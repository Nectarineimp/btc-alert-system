# btc-alert-system

A high-performance, asynchronous Bitcoin market microstructure daemon and terminal user interface (TUI). 

The system streams live tick feeds from major spot and perpetual derivatives exchanges, computes rolling order flow dynamics (CVD, Volume Profile, POC shifts, and Value Area acceptance) in-memory, and leverages `gemini-2.5-flash` with structured Pydantic schemas to synthesize market conviction and uncertainty before dispatching private operational alerts.

## System Architecture

[ Exchange WebSockets (Spot / Perp) ]
│ (Live Trade Ticks)
▼
[ Async Microstructure Engine ]
├── Rolling In-Memory Circular Buffers (CVD / Delta)
├── Real-Time Volume Profile & POC Tracking
└── Regime & Threshold Trigger Evaluator
│
├──► [ Rich Live Terminal UI (WSL / tmux) ]
│
▼ (On High Conviction / Regime Shift)
[ Gemini 2.5 Structured Synthesis Engine ]
│
▼
[ Private Alert Dispatcher (WhatsApp / Webhook) ]

## Core Features

- **Asynchronous Ingestion:** Non-blocking WebSocket ingestion of spot and perp order book trades using `asyncio` and `aiohttp`/`websockets`.
- **Microstructure Mathematics:** Continuous calculation of Spot vs. Perp Cumulative Volume Delta (CVD), Point of Control (POC) migrations, and Value Area High/Low (VAH/VAL) boundaries.
- **AI Narrative Synthesis:** Structured analytical briefing using the `google-genai` SDK with strict JSON schema validation to evaluate market uncertainty.
- **Terminal Workstation Dashboard:** Full Rich-based TUI built for persistent `tmux` execution in WSL/Linux environments.
- **Private-First Notifications:** Targeted notifications sent directly to a private WhatsApp gateway when directional conviction flips to high.

## Project Structure

```
btc-alert-system/
├── README.md
├── pyproject.toml
├── .env.example
├── btc_alert/
│   ├── __init__.py
│   ├── config.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   └── websocket_client.py
│   ├── analytics/
│   │   ├── __init__.py
│   │   ├── cvd.py
│   │   └── volume_profile.py
│   ├── reasoning/
│   │   ├── __init__.py
│   │   ├── schemas.py
│   │   └── gemini_engine.py
│   ├── ui/
│   │   ├── __init__.py
│   │   └── dashboard.py
│   ├── alerts/
│   │   ├── __init__.py
│   │   └── whatsapp.py
│   └── main.py
└── tests/
```

## Implementation Roadmap

* [ ] **Step 1:** Environment setup & dependency configuration (`pyproject.toml` / Poetry).
* [ ] **Step 2:** Async WebSocket stream ingestion (Binance/Coinbase feeds).
* [ ] **Step 3:** Rolling in-memory metrics engine (CVD & Volume Profile).
* [ ] **Step 4:** Gemini structured synthesis integration (`gemini-2.5-flash` + Pydantic).
* [ ] **Step 5:** Terminal UI (Rich dashboard layout).
* [ ] **Step 6:** WhatsApp alert dispatcher & daemon orchestrator.

## License

MIT
