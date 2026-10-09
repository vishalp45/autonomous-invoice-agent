"""Tool registry and schemas for the agent."""
from agent.tools import list_files, read_file, save_to_finance_app, find_invoices, ask_user

TOOL_SCHEMAS = [
    {
        "name": "list_files",
        "description": "List files in the inbox, optionally filtered by a glob pattern like '*acme*'.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files. Defaults to '*'."
                }
            }
        }
    },
    {
        "name": "read_file",
        "description": "Read the text of one file in the inbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The exact name of the file to read."
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "find_invoices",
        "description": "Search ALL invoices in the inbox by vendor name (partial match, case-insensitive). Returns the newest first with invoice_no, dates, amount and file name. Prefer this over listing/reading many files, especially when the inbox is large.",
        "parameters": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string", "description": "Vendor name or part of it, e.g. 'acme'."},
                "limit": {"type": "integer", "description": "How many newest invoices to return (default 5, max 20)."}
            },
            "required": ["vendor"]
        }
    },
    {
        "name": "ask_user",
        "description": "Ask the human a question when the request is ambiguous (e.g. several matching vendors) or information is missing. Do not guess.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"]
        }
    },
    {
        "name": "save_to_finance_app",
        "description": "Saves an invoice to the internal finance system using the browser UI.",
        "parameters": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "invoice_no": {"type": "string"},
                "amount": {"type": "number"},
                "due_date": {"type": "string"}
            },
            "required": ["vendor", "invoice_no", "amount", "due_date"]
        }
    }
]

class Toolbox:
    def __init__(self):
        self.tools = {
            "list_files": list_files,
            "read_file": read_file,
            "save_to_finance_app": save_to_finance_app,
            "find_invoices": find_invoices,
            "ask_user": ask_user
        }

    def run(self, name: str, args: dict) -> dict:
        """Run a tool by name with the given arguments."""
        if name not in self.tools:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            return self.tools[name](**args)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close(self):
        """Clean up any resources if needed."""
        pass