# AlgoLens — Hackathon Development Plan

## Goal

Build a frontend-first trading terminal that explains the complete lifecycle:

**Market data → EMA analysis → Signal → Risk validation → Execution → Position monitoring → Explainable history**

Target one operator, one configured instrument, one EMA strategy, and all eight screens. Prioritize a reliable demonstration over additional strategies or multi-account features.

## Architecture

- Next.js App Router, strict TypeScript, Tailwind, shadcn-style Radix components, Lucide, Lightweight Charts, Recharts, React Hook Form, and Zod.
- TanStack Query owns backend snapshots and historical lists. Zustand owns connection and interface state.
- FastAPI runs one background strategy worker. SQLite persists configuration, decisions, order intents, exchange identifiers, and audit events.
- Generate API types from FastAPI OpenAPI. Recover server state through REST after WebSocket reconnects.
- Configure Demo or Testnet at startup, with separate databases and visible mode labels. Never mix simulated fills with exchange positions.
- Backend-only credentials, restricted origins, local mutation controls, and redacted logs.

## Trading rules

- Default EMA 20/50 on completed 1-minute candles; support 1m, 5m, and 15m strategy configuration.
- Seed each EMA using its first period's simple average. Require slow period + 1 candles.
- BUY when fast moves from at/below slow to above it; SELL uses the reverse comparison.
- Open only when flat. An opposite crossover closes the position using a reduce-only order; it does not immediately reverse.
- Persist a unique completed-candle intent before execution. Do not retry ambiguous exchange submissions without reconciliation.
- Validate quantity, contract sizing, exposure, margin, daily loss, duplicate intent, and protection on the backend.
- Require explicitly saved risk limits before starting. Daily loss uses the UTC day; session realized P&L starts when the strategy starts.
- Graceful stop prevents new entries while monitoring/protection continue. Emergency stop also cancels eligible entry orders, preserving protective exits. Neither implies positions are closed.

## Delivery phases

| Phase | Deliverables | Acceptance |
| --- | --- | --- |
| 1. Foundation | Frontend/backend structure, theme, responsive navigation, typed contracts | Both applications run locally; eight routes render |
| 2. Demo frontend | Overview, trading, strategy, positions, orders, risk, logs, settings | Clearly labeled deterministic lifecycle |
| 3. Visualization | Candles, EMAs, markers, protection lines, exposure chart, Inspector | Judges can trace every decision |
| 4. Backend integration | REST, SQLite, risk enforcement, worker, WebSocket recovery | UI operates against backend state |
| 5. Delta integration | Confirm region, verify official contracts, authenticated data adapter | Read-only connectivity first; protected execution after verification |
| 6. Demo readiness | Automated tests, responsive checks, docs, presentation script | Rehearsed demo and honest fallback |

## Application APIs

Account: `GET /api/account`, `/api/account/balance`.

Market: `GET /api/markets`, `/api/market/candles`, `/api/market/ticker`.

Strategy: `GET /api/strategy/status`, `GET/PUT /api/strategy/config`, `POST /api/strategy/start`, `/stop`, `/emergency-stop`.

Trading: `GET /api/positions`, `/api/orders`, `/api/orders/{id}`.

Risk: `GET /api/risk/status`, `GET/PUT /api/risk/config`, `GET /api/risk/rejections`.

Audit/operations: `GET /api/events`, `/api/decisions/{id}`, `/api/snapshot`, `/api/health`, `/api/ready`; `POST /api/connection/test`; WebSocket `/ws/trading`.

Event envelopes contain ID, increasing sequence, UTC timestamp, type, severity, mode, correlation ID, and structured payload. The Inspector exposes real indicator inputs, deterministic explanations, individual risk results, and related order outcomes.

## Verification

- EMA seed, warm-up, both crossovers, no signal, and duplicate intent prevention.
- Invalid parameters, quantity/exposure/margin/loss failures, and unconfirmed risk configuration.
- Duplicate starts, safe stops, positions retained after stop, restart reconciliation, and mode isolation.
- Submission/acknowledgment/fill separation, exchange rejection, partial fills, and ambiguous timeouts before enabling Testnet execution.
- WebSocket reconnect and snapshot recovery; loading, unavailable, empty, error, and stale states.
- All routes, responsive layout, secret handling, and production build.

## Current delivery decision

The user initially chose read-only mode, then explicitly authorized genuine India Testnet automated orders. The code implements risk preflight, 1x leverage, native reduce-only exits, persisted client-ID recovery, partial-fill handling and wallet-ledger accounting. A genuine BTCUSD entry and opposite-signal close are now reconciled, including protective-order acknowledgments and cancellations. Overview/Order History show gross P&L, actual commissions and net P&L for matched closed trades. Native stop-trigger and exceptional recovery behaviors are not all exchange-verified. A packaged replay remains deferred. Global and production execution remain disabled.

Reference documentation: [Delta India API](https://docs.delta.exchange/), [Delta Global API](https://docs-global.delta.exchange/).
