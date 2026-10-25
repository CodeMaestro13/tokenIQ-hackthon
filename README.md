# AlgoLens

An explainable algorithmic trading terminal: **market data → EMA analysis → signal → risk checks → execution → positions → audit history**.

## Delivered behavior

- Eight responsive screens: Overview, Live Trading, Strategy Control, Positions, Order History, Risk Management, Execution Logs, and Settings.
- Backend-driven deterministic Demo Mode, including an accelerated candle replay, EMA 20/50 crossovers, server-enforced risk limits, simulated order lifecycle, protected positions, and SQLite audit history.
- Trade Decision Inspector with signal-time values, previous/current EMA relationships, deterministic explanations, individual risk checks, and related orders.
- Candlestick/volume charts, indicator overlays, execution markers, entry/SL/TP lines, exposure analytics, filtered server-paginated orders, and structured event drawers.
- WebSocket reconnection with deduplicated, serialized REST snapshot recovery; stale data is visibly labeled.
- Read-only Delta Testnet market adapter and authenticated connection test.

**Testnet execution is disabled by explicit user choice.** No exchange order submission is implemented or claimed. Demo order IDs begin with `demo_`. No authentic exchange-event replay is bundled because no authenticated Testnet session has been captured.

## Local setup (Windows PowerShell)

Requirements: Python 3.11+ and Node.js 22+ (Node 24 recommended).

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --env-file .env
```

In a second terminal:

```powershell
cd frontend
npm.cmd ci
Copy-Item .env.example .env.local
npm.cmd run dev
```

Open **http://localhost:3000**. The backend API explorer is **http://127.0.0.1:8000/docs**.

For a production frontend build, run `npm.cmd run build`, then `npm.cmd start`. Both services bind locally. Run exactly one backend process; multiple workers would create duplicate strategy engines.

On macOS/Linux, use `.venv/bin/python` and `npm` instead of the Windows executable paths.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALGOLENS_MODE` | `demo` | `demo` or read-only `testnet`; restart required |
| `ALGOLENS_DB` | `algolens-{mode}.db` | Optional SQLite path; cannot reuse a database across modes |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Comma-separated allowed frontend origins |
| `DELTA_TESTNET_URL` | empty | Explicit regional Testnet URL |
| `DELTA_API_KEY` | empty | Backend-only API key |
| `DELTA_API_SECRET` | empty | Backend-only secret |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Frontend API address; no credentials |
| `PLAYWRIGHT_CHANNEL` | `chrome` | Installed browser for end-to-end tests; `msedge` also works |

No credentials are required for Demo Mode. Do not commit `.env` or enter exchange secrets in the browser.

### Read-only Testnet setup

The [official India documentation](https://docs.delta.exchange/) identifies `https://cdn-ind.testnet.deltaex.org` as the India Testnet host. The [official Delta Python client](https://github.com/delta-exchange/python-rest-client) uses `https://testnet-api.delta.exchange` for Global Testnet. Verify your account region and current documentation before configuring credentials. Production hosts are rejected by the adapter.

Set mode and host in `.env`, restart FastAPI, and use **Settings → Test connection**. Public candles can load without credentials; the connection test additionally verifies authenticated wallet access. The UI keeps account/position trading metrics unavailable because execution and full account normalization are not enabled. A successful connection test does not enable trading.

Before a later Testnet trading release, implement and verify contract sizing/ticks, exchange-native protective orders, actual account/position reconciliation, partially filled orders, persisted client-order IDs with timeout lookup, daily realized loss including account fills, and restart recovery. No flag currently bypasses this gate.

## Architecture

`frontend/` contains the Next.js App Router application. Shared UI is built from Tailwind/CSS tokens and Radix primitives with a shadcn-compatible component configuration. Fonts are bundled locally. Lightweight Charts handles OHLC/volume/EMAs; Recharts handles the market sparkline.

TanStack Query is the owner of backend snapshots and paginated historical orders. Zustand holds connection/interface state and persisted display preferences. Socket events trigger serialized snapshot refreshes; events received during a refresh cause a subsequent refresh, preventing dropped state. Backend sequence numbers deduplicate old events. A periodic REST refresh provides recovery if WebSocket transport is interrupted.

`backend/` separates Pydantic contracts, SMA-seeded EMA calculations, risk checks, SQLite storage, exchange reads, and the single strategy engine. FastAPI owns the worker lifecycle and exposes REST/WebSocket interfaces. All trading decisions occur on the server.

SQLite persists configuration, completed decisions, unique candle intents, orders, the demo position, cumulative demo P&L, daily losses, recent candle state, and structured events. A restart restores state but leaves the strategy stopped. Demo protection resumes when the backend runs; protection is **simulated**, not an exchange-native order.

### Strategy and accounting

- Default: BTCUSD, 1-minute candles, EMA 20/50, 1 contract.
- The demo contract multiplier is explicitly 0.001 BTC per contract. It is not used to size Testnet orders.
- A crossover is evaluated only after `slow_period + 1` completed candles. EMA seed is the first period's average close.
- BUY: previous fast ≤ slow and current fast > slow. SELL: previous fast ≥ slow and current fast < slow.
- One position at a time. Opposite signals close reduce-only; a later crossover can create another entry.
- Risk limits must be saved before starting. Entries check quantity, fully collateralized available margin, exposure percentage, daily realized loss, duplicate intent, and SL/TP policy.
- Daily realized loss accumulates losing closes within the UTC day; gains do not reset consumed loss allowance.
- Session realized P&L resets on a new strategy start. Account equity includes cumulative simulated realized and unrealized P&L.
- Demo uses an accelerated replay clock: every two wall-clock seconds adds one completed configured-timeframe candle. Candle timestamps may advance beyond wall-clock time and are always labeled simulated.
- SL/TP uses candle high/low; if both are touched, stop loss takes precedence. Demo accounting excludes fees, funding, liquidation, latency, and slippage. It is an educational walkthrough, not a performance backtest.

Graceful stop and emergency stop disable automation while leaving positions monitored. There are no pending Demo entry orders because simulated fills are synchronous. SL/TP monitoring continues only while the backend is running. Manual close is deliberately not offered.

## API contract

The authoritative interactive contract is `/docs`; raw schema is `/openapi.json`. With FastAPI running, regenerate frontend contracts with:

```powershell
cd frontend
npm.cmd run generate:api
```

Generated strategy/risk contracts are consumed by the frontend. UI snapshot/trading interfaces live in `frontend/lib/types.ts`.

| Group | Endpoints |
| --- | --- |
| State | `GET /api/snapshot`, `/api/health`, `/api/ready` |
| Account | `GET /api/account`, `/api/account/balance` |
| Market | `GET /api/markets`, `/api/market/candles`, `/api/market/ticker` |
| Strategy | `GET /api/strategy/status`, `GET/PUT /api/strategy/config`, `POST /api/strategy/start`, `/stop`, `/emergency-stop` |
| Trading | `GET /api/positions`, `/api/orders`, `/api/orders/{id}` |
| Risk | `GET /api/risk/status`, `GET/PUT /api/risk/config`, `GET /api/risk/rejections` |
| Audit | `GET /api/events`, `/api/decisions/{id}` |
| Connection | `POST /api/connection/test`, `WS /ws/trading` |

Orders support page/page_size, symbol, side, status, start, and end query parameters. Events support sequence cursor, severity, and type filters. Each event includes ID, sequence, UTC timestamp, mode, severity, correlation ID, and structured payload. Validation/action errors return `{code, message, correlation_id}`.

`/api/snapshot` includes mode, freshness timestamp, sequence, strategy/risk configuration, account, recent candles, orders, decisions, positions, and recent events. No HTTP response implies an order was filled unless its actual order state says so.

## Verification

```powershell
# From repository root
.\.venv\Scripts\python.exe -m pytest backend/tests -q

# From frontend
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd audit

# With both services running and Google Chrome installed
npm.cmd run test:e2e
```

The end-to-end tests use an installed browser, avoiding an additional browser download. For Edge, set `$env:PLAYWRIGHT_CHANNEL='msedge'`.

Tests cover EMA parity, warm-up, crossovers, invalid configuration, risk rejection, persisted audit data, restart/stop semantics, mode isolation, API controls, WebSocket connection, route rendering, and mobile overflow. Exchange execution scenarios are deferred with Testnet execution.

## Hackathon demonstration

1. Open Overview and point out the **SIMULATED DATA — DEMO MODE** label.
2. Open Risk Management, review limits, and save them to confirm.
3. Open Strategy Control and explain completed-candle EMA 20/50 crossovers.
4. Start the strategy. Allow approximately 1–90 seconds for the next deterministic crossover.
5. Show Execution Logs: signal, risk evaluation, submitted order, acknowledgment, fill, and position update.
6. Open Overview → Inspect decision to explain exact EMA inputs, risk checks, and the resulting simulated order.
7. Show positions, SL/TP chart lines, and backend-derived P&L.
8. Stop the strategy and explain that open positions remain monitored.
9. Optionally lower a risk limit and demonstrate a rejected decision on a later crossover.

See [the implementation plan](ALGOLENS_IMPLEMENTATION_PLAN.md) for phases and deferred Testnet acceptance criteria.

## Attribution

Financial charting uses [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/). Its attribution logo is retained in the chart. Other dependencies retain their respective licenses.
