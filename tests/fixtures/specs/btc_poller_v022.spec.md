# BTC Price Poller with Prometheus Metrics (v0.2.2 baseline — pre-evaluator)

**Generated:** 2026-05-05
**Slug:** btc-price-poller-with-prometheus-metrics

## 1. Hard Problem

Polling an external API at regular intervals and exposing the result as a Prometheus
gauge requires a persistent process, a bound TCP port, and a mechanism that survives
reboots. Partial installs leave the host exposing a port with no process behind it.

## 2. First Principles

- Prometheus scrape targets expect a stable port that stays open between polls.
- BTC price feeds impose per-minute rate limits; polling faster than 60 s is wasteful.
- The poller must restart automatically on crash or reboot.
- Log files accumulate unboundedly without rotation — 10-row CSV cap keeps the fixture simple.
- `/tmp/btc-prices/log.csv` contains at most 10 rows to bound disk use on the test host.

## 3. Algorithm Audit

- **Delete:** manual polling loops that busy-wait (use `time.sleep` inside the script)
- **Simplify:** single Python script handles both fetch and Prometheus exposition
- **Accelerate:** systemd oneshot with restart policy replaces a custom watchdog

## 4. Speed-of-Light Limit

Service reaches ACTIVE state within 5 seconds of `systemctl enable --now`; first
successful Prometheus scrape completes within 10 seconds.

## 5. Physics Guardrails

- BTC price feed API must be reachable from the host at install time.
- Port 8765 must not be in use before the service starts.
- Python 3.8+ must be present at `/usr/bin/python3`.

## 6. Steps

```yaml
- step: 1
  why: "Runtime and log directories must exist before the poller script is written."
  action: "mkdir -p /opt/btc-poller /tmp/btc-prices"
  verification: "test -d /opt/btc-poller && test -d /tmp/btc-prices"

- step: 2
  why: "The poller script must be in place before the systemd unit references it."
  action: "tee /opt/btc-poller/poller.py << 'EOF'\nimport os, time, socket, threading\nfrom http.server import HTTPServer, BaseHTTPRequestHandler\nimport urllib.request, json\n\nPORT = 8765\nLOG = '/tmp/btc-prices/log.csv'\nMAX_ROWS = 10\n\ndef fetch_price():\n    url = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd'\n    with urllib.request.urlopen(url, timeout=10) as r:\n        return json.load(r)['bitcoin']['usd']\n\nclass Handler(BaseHTTPRequestHandler):\n    def do_GET(self):\n        price = fetch_price()\n        rows = open(LOG).readlines() if os.path.exists(LOG) else []\n        rows.append(f'{time.time()},{price}\\n')\n        open(LOG, 'w').writelines(rows[-MAX_ROWS:])\n        body = f'# HELP btc_price_usd BTC price in USD\\n# TYPE btc_price_usd gauge\\nbtc_price_usd {price}\\n'.encode()\n        self.send_response(200)\n        self.send_header('Content-Type', 'text/plain; version=0.0.4')\n        self.end_headers()\n        self.wfile.write(body)\n    def log_message(self, *a): pass\n\nHTTPServer(('', PORT), Handler).serve_forever()\nEOF"
  verification: "test -f /opt/btc-poller/poller.py"

- step: 3
  why: "Smoke-test confirms the script binds the port and returns valid Prometheus text before installing the unit."
  action: "timeout 5 python3 /opt/btc-poller/poller.py & sleep 1 && curl -sf http://127.0.0.1:8765/metrics; kill %1"
  verification: "curl -sf http://127.0.0.1:8765/metrics | grep -q btc_price_usd"

- step: 4
  why: "A systemd unit is required for automatic restart on crash and reboot-survival."
  action: "tee /etc/systemd/system/btc-poller.service << 'EOF'\n[Unit]\nDescription=BTC Price Poller (Prometheus)\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nExecStart=/usr/bin/python3 /opt/btc-poller/poller.py\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=multi-user.target\nEOF"
  verification: "test -f /etc/systemd/system/btc-poller.service"

- step: 5
  why: "systemd must reload unit files from disk before enable/start can see the new unit."
  action: "systemctl daemon-reload"
  verification: "systemctl list-unit-files btc-poller.service | grep -q btc-poller"

- step: 6
  why: "Enabling the unit registers it for reboot-survival; --now starts it immediately."
  action: "systemctl enable --now btc-poller.service"
  verification: "systemctl is-active btc-poller.service"

- step: 7
  why: "Live metrics scrape confirms the running service exposes the gauge on port 8765."
  action: "sleep 3 && curl -sf http://127.0.0.1:8765/metrics > /tmp/btc-poller-live.out"
  verification: "grep -q btc_price_usd /tmp/btc-poller-live.out"
```

## 7. Success Criteria

- [ ] `python3 /opt/btc-poller/poller.py` binds port 8765 and serves Prometheus text.
- [ ] `systemctl is-active btc-poller.service` returns 0 after install.
- [ ] `curl -sf http://127.0.0.1:8765/metrics` returns a line starting with `btc_price_usd`.
- [ ] Service is still active after `systemctl reboot` (observed manually).
