"""Provider layer: the agent loop talks to ONE small interface, so the model is swappable.

    llm = get_llm(system_prompt, tool_schemas)
    llm.add_user("task text")
    turn = llm.generate()            # -> Turn(text, tool_calls)
    llm.add_tool_results([(call, result_dict), ...])

Each provider keeps its own history in its own native format."""
import json, os, time
from dataclasses import dataclass, field
from pathlib import Path

def _load_env():
    """Reads KEY=value lines from .env into os.environ (real env vars win)."""
    f = Path(__file__).resolve().parent.parent / ".env"
    if f.is_file():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

def _schema(t: dict) -> dict:
    return t.get("input_schema") or t.get("parameters") or {"type": "object", "properties": {}}


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict

@dataclass
class Turn:
    text: str = ""
    tool_calls: list = field(default_factory=list)   # empty list => model is finished


class GeminiLLM:
    def __init__(self, system: str, tool_schemas: list):
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                                   http_options=types.HttpOptions(timeout=60_000))  # 60s per call
        self.model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
        decls = []
        for t in tool_schemas:
            schema = _schema(t)
            kwargs = {"name": t["name"], "description": t["description"]}
            if schema.get("properties"):          # Gemini dislikes empty-parameter objects
                kwargs["parameters_json_schema"] = schema
            decls.append(types.FunctionDeclaration(**kwargs))
        self.config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.history = []

    def add_user(self, text: str):
        t = self.types
        self.history.append(t.Content(role="user", parts=[t.Part.from_text(text=text)]))

    def _is_daily_quota(self, e: Exception) -> bool:
        """429 'quota exceeded' (daily free-tier cap): retrying for seconds is pointless."""
        m = str(e)
        return "RESOURCE_EXHAUSTED" in m and ("PerDay" in m or "Quota exceeded" in m or "no longer available" in m)

    def generate(self) -> Turn:
        # Try the main model, then any fallbacks (GEMINI_FALLBACK_MODELS=modelA,modelB).
        fallbacks = [m.strip() for m in os.environ.get("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()]
        models = [self.model] + [m for m in fallbacks if m != self.model]
        last_error = None
        resp = None
        for mi, model in enumerate(models):
            for attempt in range(4):              # short retries for temporary overload / timeouts
                try:
                    resp = self.client.models.generate_content(
                        model=model, contents=self.history, config=self.config)
                    if mi > 0:
                        self.model = model        # stay on the model that works
                    break
                except Exception as e:
                    last_error = e
                    msg = str(e).lower()
                    if self._is_daily_quota(e) or "404" in msg:
                        print(f"  ({model}: daily quota used up or unavailable)")
                        break                     # no point retrying this model
                    transient = any(x in msg for x in ("429", "503", "500", "timeout", "timed out", "deadline", "overloaded"))
                    if not transient:
                        raise
                    wait = 5 * (attempt + 1)
                    print(f"  ({model}: busy or slow - retrying in {wait}s, attempt {attempt + 2}/4)")
                    time.sleep(wait)
            if resp is not None:
                break
            if mi + 1 < len(models):
                print(f"  [switching to fallback model: {models[mi + 1]}]")
        if resp is None:
            raise last_error
        content = resp.candidates[0].content
        self.history.append(content)              # keep the model's reply in history
        calls = [ToolCall(id=str(i), name=p.function_call.name, args=dict(p.function_call.args or {}))
                 for i, p in enumerate(content.parts or []) if p.function_call]
        text = "".join(p.text for p in (content.parts or []) if p.text)
        return Turn(text=text, tool_calls=calls)

    def add_tool_results(self, results: list):
        t = self.types
        parts = [t.Part.from_function_response(name=c.name, response=r) for c, r in results]
        self.history.append(t.Content(role="user", parts=parts))


class AnthropicLLM:
    def __init__(self, system: str, tool_schemas: list):
        from anthropic import Anthropic
        self.client = Anthropic()
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.system, self.history = system, []
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": _schema(t)}
                      for t in tool_schemas]

    def add_user(self, text: str):
        self.history.append({"role": "user", "content": text})

    def generate(self) -> Turn:
        resp = self.client.messages.create(model=self.model, max_tokens=1024,
                                           system=self.system, tools=self.tools,
                                           messages=self.history)
        self.history.append({"role": "assistant", "content": resp.content})
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        text = "".join(b.text for b in resp.content if b.type == "text")
        return Turn(text=text, tool_calls=calls)

    def add_tool_results(self, results: list):
        self.history.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(r)}
            for c, r in results]})


class OpenAILLM:
    def __init__(self, system: str, tool_schemas: list):
        from openai import OpenAI
        self.client = OpenAI(timeout=60, max_retries=4)      # built-in retry/backoff
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.tools = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": _schema(t)}}
            for t in tool_schemas]
        self.history = [{"role": "system", "content": system}]

    def add_user(self, text: str):
        self.history.append({"role": "user", "content": text})

    def generate(self) -> Turn:
        resp = self.client.chat.completions.create(
            model=self.model, messages=self.history, tools=self.tools)
        msg = resp.choices[0].message
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [{"id": c.id, "type": "function",
                                    "function": {"name": c.function.name,
                                                 "arguments": c.function.arguments}}
                                   for c in msg.tool_calls]
        self.history.append(entry)
        calls = [ToolCall(c.id, c.function.name, json.loads(c.function.arguments or "{}"))
                 for c in (msg.tool_calls or [])]
        return Turn(text=msg.content or "", tool_calls=calls)

    def add_tool_results(self, results: list):
        for c, r in results:
            self.history.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(r)})


def get_llm(system: str, tool_schemas: list):
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    return {"gemini": GeminiLLM, "anthropic": AnthropicLLM, "openai": OpenAILLM}[provider](system, tool_schemas)
