'use client';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Snapshot } from '@/lib/types';

type Trade = {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  contract_value: number;
  base_quantity: number;
  entry_price: number;
  exit_price: number;
  gross_pnl: number;
  fees: number | null;
  net_pnl: number | null;
  entry_order_id: string;
  exit_order_id: string;
  closed_at: string;
  mode: string;
};
type Report = {
  trades: Trade[];
  closed_count: number;
  gross_pnl: number;
  fees: number | null;
  net_pnl: number | null;
  warnings: string[];
  scope: string;
  mode: string;
  as_of: string | null;
  account_connected: boolean;
  account_error: string | null;
};
const usd = (value: number | null, digits = 8, signed = false) =>
  value == null
    ? 'Unavailable'
    : `${signed && value >= 0 ? '+' : ''}${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value)}`;
const tone = (value: number | null) =>
  value == null ? 'muted' : value >= 0 ? 'positive' : 'negative';

export default function TradeResults({ data }: { data: Snapshot }) {
  const query = useQuery({
    queryKey: ['trade-results', data.mode, data.session_id],
    queryFn: () => api<Report>('/api/trade-results'),
    refetchInterval: 10000,
    retry: 1,
  });
  const result = query.data;
  return (
    <section className="panel closed-trades" aria-label="Closed trade results">
      <div className="panel-head">
        <div>
          <div className="eyebrow">
            REALIZED RESULTS · {data.mode === 'demo' ? 'SIMULATED' : 'DELTA TESTNET'}
          </div>
          <h2>Closed trade results</h2>
        </div>
        <span className="badge">{result?.closed_count ?? '—'} MATCHED CLOSES</span>
      </div>
      {query.isPending ? (
        <p className="table-note">Loading realized trade results…</p>
      ) : query.isError ? (
        <p role="alert" className="table-note negative">
          Could not load trade results. Retry on the next data refresh.
        </p>
      ) : result && result.closed_count > 0 ? (
        <>
          <div className="pnl-metrics">
            {[
              ['Gross trade P&L', result.gross_pnl, 'Before trading fees', 4],
              ['Trading fees', result.fees, 'Entry + exit paid commissions', 8],
              ['Net trade P&L', result.net_pnl, 'Gross P&L minus trading fees', 8],
            ].map(([label, value, caption, digits], i) => (
              <div className="metric" key={String(label)}>
                <div className="metric-label">{String(label)}</div>
                <div
                  data-testid={['gross-trade-pnl', 'trade-fees', 'net-trade-pnl'][i]}
                  className={'metric-value ' + (i === 1 ? 'muted' : tone(value as number | null))}
                >
                  {usd(value as number | null, Number(digits), i !== 1)}
                </div>
                <div className="metric-caption">{String(caption)}</div>
              </div>
            ))}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {[
                    'Instrument / side',
                    'Contracts / multiplier',
                    'Entry fill',
                    'Exit fill',
                    'Gross P&L',
                    'Fees',
                    'Net P&L',
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.trades.slice(0, 10).map((t) => (
                  <tr key={t.id}>
                    <td>
                      <strong>
                        {t.symbol} · {t.side}
                      </strong>
                      <small className="trade-reference">
                        {new Date(t.closed_at).toLocaleString()}
                        <br />
                        Orders {t.entry_order_id} → {t.exit_order_id}
                      </small>
                    </td>
                    <td>
                      {t.quantity} × {t.contract_value}
                      <small className="trade-reference">{t.base_quantity} underlying units</small>
                    </td>
                    <td>{usd(t.entry_price, 2)}</td>
                    <td>{usd(t.exit_price, 2)}</td>
                    <td className={tone(t.gross_pnl)}>{usd(t.gross_pnl, 4, true)}</td>
                    <td>{usd(t.fees)}</td>
                    <td className={tone(t.net_pnl)}>{usd(t.net_pnl, 8, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="table-note">
            Closed-position results stay here. Unrealized P&L covers open positions and returns to
            zero after closing. Net trade P&L includes paid order commissions; funding and transfers
            are excluded. Totals cover all matched AlgoLens closes in loaded history; table shows
            the latest 10.
          </p>
        </>
      ) : (
        <p className="table-note">
          No matched closed strategy trades are available yet. Open positions are tracked under
          Unrealized P&L.
        </p>
      )}
      {result?.warnings.map((w) => (
        <p className="table-note negative" key={w}>
          {w}
        </p>
      ))}
      {data.mode === 'testnet' && result && !result.account_connected && (
        <p className="table-note negative">
          Account refresh unavailable. Displaying available saved order records.
        </p>
      )}
      {result?.as_of && (
        <p className="table-note">
          Last source update: {new Date(result.as_of).toLocaleString()} · Amounts in USD.
        </p>
      )}
    </section>
  );
}
