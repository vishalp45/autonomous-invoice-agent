"""Testing scripts: Hard-coded baseline and Mock Agent loop."""
import re, sys, json, urllib.request
sys.path.insert(0, ".")
from agent.tools import list_files, read_file
from agent.browser import BrowserTools
from agent.loop import run_agent
from agent.llm import MockLLM
import agent.loop 

def parse(text):
    get = lambda k: re.search(rf"{k}:\s*(.+)", text).group(1).strip()
    return {"vendor": get("Vendor"), "invoice_no": get("Invoice No"),
            "invoice_date": get("Invoice Date"), "due_date": get("Due Date"),
            "amount": float(re.sub(r"[^\d.]", "", get("Amount")))}

def run_manual_baseline():
    """Hard-coded baseline: NO AI. Proves the world + tools work end to end."""
    print("--- RUNNING MANUAL BASELINE ---")
    invoices = [parse(read_file(f)["content"]) for f in list_files("*acme*")["files"]]
    latest = max(invoices, key=lambda i: i["invoice_date"])
    print("Latest:", latest)

    b = BrowserTools()
    b.open_page("http://localhost:5000/")
    b.fill("#vendor", latest["vendor"]); b.fill("#invoice_no", latest["invoice_no"])
    b.fill("#amount", str(latest["amount"])); b.fill("#due_date", latest["due_date"])
    b.click("#save")
    b.screenshot("manual_run.png"); b.close()

    rows = json.load(urllib.request.urlopen("http://localhost:5000/api/invoices"))
    ok = any(r["invoice_no"] == latest["invoice_no"] and r["amount"] == latest["amount"]
             and r["due_date"] == latest["due_date"] for r in rows)
    print("VERIFIED" if ok else "FAILED", rows)

def test_mock_agent():
    """Tests the agent loop, approval gate, and verifier using a mocked LLM script."""
    print("\n--- RUNNING MOCK AGENT TEST ---")
    globex_test_script = [
        {"tool": "list_files", "args": {"pattern": "*globex*"}},
        {"tool": "read_file", "args": {"name": "globex_inv_550.txt"}},
        {"tool": "save_to_finance_app", "args": {
            "vendor": "Globex Ltd", 
            "invoice_no": "INV-550", 
            "amount": 150000.00, 
            "due_date": "2026-10-20"
        }}
    ]

    # Inject the mock LLM into the loop
    agent.loop.get_llm = lambda system, schemas: MockLLM(globex_test_script)

    final_result = run_agent(
        task="Process the Globex invoice.", 
        verify_vendor="Globex Ltd", # <-- Updated to match the form entry
        verify_amount=150000.00
    )
    print(f"\nFinal Agent Output: {final_result}")

if __name__ == "__main__":
    # Comment one out to run exactly what you want to test
    # run_manual_baseline()
    test_mock_agent()