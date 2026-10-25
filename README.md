# AlgoLens

An explainable algorithmic trading terminal: **market data → EMA analysis → signal → risk checks → execution → positions → audit history**.

## Delivered behavior

- Eight responsive screens: Overview, Live Trading, Strategy Control, Positions, Order History, Risk Management, Execution Logs, and Settings.
- Backend-driven deterministic Demo Mode, including an accelerated candle replay, EMA 20/50 crossovers, server-enforced risk limits, simulated order lifecycle, protected positions, and SQLite audit history.
- Trade Decision Inspector with signal-time values, previous/current EMA relationships, deterministic explanations, individual risk checks, and related orders.
- Candlestick/volume charts, indicator overlays, execution markers, entry/SL/TP lines, exposure analytics, filtered server-paginated orders, and structured event drawers.
- WebSocket reconnection with deduplicated, serialized REST snapshot recovery; stale data is visibly labeled.
- India Testnet candle monitoring, EMA observations, protected automated execution, authenticated account imports, and start-preflight diagnostics.

**India Testnet automated execution is implemented following explicit user authorization.** Start requires saved risk limits and passing server preflight checks. No genuine exchange fill has yet been verified here: BTC's minimum contract currently exceeds the configured exposure allowance. Demo IDs begin with `demo_`; Testnet IDs come from Delta. Global and production execution are disabled.

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
| `ALGOLENS_MODE` | `demo` | `demo` or `testnet`; restart required |
| `ALGOLENS_DB` | `algolens-{mode}.db` | Optional SQLite path; cannot reuse a database across modes |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Comma-separated allowed frontend origins |
| `DELTA_TESTNET_URL` | empty | Explicit regional Testnet URL |
| `DELTA_API_KEY` | empty | Backend-only API key |
| `DELTA_API_SECRET` | empty | Backend-only secret |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Frontend API address; no credentials |
| `PLAYWRIGHT_CHANNEL` | `chrome` | Installed browser for end-to-end tests; `msedge` also works |

No credentials are required for Demo Mode. Do not commit `.env` or enter exchange secrets in the browser.

### Testnet setup

The [official India documentation](https://docs.delta.exchange/) identifies `https://cdn-ind.testnet.deltaex.org` as the India Testnet host. The [official Delta Python client](https://github.com/delta-exchange/python-rest-client) uses `https://testnet-api.delta.exchange` for Global Testnet. Verify your account region and current documentation before configuring credentials. Production hosts are rejected by the adapter.

Set mode and host in `.env`, restart FastAPI, and use **Settings → Test connection**. Public candles can load without credentials; private wallet, position, active-order and recent order-history reads require authentication. Market connectivity and account authentication have separate indicators. The backend imports available USD wallet metrics, positions and orders without inventing missing P&L values. Authentication errors such as a rejected IP whitelist are shown in the frontend. The history import contains active orders plus the latest 50 exchange history records; it is not a complete exchange ledger.

When stopped, Testnet mode publishes HOLD/BUY/SELL observations without requesting orders. Start enables execution after server preflight passes. Only new completed candles after Start can trigger trades. The engine sets and verifies 1x order leverage, persists a client order ID before submitting, reconciles the actual fill, and places separate native reduce-only stop-market SL/TP orders for filled quantity. This product does not advertise combined bracket orders. Protection failure triggers ERROR and a failsafe reduce-only close. Native exits remain hosted at Delta after Stop; the backend must run to cancel sibling exits and reconcile outcomes.

Preflight checks authentication, saved limits, contract sizing, fresh candles, exposure including a 2% notional buffer, full-notional collateral, daily loss, concurrent positions, outstanding orders, and unresolved submissions. A successful connection test never starts trading. Partial fills are protected only for their filled quantity; any remaining entry quantity must reach a confirmed terminal state first.

Daily Testnet loss conservatively sums negative USD trading-ledger debits (cashflow, commissions, funding, settlement and liquidation fees) for the UTC day. Profits do not replenish it. Session net realized cashflow sums trading entries since Start and excludes deposits/transfers. Ledger pagination must complete before entries are allowed. Unsupported or missing financial values remain unavailable.

The execution path is tested against a fake exchange, including timeout lookup without POST retry, partial fills, protection failure, opposite-signal exits, and restart reconciliation. Genuine entry/fill/protection behavior still needs a supervised Testnet run within approved limits. A $100 account with 20% maximum exposure allows $20 notional; a roughly $80 BTC contract plus buffer requires roughly $408 equity at that limit. The application never raises limits automatically.

### Start genuine India Testnet automation

1. Verify Settings connection status after loading local credentials.
2. Save chosen risk limits in Risk Management.
3. Select a supported USD linear perpetual and quantity in Strategy Control. Contract multipliers appear in the instrument selector.
4. Resolve failing preflight checks by adding Testnet funds, choosing a smaller-notional instrument, or deliberately choosing different limits.
5. Click Start strategy. HOLD is normal; there is no forced trade on startup.
6. Inspect actual exchange IDs, fills and native protection acknowledgments. Stop leaves positions open; emergency stop also cancels eligible pending entries.

Unresolved persisted submissions block new entries. Restart leaves automation stopped while owned positions/orders reconcile. An owned position whose protection cannot be established may be failsafe-closed. Use one worker and one operator; do not combine this with other automation on the same account.

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

Tests cover EMA parity, crossovers, risk policy, SQLite state, stop/restart behavior, exact signed request bodies, native protection, partial fills, ambiguous submissions, failsafe closing, and opposite-signal exits against a fake exchange. Genuine Testnet fills have not yet been verified.

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

For a presentation script, mathematical explanation, risk examples and honest capability boundaries, see [the judges' strategy guide](JUDGES_STRATEGY_GUIDE.md).

## Attribution

Financial charting uses [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/). Its attribution logo is retained in the chart. Other dependencies retain their respective licenses.
