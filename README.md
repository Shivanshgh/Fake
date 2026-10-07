# ATM HFC

Offline, touchscreen-style ATM kiosk demonstration. Every customer and transaction is fictional. This demo does not connect to payment networks or real banking systems.

## Requirements

- Python 3.9 or newer
- `pip install flask requests`

## Run locally

Open two terminals in this folder. Start the mock bank first:

```bash
python mock_bank.py
```

Then start the kiosk:

```bash
python app.py
```

Open `http://127.0.0.1:5000` in Chromium. The bank dashboard is at `http://127.0.0.1:6000`. Use Chromium kiosk mode for a fullscreen demo, for example `chromium --kiosk http://127.0.0.1:5000`.

If running the bank on another computer, set `BANK_URL` on the kiosk machine to its reachable address, such as `http://192.0.2.20:6000`. The bank listener binds to `0.0.0.0:6000` for this purpose; allow that port only on the demo network. The kiosk itself binds only to `127.0.0.1:5000`.

## Fake cards

| Customer | Card number | PIN | Starting balance |
| --- | --- | --- | ---: |
| Alex Morgan | 4111111111111234 | 1234 | $12,500 |
| Jordan Lee | 5555555555555678 | 2468 | $300 |
| Casey Patel | 4000000000009012 | 4321 | $48,200 |

Balances, PINs, daily withdrawal totals, ledger entries, and audit events live in the bank process's memory and reset when it restarts or when **Reset demo data** is pressed. The kiosk keeps only its active card/PIN authentication state in a process-memory dictionary; it does not persist session state to disk or browser storage. The kiosk fetches balance and statement details from the bank when requested. Its anonymous audit events contain a random transaction ID, timestamp, amount, and success flag, and are sent to the bank.

The kiosk uses one process-wide active session, suitable for one kiosk browser. A 30-second idle timeout and Exit clear the session. Do not expose this unauthenticated mock bank outside an isolated demo network.

Set `BAD_UPDATE=1` when launching `app.py` to intentionally fail startup for rollback demonstrations (`BAD_UPDATE=1 python app.py` on Linux/macOS; `$env:BAD_UPDATE='1'; python app.py` in PowerShell).

## Endpoints

- Kiosk: `GET /`, `GET /health`, `GET /status`, `POST /api/end-session`
- Mock bank: dashboard at `GET /`, API under `/api/`

The status strip reads Linux mount and swap information and checks `usbguard list-devices` when available. Non-Linux hosts report clearly labelled demo values.

## Desktop app

The Electron desktop shell can be launched with Node.js installed:

```bash
npm install
npm start
```

To create a Windows installer:

```bash
npm run build
```

Build output is written to `dist/` and is intentionally excluded from Git. Attach release installers to a GitHub Release if you want to distribute them.
