"""Independent verifier: reads the finance system's REAL records, never the agent's claims."""
import json
import urllib.request

API = "http://localhost:5000/api/invoices"


def fetch_records() -> list:
    with urllib.request.urlopen(API, timeout=5) as r:
        return json.load(r)


def verify_invoice(vendor: str, invoice_no: str, amount: float, due_date: str) -> dict:
    """Return {"verified": bool, "reason": str, "record": dict|None}."""
    try:
        records = fetch_records()
    except Exception as e:
        return {"verified": False, "reason": f"could not read finance system: {e}", "record": None}

    matches = [r for r in records if r["invoice_no"] == invoice_no]
    if not matches:
        return {"verified": False, "reason": f"no saved record with invoice_no {invoice_no}", "record": None}
    if len(matches) > 1:
        return {"verified": False, "reason": f"{len(matches)} duplicate records for {invoice_no}", "record": matches[0]}

    rec = matches[0]
    problems = []
    if rec["vendor"] != vendor:
        problems.append(f"vendor saved as '{rec['vendor']}', expected '{vendor}'")
    if abs(float(rec["amount"]) - float(amount)) > 0.01:
        problems.append(f"amount saved as {rec['amount']}, expected {amount}")
    if rec["due_date"] != due_date:
        problems.append(f"due date saved as '{rec['due_date']}', expected '{due_date}'")
    if problems:
        return {"verified": False, "reason": "; ".join(problems), "record": rec}
    return {"verified": True, "reason": "saved record matches the invoice", "record": rec}
