import os
import platform
import secrets
import subprocess
import threading
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request

if os.environ.get("BAD_UPDATE") == "1":
    raise RuntimeError("BAD_UPDATE=1: intentional startup failure for rollback demo")

app = Flask(__name__)
BANK_URL = os.environ.get("BANK_URL", "http://127.0.0.1:6000").rstrip("/")
IDLE_SECONDS = 30
DAILY_LIMIT = 10000
# This process-wide kiosk demo assumes one physical kiosk/browser at a time.
# Never serialize this object, expose it in API responses, or log its contents.
_session = {}
_session_lock = threading.RLock()


def _bank(method, path, **kwargs):
    response = requests.request(method, BANK_URL + path, timeout=3, **kwargs)
    response.raise_for_status()
    return response.json()


def _clear_session():
    with _session_lock:
        _session.clear()


def _expire_if_idle():
    with _session_lock:
        if _session and time.monotonic() - _session.get("last_activity", 0) >= IDLE_SECONDS:
            _session.clear()
            return True
        return False


def _touch():
    with _session_lock:
        if _session:
            _session["last_activity"] = time.monotonic()


def _active():
    _expire_if_idle()
    with _session_lock:
        return bool(_session)


def _audit(amount, success):
    # Anonymous kiosk event: no account identifiers or personal data.
    event = {"transaction_id": "ATM-" + secrets.token_hex(6).upper(),
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "amount": int(amount), "success": bool(success)}
    try:
        _bank("POST", "/api/audit", json=event)
    except requests.RequestException:
        pass


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.get("/status")
def status():
    version = "unknown"
    try:
        with open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8") as f:
            version = f.read().strip()
    except OSError:
        pass
    linux = platform.system() == "Linux"
    if not linux:
        return jsonify({"platform": "Demo values (non-Linux)", "root": {"label": "Demo: Read-only", "ok": True},
                        "swap": {"label": "Demo: Disabled", "ok": True},
                        "session": {"label": "RAM only", "ok": True},
                        "usb": {"label": "Demo: Unknown", "ok": False}, "version": version})
    root_label, root_ok = "Unknown", False
    try:
        with open("/proc/mounts", encoding="utf-8") as mounts:
            for line in mounts:
                fields = line.split()
                if len(fields) >= 4 and fields[1] == "/":
                    opts, fs = fields[3].split(","), fields[2]
                    root_ok = "ro" in opts or fs == "overlay"
                    root_label = "Read-only" if root_ok else "Writable"
                    if fs == "overlay":
                        root_label = "Read-only (overlay)" if root_ok else "Writable (overlay)"
                    break
    except OSError:
        pass
    swap_label, swap_ok = "Unknown", False
    try:
        with open("/proc/swaps", encoding="utf-8") as swaps:
            rows = swaps.read().splitlines()[1:]
        swap_ok = not rows
        swap_label = "Disabled" if swap_ok else "Enabled"
    except OSError:
        pass
    usb_label, usb_ok = "Unknown", False
    try:
        result = subprocess.run(["usbguard", "list-devices"], capture_output=True,
                                text=True, timeout=2, check=True)
        blocked = sum(1 for line in result.stdout.splitlines()
                      if " block " in f" {line.lower()} " or " reject " in f" {line.lower()} ")
        usb_ok, usb_label = True, f"Locked ({blocked} blocked)"
    except (OSError, subprocess.SubprocessError):
        pass
    return jsonify({"platform": "Linux", "root": {"label": root_label, "ok": root_ok},
                    "swap": {"label": swap_label, "ok": swap_ok},
                    "session": {"label": "RAM only", "ok": True},
                    "usb": {"label": usb_label, "ok": usb_ok}, "version": version})


@app.get("/api/cards")
def cards():
    try:
        return jsonify(_bank("GET", "/api/cards"))
    except requests.RequestException:
        return jsonify({"error": "service_unavailable"}), 503


@app.post("/api/insert")
def insert_card():
    card_id = str((request.get_json(silent=True) or {}).get("card_id", ""))
    try:
        result = _bank("POST", "/api/lookup", json={"card_id": card_id})
    except requests.RequestException:
        return jsonify({"error": "service_unavailable"}), 503
    if not result.get("found") or not result.get("card"):
        return jsonify({"error": "card_unavailable"}), 404
    _clear_session()
    with _session_lock:
        _session.update({"card": result["card"], "pin": None, "failures": 0,
                         "locked": False, "last_activity": time.monotonic()})
    return jsonify({"ok": True})


@app.post("/api/pin")
def verify_pin():
    if not _active():
        return jsonify({"error": "session_expired"}), 401
    pin = str((request.get_json(silent=True) or {}).get("pin", ""))
    with _session_lock:
        if _session.get("locked"):
            return jsonify({"error": "card_locked"}), 423
        card = _session["card"]
    try:
        result = _bank("POST", "/api/verify-pin", json={"card": card, "pin": pin})
    except requests.RequestException:
        return jsonify({"error": "service_unavailable"}), 503
    with _session_lock:
        if result.get("valid"):
            _session["pin"] = pin
            _session["failures"] = 0
            _touch()
            return jsonify({"ok": True})
        _session["failures"] = _session.get("failures", 0) + 1
        if _session["failures"] >= 3:
            _session["locked"] = True
            return jsonify({"error": "card_locked"}), 423
    _touch()
    return jsonify({"error": "incorrect_pin", "attempts_left": 3 - _session["failures"]}), 401


@app.before_request
def track_activity():
    if request.path.startswith("/api/") and request.path not in ("/api/cards", "/api/insert", "/api/end-session"):
        _touch()


@app.get("/api/session")
def session_status():
    expired = _expire_if_idle()
    with _session_lock:
        remaining = max(0, IDLE_SECONDS - int(time.monotonic() - _session.get("last_activity", time.monotonic()))) if _session else 0
        return jsonify({"active": bool(_session), "remaining": remaining, "expired": expired})


@app.post("/api/end-session")
def end_session():
    _clear_session()
    return jsonify({"ok": True})


def require_pin():
    if not _active():
        return None, (jsonify({"error": "session_expired"}), 401)
    with _session_lock:
        if not _session.get("pin"):
            return None, (jsonify({"error": "authentication_required"}), 401)
        return _session["card"], None


@app.get("/api/balance")
def balance():
    card, error = require_pin()
    if error:
        return error
    try:
        return jsonify(_bank("POST", "/api/balance", json={"card": card}))
    except requests.RequestException:
        return jsonify({"error": "service_unavailable"}), 503


@app.get("/api/statement")
def statement():
    card, error = require_pin()
    if error:
        return error
    try:
        return jsonify(_bank("POST", "/api/statement", json={"card": card}))
    except requests.RequestException:
        return jsonify({"error": "service_unavailable"}), 503


@app.post("/api/withdraw")
def withdraw():
    card, error = require_pin()
    if error:
        return error
    amount = (request.get_json(silent=True) or {}).get("amount")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0 or amount % 100:
        _audit(amount, False)
        return jsonify({"error": "invalid_amount"}), 400
    try:
        result = _bank("POST", "/api/withdraw", json={"card": card, "amount": amount, "daily_limit": DAILY_LIMIT})
    except requests.RequestException:
        return jsonify({"error": "service_unavailable"}), 503
    _audit(amount, result.get("ok", False))
    if not result.get("ok"):
        return jsonify({"error": result.get("error", "withdraw_failed")}), 400
    return jsonify(result)


@app.post("/api/deposit")
def deposit():
    card, error = require_pin()
    if error:
        return error
    amount = (request.get_json(silent=True) or {}).get("amount")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0 or amount % 100:
        _audit(amount, False)
        return jsonify({"error": "invalid_amount"}), 400
    try:
        result = _bank("POST", "/api/deposit", json={"card": card, "amount": amount})
    except requests.RequestException:
        return jsonify({"error": "service_unavailable"}), 503
    _audit(amount, result.get("ok", False))
    if not result.get("ok"):
        return jsonify({"error": result.get("error", "deposit_failed")}), 400
    return jsonify(result)


@app.post("/api/change-pin")
def change_pin():
    card, error = require_pin()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    old_pin, new_pin = str(data.get("old_pin", "")), str(data.get("new_pin", ""))
    if len(new_pin) != 4 or not new_pin.isdigit():
        return jsonify({"error": "pin_format"}), 400
    try:
        result = _bank("POST", "/api/change-pin", json={"card": card, "old_pin": old_pin, "new_pin": new_pin})
    except requests.RequestException:
        return jsonify({"error": "service_unavailable"}), 503
    if result.get("ok"):
        with _session_lock:
            _session["pin"] = new_pin
        return jsonify({"ok": True})
    return jsonify({"error": result.get("error", "pin_change_failed")}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
