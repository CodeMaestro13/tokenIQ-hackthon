# AlgoLens — Strategy and Judge Demonstration Guide

## What we can honestly demonstrate

AlgoLens uses a deterministic **EMA 20/50 Crossover** strategy. It is a rule-based trend-following system, not an AI predictor.

| Capability | Demo Mode | India Testnet Mode |
| --- | --- | --- |
| Market data | Clearly labeled deterministic simulation | Genuine completed candles, polled every 10 seconds |
| EMA calculation and crossover detection | Active while Demo bot runs | Automatic read-only observation of latest completed candles |
| Start / stop automation | Functional simulated trading | Implemented for India Testnet; requires passing preflight and explicit Start |
| Risk checks and fills | Server-enforced checks and simulated fills | Genuine execution after Start; stopped observations never request orders |
| Balances / positions / orders | Simulated account and audit history | Read-only imports when exchange authentication succeeds |
| Explanation | Actual strategy inputs and simulated execution results | Actual candle/EMA inputs, explicitly labeled observed signals |

Updated credentials now authenticate successfully. At verification the account had $100 equity and available margin. BTC preflight is blocked by unsaved risk limits and a roughly $82 minimum contract including a price buffer, exceeding the default $20 exposure allowance. Limits have not been raised automatically. A public chart alone does not prove private authentication.

No genuine AlgoLens Testnet trade has been executed or verified. Previously placed exchange orders, if imported, are explicitly identified as imported orders rather than AlgoLens executions.

## A 90-second presentation script

> AlgoLens makes algorithmic trading decisions inspectable. Our current strategy is an EMA 20/50 crossover on completed one-minute candles. The fast EMA reacts more quickly to recent prices; the slow EMA represents a slower-moving baseline.
>
> We generate a BUY only when the fast EMA changes from at or below the slow EMA to above it. SELL uses the opposite crossing. Simply staying above the slow EMA does not generate another BUY on every candle.
>
> A signal is only a potential trade. In Demo Mode, the backend checks position size, account exposure, available margin, daily realized loss, duplicate prevention, and stop-loss policy before allowing a simulated entry. We allow one position at a time. An opposite crossover closes the current position without immediately reversing it.
>
> The Decision Inspector shows the exact previous and current EMA values, candle timestamp, risk results, and order outcome. All explanations come from those recorded values and fixed rules. We do not invent a confidence score or claim profitability.
>
> India Testnet Mode observes real exchange candles. Passing preflight and clicking Start enables genuine automated orders on new crossovers. Our current account configuration does not pass the exposure gate yet, so separately labeled Demo Mode demonstrates the fill lifecycle until that is resolved. Stopping automation does not imply that a position is closed.

## How EMA works

For a period `N`, first seed the EMA with the simple average of its first `N` closing prices. Then update it for each completed candle:

```text
alpha = 2 / (N + 1)
EMA_now = alpha × close_now + (1 - alpha) × EMA_previous
```

For EMA 20, alpha is approximately `0.09524`. For EMA 50, alpha is approximately `0.03922`. The larger weight on the latest close makes EMA 20 react faster. These periods count candles: with one-minute candles, the indicators use 20- and 50-candle periods, with exponentially decaying influence from earlier closes.

The implementation requires at least **51 completed candles** for the default strategy so that both the previous and current EMA relationships can be compared. Insufficient history produces a warming-up state.

## Exact signal rules

```text
BUY:
  previous_fast <= previous_slow
  AND current_fast > current_slow

SELL:
  previous_fast >= previous_slow
  AND current_fast < current_slow

Otherwise: HOLD (no crossover)
```

Illustrative BUY example (educational values, not an exchange fill):

| Value | Previous completed candle | Current completed candle |
| --- | --- | --- |
| EMA 20 | 67,300 | 67,340 |
| EMA 50 | 67,310 | 67,325 |
| Relationship | Fast below slow | Fast above slow |

This generates a BUY because the relationship changed across two completed candles. Equal values followed by a strict move above also qualify. The current unfinished candle never triggers a decision.

## From signal to position

1. Receive completed candles and calculate EMAs on the backend.
2. Compare previous and current EMA relationships.
3. Record the signal and a unique candle intent to prevent duplicate action.
4. In Demo trading, evaluate risk and reject an entry if any required check fails.
5. Record separate simulated SUBMITTED, ACKNOWLEDGED, and FILLED events.
6. Open a simulated position with configured SL/TP levels.
7. Monitor P&L and protective thresholds; preserve an audit trail linked by correlation ID.

If flat, BUY opens a simulated long and SELL opens a simulated short. If holding the opposite side, the signal closes that position reduce-only. It does not open the reverse position in the same decision. Existing same-side exposure is retained rather than increased.

While Testnet automation is stopped, crossovers are **OBSERVED**, entry checks are **NOT EVALUATED**, and no order is requested. After Start, new crossovers pass actual backend risk checks before an exchange entry. The signal monitor can therefore be active while automation remains STOPPED.

## Risk and P&L example

The Demo contract multiplier is explicitly **0.001 BTC per contract**. This value is not used to size genuine Testnet orders.

For one contract at an illustrative entry of `$67,420`:

- Notional exposure: `1 × 0.001 × 67,420 = $67.42`.
- With `$10,000` equity, this is `0.6742%` exposure.
- A configured 20% exposure limit allows up to `$2,000` of notional exposure; a different quantity may be rejected.
- The Demo margin check conservatively requires full notional collateral rather than assuming leverage.
- For a long, 1% SL is `$66,745.80`; 2% TP is `$68,768.40`.
- For a long, P&L is `(mark - entry) × quantity × 0.001`. For a short, reverse the price difference.

Daily realized loss accumulates losing closes within the UTC day. Profits do not replenish that allowance. Session realized P&L resets on a new Demo strategy start. Risk limits must be explicitly saved before the Demo bot starts.

## Stopping and protection

- Stop disables new strategy decisions. Existing Demo positions remain monitored while the backend runs.
- Emergency stop also represents cancellation of eligible pending entries. Demo fills are synchronous, so there are no pending Demo entry orders to cancel.
- Demo SL/TP is simulated by the backend, not exchange-native protection. If both SL and TP are touched in one candle, the stop loss takes precedence.
- Turning off the backend also turns off simulated protective monitoring. It must not be described as an exchange-hosted stop order.
- Imported exchange positions show protection as NOT VERIFIED; configured policy alone is not proof of an actual exchange protective order.

## Why the interface may show unavailable values

Genuine execution uses verified 1x order leverage and separate native reduce-only stop-market SL/TP orders for actual filled contracts. These are not an atomic OCO bracket. The running backend cancels and verifies cancellation of the sibling exit after the position closes, before allowing a new entry. A protection failure requests a failsafe close and requires an explicit restart. Unknown submissions are looked up by persisted client ID; the POST is never repeated.

- **Equity / margin unavailable:** private API access was rejected, a USD wallet was not returned, or the required field is missing.
- **Session realized P&L unavailable before Start:** no active session exists. Testnet daily loss comes from complete USD trading-ledger reconciliation and includes negative fees/funding. Failure to reconcile blocks entries.
- **No signal:** no completed-candle crossover occurred. A trend remaining above/below the slow EMA is not a new signal.
- **No orders / positions:** no verified imported records, or authenticated access is unavailable. Demo fills are never mixed into Testnet Mode.
- **Start blocked in Testnet:** inspect preflight for authentication, risk confirmation, exposure, margin, fresh data, existing orders/positions and unresolved submissions.

## Suggested demonstration

1. In Testnet Mode, show genuine candle data, EMA values, and read-only monitoring.
2. Show the account-authentication status independently from market connectivity.
3. Explain HOLD or open an observed crossover in the Inspector, if one has occurred.
4. For execution, restart the backend with `ALGOLENS_MODE=demo` in the local `.env`. Keep the simulation banner visible.
5. Save risk limits, start the Demo strategy, and wait for a deterministic crossover.
6. Open the Inspector to trace input values, risk checks, order states, and the resulting position.
7. Stop the strategy and show that a position may remain open.
8. Restore `ALGOLENS_MODE=testnet` and restart when finished.

## Likely judge questions

**Why EMA 20 and 50?** They provide a simple, explainable fast/slow trend comparison. They are demonstration defaults, not parameters proven optimal for this market.

**Why completed candles?** It prevents acting on a crossover that appears during a candle and disappears before the close. This does not eliminate false signals.

**What is the differentiator?** Traceability: the user can see the exact mathematical inputs, decision, risk outcome, and execution history for each trade or rejected trade.

**Does it guarantee profit?** No. EMA signals lag price and can whipsaw in sideways markets. Real execution introduces fees, funding, slippage, latency and liquidation risk that the educational simulator does not model.

**Is automated Delta execution verified?** The implementation and fake-exchange tests cover supported India Testnet linear perpetuals. Real authentication is verified. A genuine entry/fill/protection lifecycle has not yet been verified because the current account/risk configuration blocks entry. Do not present mock tests as exchange fills.

**What was tested?** EMA seeding and warm-up, both crossing directions, no-signal behavior, invalid inputs, risk rejection, Demo fills, stop/restart behavior, data isolation, read-only monitoring without order creation, private-data normalization, and explicit authentication failures. These tests establish implementation behavior, not strategy profitability.
