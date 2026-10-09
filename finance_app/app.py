"""Mock internal finance system: a form to record vendor invoices."""
import sqlite3
from pathlib import Path
from flask import Flask, request, redirect, jsonify, render_template_string

DB = Path(__file__).parent / "finance.db"
app = Flask(__name__)

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor TEXT, invoice_no TEXT, amount REAL, due_date TEXT)""")

PAGE = """
<h1>Finance System - Invoice Entry</h1>
<form id="invoice-form" method="post" action="/add">
  <label>Vendor <input name="vendor" id="vendor"></label><br>
  <label>Invoice No <input name="invoice_no" id="invoice_no"></label><br>
  <label>Amount (INR) <input name="amount" id="amount"></label><br>
  <label>Due Date (YYYY-MM-DD) <input name="due_date" id="due_date"></label><br>
  <button type="submit" id="save">Save</button>
</form>
<p id="message">{{ message }}</p>
<h2>Saved invoices</h2>
<table border="1" id="invoices">
<tr><th>Vendor</th><th>Invoice No</th><th>Amount</th><th>Due Date</th></tr>
{% for r in rows %}<tr><td>{{r.vendor}}</td><td>{{r.invoice_no}}</td>
<td>{{r.amount}}</td><td>{{r.due_date}}</td></tr>{% endfor %}
</table>
"""

@app.get("/")
def index():
    with db() as con:
        rows = con.execute("SELECT * FROM invoices ORDER BY id").fetchall()
    return render_template_string(PAGE, rows=rows, message=request.args.get("message", ""))

@app.post("/add")
def add():
    f = request.form
    try:
        amount = float(f["amount"].replace(",", ""))
    except (KeyError, ValueError):
        return redirect("/?message=Error: invalid amount")
    with db() as con:
        con.execute("INSERT INTO invoices (vendor, invoice_no, amount, due_date) VALUES (?,?,?,?)",
                    (f.get("vendor", ""), f.get("invoice_no", ""), amount, f.get("due_date", "")))
    return redirect("/?message=Saved")

@app.get("/api/invoices")
def api_invoices():
    with db() as con:
        return jsonify([dict(r) for r in con.execute("SELECT * FROM invoices ORDER BY id")])

if __name__ == "__main__":
    init_db()
    app.run(port=5000)
