"""The agent loop. YOU write the TODOs. See notes/01_agent_loop.md for hints."""
from agent.llm import get_llm
from agent.registry import TOOL_SCHEMAS, Toolbox
import requests

MAX_STEPS = 15

SYSTEM = """You are an AI worker for a company. Complete the user's task using the tools.
Inbox files are invoices. The finance system is at http://localhost:5000/.
Work step by step, check results after each action, and verify the outcome before finishing.Be efficient: call list_files once, then read all relevant files in a single step.
Do not repeat a tool call whose result you already have.Prefer find_invoices to locate invoices. If the request is ambiguous or no matching invoice exists, use ask_user instead of guessing.
In your final answer include the saved record and the evidence file path."""

def verify_outcome(expected_vendor: str, expected_amount: float) -> bool:
    """
    Verifies the invoice was saved by querying the finance app directly, 
    bypassing the AI to ensure ground-truth completion.
    """
    print(f"\n🔍 [VERIFIER] Checking finance app for {expected_vendor} (₹{expected_amount})...")
    try:
        # Fetch all saved invoices from the simulated finance app
        response = requests.get("http://localhost:5000/api/invoices")
        if response.status_code == 200:
            saved_invoices = response.json()
            for entry in saved_invoices:
                if entry.get('vendor', '').lower() == expected_vendor.lower() and float(entry.get('amount', 0)) == float(expected_amount):
                    print("✅ [VERIFIER] Passed: Invoice successfully found in the finance app records.\n")
                    return True
        print("❌ [VERIFIER] Failed: Invoice not found in the finance app records.\n")
        return False
    except Exception as e:
        print(f"❌ [VERIFIER] Error: Could not connect to finance app ({e})\n")
        return False

def run_agent(task: str, verify_vendor: str = None, verify_amount: float = None) -> str:
    llm = get_llm(SYSTEM, TOOL_SCHEMAS)
    toolbox = Toolbox()
    llm.add_user(task)

    try:
        for step in range(MAX_STEPS):
            turn = llm.generate()

            if not turn.tool_calls:
                # 1. AI indicates it is finished.
                # 2. Run the hardcoded independent verifier if test criteria were provided.
                if verify_vendor and verify_amount:
                    verify_outcome(verify_vendor, verify_amount)
                    
                # 3. Return the AI's final text summary.
                return turn.text
            
            pairs = []
            for call in turn.tool_calls:
                result = toolbox.run(call.name, call.args)
                print(f"[step {step}] {call.name}({call.args}) -> {result}")
                pairs.append((call, result))

            llm.add_tool_results(pairs)
            
        return "Stopped: reached the step limit without finishing."
    finally:
        toolbox.close()