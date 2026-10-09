"""Deterministic evaluation of the tool layer (NO model calls, so it costs no API quota).
Starts its own throw-away finance app with a temp database, runs scenarios, prints a PASS/FAIL table.

Run from the project folder, with your own finance app STOPPED:   python scripts/eval_tools.py
"""
import builtins, json, random, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import agent.tools as tools_module                       # noqa: E402
from agent.registry import Toolbox                       # noqa: E402
from agent.verifier import fetch_records, verify_invoice  # noqa: E402

URL = "http://localhost:5000/"
ACME = {"vendor": "Acme Corp", "invoice_no": "INV-102", "amount": 48200, "due_date": "2026-10-15"}
GLOBEX = {"vendor": "Globex Ltd", "invoice_no": "INV-550", "amount": 125000, "due_date": "2026-10-20"}


def server_up() -> bool:
    try:
        urllib.request.urlopen(URL, timeout=1)
        return True
    except Exception:
        return False


class TempApp:
    """Run a copy of the finance app (optionally modified) with its own empty database."""
    def __init__(self, modify=None):
        self.modify = modify

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        src = (ROOT / "finance_app" / "app.py").read_text()
        if self.modify:
            src = src.replace(*self.modify)
        (Path(self.dir.name) / "app.py").write_text(src)
        self.proc = subprocess.Popen([sys.executable, "app.py"], cwd=self.dir.name,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            if server_up():
                return self
            time.sleep(0.25)
        raise RuntimeError("temporary finance app did not start")

    def __exit__(self, *a):
        self.proc.terminate()
        self.proc.wait(timeout=10)
        self.dir.cleanup()


def with_input(answer: str, fn):
    """Run fn() while the human answers every approval prompt with `answer`."""
    real = builtins.input
    builtins.input = lambda prompt="": (print(f"   (simulated human answers: {answer})"), answer)[1]
    try:
        return fn()
    finally:
        builtins.input = real


def run_tool(name, args):
    return Toolbox().run(name, args)


RESULTS = []

def check(name, expected, ok, detail=""):
    RESULTS.append((name, expected, "PASS" if ok else "FAIL", detail))


def main() -> int:
    if server_up():
        print("A finance app is already running on port 5000. Stop it first (Ctrl+C), then rerun.")
        return 2

    # ---- Phase 0: LARGE inbox (needs no server; uses a temporary inbox, your real one is untouched) ----
    random.seed(1)
    inbox = Path(tempfile.mkdtemp())
    vendors = ["Acme Corp", "Globex Ltd", "Initech", "Umbrella Co", "Stark Industries", "Wayne Enterprises"]
    newest = {"date": "", "no": None}
    for i in range(600):
        v = random.choice(vendors)
        date = f"2026-0{random.randint(1, 9)}-{random.randint(1, 28):02d}"
        (inbox / f"{v.split()[0].lower()}_inv_{1000 + i}.txt").write_text(
            f"INVOICE\nVendor: {v}\nInvoice No: INV-{1000 + i}\nInvoice Date: {date}\nDue Date: 2026-12-01\n"
            f"Amount: INR {random.randint(1000, 200000):,}.00\nDescription: Services\n")
        if v == "Acme Corp" and date > newest["date"]:
            newest = {"date": date, "no": f"INV-{1000 + i}"}
    (inbox / "huge.txt").write_text("INVOICE\nVendor: Big\n" + "x" * 500_000)
    real_inbox, tools_module.INBOX = tools_module.INBOX, inbox
    try:
        t0 = time.time()
        r = run_tool("find_invoices", {"vendor": "acme", "limit": 3})
        ms = (time.time() - t0) * 1000
        check("600-file inbox: find newest Acme invoice", "correct invoice, small reply",
              r.get("ok") and r["invoices"][0]["invoice_no"] == newest["no"] and r["total_matches"] > 1
              and len(json.dumps(r)) < 3000, f"{r.get('total_matches')} matches, {len(json.dumps(r))} chars, {ms:.0f} ms")

        r = run_tool("list_files", {})
        check("600-file inbox: list_files is capped", "<= 50 names, reports total",
              r.get("ok") and len(r["files"]) <= 50 and r["total"] == 601, f"{len(r.get('files', []))} shown of {r.get('total')}")

        r = run_tool("read_file", {"name": "huge.txt"})
        check("500 KB file is read", "truncated to ~4000 chars",
              r.get("ok") and r.get("truncated") and len(r["content"]) < 4200, f"{len(r.get('content', ''))} chars")
    finally:
        tools_module.INBOX = real_inbox
        shutil.rmtree(inbox, ignore_errors=True)

    r = with_input("Acme Corp", lambda: run_tool("ask_user", {"question": "Which vendor do you mean?"}))
    check("Agent asks the human a question", "answer returned to the agent", r.get("ok") and r.get("answer") == "Acme Corp", str(r))

    # ---- Phase 1: normal app ----
    with TempApp():
        r = run_tool("save_to_finance_app", ACME)
        check("Normal invoice (Acme, Rs 48,200)", "saved + verified",
              r.get("ok") and verify_invoice(**ACME)["verified"], str(r.get("message", r.get("error"))))

        r = run_tool("save_to_finance_app", ACME)
        check("Same invoice entered twice", "refused, still 1 record",
              (not r.get("ok")) and "already exists" in r.get("error", "") and len(fetch_records()) == 1,
              r.get("error", ""))

        v = verify_invoice("Acme Corp", "INV-102", 99999, "2026-10-15")
        check("System holds wrong amount", "verifier catches it", (not v["verified"]) and "amount" in v["reason"], v["reason"])

        v = verify_invoice("Acme Corp", "INV-102", 48200, "2099-01-01")
        check("System holds wrong due date", "verifier catches it", (not v["verified"]) and "due date" in v["reason"], v["reason"])

        v = verify_invoice("Nobody", "INV-999", 1, "2026-01-01")
        check("Invoice never saved", "verifier catches it", (not v["verified"]) and "no saved record" in v["reason"], v["reason"])

        before = len(fetch_records())
        r = with_input("no", lambda: run_tool("save_to_finance_app", GLOBEX))
        check("High value, human says NO", "aborted, nothing written",
              (not r.get("ok")) and "denied" in r.get("error", "") and len(fetch_records()) == before, r.get("error", ""))

        r = with_input("yes", lambda: run_tool("save_to_finance_app", GLOBEX))
        check("High value, human says YES", "saved + verified",
              r.get("ok") and verify_invoice(**GLOBEX)["verified"], str(r.get("message", r.get("error"))))

        r = run_tool("read_file", {"name": "../finance_app/app.py"})
        check("Path escape (../finance_app/app.py)", "blocked", (not r.get("ok")) and "outside inbox" in r.get("error", ""), r.get("error", ""))

        r = run_tool("delete_everything", {})
        check("Model calls a tool that doesn't exist", "clean error", (not r.get("ok")) and "Unknown tool" in r.get("error", ""), r.get("error", ""))

        r = run_tool("read_file", {})
        check("Model forgets a required argument", "clean error, no crash", not r.get("ok"), r.get("error", "")[:70])

    # ---- Phase 2: UI changed (vendor field renamed) ----
    with TempApp(modify=('id="vendor"', 'id="vendor_name"')):
        r = run_tool("save_to_finance_app", ACME)
        check("Web form changed (field renamed)", "clear error, nothing saved",
              (not r.get("ok")) and "failed" in r.get("error", "") and len(fetch_records()) == 0, r.get("error", "")[:70])

    # ---- Phase 3: finance system down ----
    r = run_tool("save_to_finance_app", ACME)
    check("Finance system down", "clear error, no false success", (not r.get("ok")) and "not reachable" in r.get("error", ""), r.get("error", "")[:70])

    # ---- Report ----
    w = max(len(n) for n, *_ in RESULTS)
    print("\n" + "=" * (w + 62))
    print(f"{'SCENARIO':<{w}}  {'EXPECTED':<30} RESULT")
    print("-" * (w + 62))
    for n, e, res, d in RESULTS:
        print(f"{n:<{w}}  {e:<30} {res}")
    passed = sum(1 for *_, res, _d in RESULTS if res == "PASS")
    print("-" * (w + 62))
    print(f"{passed}/{len(RESULTS)} passed")
    for n, e, res, d in RESULTS:
        if res == "FAIL":
            print(f"FAILED: {n} -> {d}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
