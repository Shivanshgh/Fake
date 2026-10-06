import secrets
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
LOCK = threading.RLock()
SEED = [
    {"card": "4111111111111234", "pin": "1234", "name": "Alex Morgan", "balance": 12500},
    {"card": "5555555555555678", "pin": "2468", "name": "Jordan Lee", "balance": 300},
    {"card": "4000000000009012", "pin": "4321", "name": "Casey Patel", "balance": 48200},
]
customers = {}
ledger = []
audit_events = []


def reset_data():
    with LOCK:
        customers.clear()
        for item in SEED:
            customers[item["card"]] = {**item, "daily_total": 0, "last_transaction": "No transactions"}
        ledger.clear()
        audit_events.clear()


reset_data()


def masked(card):
    return "XXXX XXXX XXXX " + card[-4:]


@app.get("/")
def dashboard():
    return render_template_string(DASHBOARD)


@app.get("/api/dashboard")
def dashboard_data():
    with LOCK:
        rows = [{"name": c["name"], "card": masked(card), "balance": c["balance"],
                 "last": c["last_transaction"]} for card, c in customers.items()]
        events = list(reversed(ledger[-30:]))
        audits = list(reversed(audit_events[-20:]))
    return jsonify({"customers": rows, "transactions": events, "audits": audits})


@app.post("/api/reset")
def reset():
    reset_data()
    return jsonify({"ok": True})


@app.get("/api/cards")
def cards():
    with LOCK:
        return jsonify([{"card_id": f"demo-{index + 1}", "name": item["name"], "last4": card[-4:]}
                        for index, (card, item) in enumerate(customers.items())])


@app.post("/api/lookup")
def lookup():
    card_id = str((request.get_json(silent=True) or {}).get("card_id", ""))
    with LOCK:
        try:
            index = int(card_id.removeprefix("demo-")) - 1
            card = list(customers.keys())[index]
        except (ValueError, IndexError):
            card = ""
        item = customers.get(card)
        return jsonify({"found": bool(item), "card": card if item else None})


@app.post("/api/verify-pin")
def verify_pin():
    data = request.get_json(silent=True) or {}
    with LOCK:
        item = customers.get(str(data.get("card", "")))
        return jsonify({"valid": bool(item and secrets.compare_digest(item["pin"], str(data.get("pin", ""))))})


@app.post("/api/balance")
def balance():
    card = str((request.get_json(silent=True) or {}).get("card", ""))
    with LOCK:
        item = customers.get(card)
        if not item:
            return jsonify({"error": "card_unavailable"}), 404
        return jsonify({"balance": item["balance"]})


@app.post("/api/statement")
def statement():
    card = str((request.get_json(silent=True) or {}).get("card", ""))
    with LOCK:
        if card not in customers:
            return jsonify({"error": "card_unavailable"}), 404
        rows = [t for t in ledger if t["card"] == card][-5:]
        return jsonify({"transactions": [{k: t[k] for k in ("id", "masked_card", "amount", "time", "balance", "type")}
                                          for t in rows]})


@app.post("/api/withdraw")
def withdraw():
    data = request.get_json(silent=True) or {}
    card = str(data.get("card", ""))
    try:
        amount, limit = int(data.get("amount", 0)), int(data.get("daily_limit", 10000))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_amount"}), 400
    with LOCK:
        item = customers.get(card)
        if not item:
            return jsonify({"ok": False, "error": "card_unavailable"}), 404
        if amount <= 0 or amount % 100:
            return jsonify({"ok": False, "error": "invalid_amount"}), 400
        if item["daily_total"] + amount > limit:
            return jsonify({"ok": False, "error": "daily_limit"}), 400
        if amount > item["balance"]:
            return jsonify({"ok": False, "error": "insufficient_funds"}), 400
        item["balance"] -= amount
        item["daily_total"] += amount
        when = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        tx = {"id": "TX-" + secrets.token_hex(4).upper(), "card": card, "masked_card": masked(card),
              "name": item["name"], "amount": amount, "time": when,
              "balance": item["balance"], "type": "Cash withdrawal"}
        ledger.append(tx)
        item["last_transaction"] = f"Withdrawal {amount} · {when}"
        return jsonify({"ok": True, "transaction": {k: v for k, v in tx.items() if k not in ("card", "name")}})


@app.post("/api/change-pin")
def change_pin():
    data = request.get_json(silent=True) or {}
    card = str(data.get("card", ""))
    with LOCK:
        item = customers.get(card)
        if not item or not secrets.compare_digest(item["pin"], str(data.get("old_pin", ""))):
            return jsonify({"ok": False, "error": "incorrect_pin"}), 400
        item["pin"] = str(data.get("new_pin", ""))
    return jsonify({"ok": True})


@app.post("/api/audit")
def audit():
    data = request.get_json(silent=True) or {}
    event = {"transaction_id": str(data.get("transaction_id", ""))[:40],
             "timestamp": str(data.get("timestamp", ""))[:40],
             "amount": int(data.get("amount", 0)), "success": bool(data.get("success"))}
    with LOCK:
        audit_events.append(event)
    return jsonify({"ok": True})


DASHBOARD = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ATM HFC · Bank dashboard</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#080b15;color:#eff2ff;font:18px/1.5 system-ui,Segoe UI,sans-serif;padding:32px;background-image:radial-gradient(ellipse at 20% 0,#18245b 0,transparent 45%),radial-gradient(ellipse at 85% 15%,#32194e 0,transparent 38%)}main{max-width:1450px;margin:auto}h1{font-size:38px;margin:0 0 6px}h2{font-size:23px;margin:0 0 16px}.banner,.panel{border:1px solid #ffffff20;background:#111827df;border-radius:20px;padding:22px;margin:22px 0;box-shadow:0 15px 60px #0006}.banner{background:linear-gradient(110deg,#173c71,#462875);font-weight:650}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid #ffffff15;padding:12px 8px}th{color:#aebef8}button{border:0;border-radius:12px;padding:14px 20px;color:white;font-weight:700;background:#5e57e8;cursor:pointer;min-height:52px}.feed{max-height:350px;overflow:auto}.event{padding:11px;border-bottom:1px solid #ffffff15}.dim{color:#abb4d2}@media(max-width:850px){.grid{grid-template-columns:1fr}body{padding:16px}}
</style></head><body><main><h1>ATM HFC · Bank console</h1><div class="dim">Mock bank server · demo data only</div><div class="banner">Kiosk stores no customer data. The bank is the source of truth.</div>
<section class="panel"><h2>Customers</h2><table><thead><tr><th>Customer</th><th>Card</th><th>Balance</th><th>Last transaction</th></tr></thead><tbody id="customers"></tbody></table></section>
<div class="grid"><section class="panel"><h2>Live transaction feed</h2><div class="feed" id="transactions"></div></section><section class="panel"><h2>Anonymous kiosk audit</h2><div class="feed" id="audits"></div></section></div><button id="reset">Reset demo data</button></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function refresh(){try{const r=await fetch('/api/dashboard');const d=await r.json();document.querySelector('#customers').innerHTML=d.customers.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.card)}</td><td>$${Number(c.balance).toLocaleString()}</td><td>${esc(c.last)}</td></tr>`).join('');document.querySelector('#transactions').innerHTML=d.transactions.length?d.transactions.map(t=>`<div class="event"><b>${esc(t.type)}</b> · $${Number(t.amount).toLocaleString()}<br><span class="dim">${esc(t.name)} · ${esc(t.time)} · ${esc(t.id)}</span></div>`).join(''):'<div class="dim">No transactions yet</div>';document.querySelector('#audits').innerHTML=d.audits.length?d.audits.map(a=>`<div class="event">${a.success?'✓':'✕'} $${Number(a.amount).toLocaleString()} · ${esc(a.transaction_id)}<br><span class="dim">${esc(a.timestamp)}</span></div>`).join(''):'<div class="dim">No audit events yet</div>'}catch{}}
document.querySelector('#reset').onclick=async()=>{await fetch('/api/reset',{method:'POST'});refresh()};refresh();setInterval(refresh,2000);
</script></body></html>'''


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000, threaded=True)
