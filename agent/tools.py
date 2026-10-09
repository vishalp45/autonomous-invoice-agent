"""Tools the agent can call. Each returns a dict: {"ok": bool, ...}.
Errors are returned (not raised) so the model can read them and react."""
import re
from pathlib import Path
from agent.verifier import fetch_records, verify_invoice
from agent.browser import BrowserTools
INBOX = Path(__file__).resolve().parent.parent / "inbox"
MAX_LIST = 50          # never send the model more than this many file names
MAX_READ_CHARS = 4000  # never send the model more than this much of one file

def _safe_path(name: str) -> Path:
    """Resolve a name inside the inbox; refuse anything that escapes it."""
    p = (INBOX / name).resolve()
    if INBOX.resolve() not in p.parents and p != INBOX.resolve():
        raise PermissionError(f"Access outside inbox is not allowed: {name}")
    return p

def list_files(pattern: str = "*") -> dict:
    """List files in the inbox (max 50 names shown; reports the total). Use a glob like '*acme*' to narrow."""
    try:
        files = sorted(f.name for f in INBOX.glob(pattern) if f.is_file())
        out = {"ok": True, "files": files[:MAX_LIST], "total": len(files)}
        if len(files) > MAX_LIST:
            out["note"] = f"Only the first {MAX_LIST} of {len(files)} files are shown. Narrow the pattern or use find_invoices."
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}


def read_file(name: str) -> dict:
    """Read the text of one file in the inbox."""
    try:
        p = _safe_path(name)
        if not p.is_file():
            return {"ok": False, "error": f"File not found: {name}"}
        text = p.read_text(errors="ignore")
        if len(text) > MAX_READ_CHARS:
            return {"ok": True, "content": text[:MAX_READ_CHARS] + "\n[...truncated...]", "truncated": True}
        return {"ok": True, "content": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _field(text: str, key: str):
    m = re.search(rf"^{key}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def find_invoices(vendor: str = "", limit: int = 5) -> dict:
    """Search ALL inbox invoices by vendor name (case-insensitive). Returns the newest first, by Invoice Date.
    Cheap on huge inboxes: the model receives at most `limit` (max 20) summaries, never every file."""
    try:
        rows = []
        for f in sorted(INBOX.glob("*.txt")):
            text = f.read_text(errors="ignore")[:MAX_READ_CHARS]
            v = _field(text, "Vendor")
            if v is None or vendor.lower() not in v.lower():
                continue
            amt = re.sub(r"[^\d.]", "", _field(text, "Amount") or "")
            rows.append({"file": f.name, "vendor": v, "invoice_no": _field(text, "Invoice No"),
                         "invoice_date": _field(text, "Invoice Date"), "due_date": _field(text, "Due Date"),
                         "amount": float(amt) if amt else None})
        rows.sort(key=lambda r: r["invoice_date"] or "", reverse=True)
        limit = max(1, min(int(limit), 20))
        return {"ok": True, "total_matches": len(rows), "showing": min(limit, len(rows)), "invoices": rows[:limit]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def ask_user(question: str) -> dict:
    """Ask the human a question when the request is ambiguous or something is missing."""
    print(f"\n\u2753 AGENT NEEDS INPUT: {question}")
    answer = input("Your answer: ").strip()
    return {"ok": True, "answer": answer}


def requires_human_approval(amount: float, vendor: str) -> bool:
    """
    Pauses execution and requests terminal input for high-value invoices.
    """
    threshold = 100000.00
    
    if amount > threshold:
        print(f"\n⚠️ APPROVAL REQUIRED: High-value invoice detected.")
        print(f"Vendor: {vendor} | Amount: ₹{amount:,.2f}")
        
        while True:
            response = input("Approve saving this invoice to the internal system? (yes/no): ").strip().lower()
            if response in ['yes', 'y']:
                print("✅ Approved by user. Proceeding with execution.")
                return True
            elif response in ['no', 'n']:
                print("🚫 Rejected by user. Halting task.")
                return False
            else:
                print("Please enter 'yes' or 'no'.")
                
    return True # Automatically proceed if under threshold



def save_to_finance_app(vendor: str, invoice_no: str, amount: float, due_date: str) -> dict:
    """Save an invoice through the finance web form, then VERIFY it was really saved.
    Order: duplicate check -> human approval (high value) -> fill form -> verify saved record."""
    # 1. Idempotency: never enter the same invoice twice (e.g. after a retry)
    try:
        if any(r["invoice_no"] == invoice_no for r in fetch_records()):
            return {"ok": False, "error": f"Invoice {invoice_no} already exists in the finance system; not entering a duplicate."}
    except Exception as e:
        return {"ok": False, "error": f"Finance system not reachable: {e}"}

    # 2. Human approval is enforced here in code, so the model cannot skip it
    if not requires_human_approval(amount, vendor):
        return {"ok": False, "error": "Action aborted: Human denied the transaction."}

    b = None
    try:
        b = BrowserTools()
        steps = [                                    # lambdas: run ONE at a time, stop at first failure
            ("open page", lambda: b.open_page("http://localhost:5000/")),
            ("fill vendor", lambda: b.fill("#vendor", vendor)),
            ("fill invoice_no", lambda: b.fill("#invoice_no", invoice_no)),
            ("fill amount", lambda: b.fill("#amount", str(amount))),
            ("fill due_date", lambda: b.fill("#due_date", due_date)),
            ("click save", lambda: b.click("#save")),
        ]
        for name, action in steps:
            res = action()
            if not res.get("ok"):                    # never reach "save" if an earlier step failed
                return {"ok": False, "error": f"Browser step '{name}' failed: {res.get('error')}"}
        shot = b.screenshot(f"{invoice_no}.png")
    except Exception as e:
        return {"ok": False, "error": f"Browser automation failed: {e}"}
    finally:
        if b:
            b.close()                                # always release the browser

    # 3. Independent verification of the real saved record
    check = verify_invoice(vendor, invoice_no, amount, due_date)
    if not check["verified"]:
        return {"ok": False, "error": f"Saved but verification FAILED: {check['reason']}", "record": check["record"]}
    return {"ok": True, "message": "Saved and verified against the finance system.",
            "saved_record": check["record"], "evidence": shot.get("path")}
