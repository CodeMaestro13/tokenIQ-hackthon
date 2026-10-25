'use client';
import { useState } from 'react';
import Link from 'next/link';
import { QueryClient, QueryClientProvider, useQueryClient, useQuery } from '@tanstack/react-query';
import * as Dialog from '@radix-ui/react-dialog';
import { AreaChart, Area, ResponsiveContainer, Tooltip } from 'recharts';
import {
  Activity,
  ArrowDownLeft,
  ArrowUpRight,
  BarChart3,
  Bell,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock,
  Code2,
  ExternalLink,
  Eye,
  History,
  LayoutDashboard,
  Menu,
  Play,
  Radio,
  Settings,
  Shield,
  Square,
  TerminalSquare,
  TrendingUp,
  Wallet,
  X,
  Zap,
} from 'lucide-react';
import { useTerminal } from '@/lib/use-terminal';
import { api } from '@/lib/api';
import { useUI, usePreferences } from '@/lib/store';
import type { Snapshot, Order, TradingEvent, Decision } from '@/lib/types';
import MarketChart from './chart';
import { Button } from './ui/button';
import { StrategyForm, RiskForm } from './forms';

const navigation = [
  ['dashboard', 'Overview', LayoutDashboard],
  ['trading', 'Live Trading', Activity],
  ['strategy', 'Strategy Control', Zap],
  ['positions', 'Positions', Wallet],
  ['orders', 'Order History', History],
  ['risk', 'Risk Management', Shield],
  ['logs', 'Execution Logs', TerminalSquare],
  ['settings', 'Settings', Settings],
] as const;
const money = (n: number | undefined | null) =>
  n == null
    ? 'Unavailable'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: usePreferences.getState().precision,
        maximumFractionDigits: usePreferences.getState().precision,
      }).format(n);
const stamp = (s: string | undefined | null) =>
  s ? new Date(s).toLocaleTimeString([], { hour12: false }) : '—';
const signed = (n: number | undefined) =>
  n == null ? 'Unavailable' : `${n >= 0 ? '+' : ''}${money(n)}`;
function Badge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: string }) {
  return <span className={'badge ' + tone}>{children}</span>;
}
function Panel({
  title,
  eyebrow,
  children,
  action,
  className = '',
}: {
  title: string;
  eyebrow?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={'panel ' + className}>
      <div className="panel-head">
        <div>
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          <h2>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
function Empty({ text = 'No activity yet' }: { text?: string }) {
  return (
    <div className="empty">
      <Activity size={24} />
      <strong>{text}</strong>
      <span>Updates appear here as the trading lifecycle progresses.</span>
    </div>
  );
}
export default function Terminal({ screen }: { screen: string }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1000,
            refetchOnWindowFocus: false,
            structuralSharing: (previous, next) => {
              const a = previous as Partial<Snapshot> | undefined,
                b = next as Partial<Snapshot>;
              return a?.sequence !== undefined &&
                b?.sequence !== undefined &&
                a.sequence > b.sequence
                ? a
                : next;
            },
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Workspace screen={screen} />
    </QueryClientProvider>
  );
}

function Workspace({ screen }: { screen: string }) {
  const query = useTerminal(),
    client = useQueryClient(),
    data = query.data;
  const precision = usePreferences((s) => s.precision),
    notifications = usePreferences((s) => s.notifications);
  const connection = useUI((s) => s.connection),
    collapsed = useUI((s) => s.collapsed),
    toggle = useUI((s) => s.toggle),
    inspect = useUI((s) => s.inspect),
    selected = useUI((s) => s.selectedDecision);
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(''),
    [mobile, setMobile] = useState(false),
    [event, setEvent] = useState<TradingEvent | null>(null),
    [detail, setDetail] = useState<unknown>(null),
    [logFilter, setLogFilter] = useState('ALL');
  const [logSeverity, setLogSeverity] = useState('ALL');
  const title = navigation.find((n) => n[0] === screen)?.[1] || 'Overview';
  async function action(path: string, method = 'POST', body?: unknown) {
    if (busy) return;
    setBusy(true);
    try {
      const result = await api<{ message?: string }>(path, method, body);
      if (notifications || result?.message)
        setNotice(result?.message || 'Action confirmed by backend');
      await client.invalidateQueries({ queryKey: ['snapshot'] });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }
  const stale =
    !data?.last_update ||
    Date.now() - Date.parse(data.last_update) > 30000 ||
    connection !== 'Connected';
  const latest = data?.decisions[0];
  const persistedDecision = useQuery({
    queryKey: ['decision', selected],
    queryFn: () => api<Decision>('/api/decisions/' + selected),
    enabled: !!selected,
    retry: false,
  });
  const decision = data?.decisions.find((d) => d.id === selected) || persistedDecision.data;
  const price = data?.candles.at(-1)?.close;
  const previous = data?.candles.at(-2)?.close;
  const change = price && previous ? ((price - previous) / previous) * 100 : 0;
  const controls = data && (
    <div className="controls">
      <Button
        disabled={busy || data.status === 'RUNNING' || !data.execution_enabled}
        onClick={() => void action('/api/strategy/start')}
      >
        <Play size={14} />
        {busy ? 'Processing…' : 'Start strategy'}
      </Button>
      <Button
        variant="outline"
        disabled={busy || data.status === 'STOPPED'}
        onClick={() => void action('/api/strategy/stop')}
      >
        <Square size={13} />
        Stop
      </Button>
    </div>
  );
  const chart = data && (
    <Panel
      title={`${data.config.symbol} / USD`}
      eyebrow="MARKET OVERVIEW"
      action={
        <div className="chart-legend">
          <span className="cyan">● EMA {data.config.fast_period}</span>
          <span className="purple">● EMA {data.config.slow_period}</span>
          <Badge>{data.config.timeframe}</Badge>
        </div>
      }
    >
      <div className="chart-price">
        {money(price)}
        <span className={change >= 0 ? 'positive' : 'negative'}>
          {change >= 0 ? '+' : ''}
          {change.toFixed(2)}% <small>last candle</small>
        </span>
      </div>
      {data.warming_up && (
        <p className="callout">Warming up: waiting for enough completed candles.</p>
      )}
      <MarketChart data={data} />
      <div className="chart-foot">
        <span>
          ● {data.mode === 'demo' ? 'Accelerated simulated candles' : 'Testnet completed candles'}
        </span>
        <Link href="/trading">
          Expand terminal <ExternalLink size={12} />
        </Link>
      </div>
    </Panel>
  );
  const strategy = data && (
    <Panel
      title="EMA Crossover"
      eyebrow="ACTIVE STRATEGY"
      action={
        <span className="icon-tile">
          <Zap size={18} />
        </span>
      }
    >
      <div className="strategy-description">
        A systematic approach.
        <br />
        Every decision explained.
      </div>
      <div className="status-row">
        <span>Strategy status</span>
        <Badge tone={data.status === 'RUNNING' ? 'green' : 'neutral'}>● {data.status}</Badge>
      </div>
      <div className="parameter-grid">
        <div>
          <span>Fast EMA</span>
          <strong>
            {data.config.fast_period} <small>periods</small>
          </strong>
        </div>
        <div>
          <span>Slow EMA</span>
          <strong>
            {data.config.slow_period} <small>periods</small>
          </strong>
        </div>
        <div>
          <span>Timeframe</span>
          <strong>{data.config.timeframe}</strong>
        </div>
        <div>
          <span>Position size</span>
          <strong>
            {data.config.quantity} <small>contracts</small>
          </strong>
        </div>
      </div>
      <div className="protection">
        <Shield size={15} />
        <span>
          SL {data.config.stop_loss_pct}% <span className="muted"> / </span> TP{' '}
          {data.config.take_profit_pct}%
        </span>
        <Badge tone="green">Protected</Badge>
      </div>
      {controls}
      <Link href="/strategy" className="text-link">
        Edit configuration <ChevronRight size={14} />
      </Link>
    </Panel>
  );
  return (
    <div className={`workspace ${collapsed ? 'collapsed' : ''}`}>
      <aside className={mobile ? 'sidebar open' : 'sidebar'}>
        <Link href="/dashboard" className="brand">
          <span className="brand-icon">
            <BarChart3 size={24} />
          </span>
          <span>
            Algo<span className="cyan">Lens</span>
            <small>EXPLAINABLE TRADING</small>
          </span>
        </Link>
        <div className="workspace-label">
          WORKSPACE{' '}
          <button aria-label="Collapse sidebar" onClick={toggle}>
            <Menu size={15} />
          </button>
        </div>
        <nav>
          {navigation.map(([path, label, Icon]) => (
            <Link
              key={path}
              href={'/' + path}
              onClick={() => setMobile(false)}
              className={path === screen ? 'nav-item active' : 'nav-item'}
              title={label}
            >
              <Icon size={18} />
              <span>{label}</span>
              {path === screen && <span className="nav-dot" />}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="help-card">
            <CircleHelp size={19} />
            <strong>Clarity at every step.</strong>
            <p>Inspect the why behind every trade.</p>
            <Link href="/logs">
              Explore execution logs <ArrowUpRight size={13} />
            </Link>
          </div>
          <div className="server-status">
            <span className={connection === 'Connected' ? 'dot green-dot' : 'dot amber-dot'} />
            <span>Backend {connection.toLowerCase()}</span>
          </div>
          <div className="version">
            AlgoLens <span>v0.1.0 · Hackathon</span>
          </div>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu"
              onClick={() => setMobile(!mobile)}
              aria-label="Toggle navigation"
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{title}</strong>
          </div>
          <div className="topbar-right">
            <Badge tone="amber">{data?.mode === 'demo' ? 'DEMO MODE' : 'TESTNET'}</Badge>
            <span className="top-connection">
              <span className={stale ? 'dot amber-dot' : 'dot green-dot'} />
              {stale ? 'Awaiting fresh data' : 'System operational'}
            </span>
            <button
              title="Show system notifications"
              onClick={() => setNotice(data?.error || 'No new system alerts')}
              aria-label="Notifications"
            >
              <Bell size={18} />
            </button>
            <span className="avatar">AL</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">YOUR EDGE, EXPLAINED</div>
              <h1>
                {title === 'Overview' ? 'Trading overview' : title}
                <span className="heading-dot">.</span>
              </h1>
              <p>
                {screen === 'dashboard'
                  ? 'A clear view of your markets, strategies, and every decision in between.'
                  : 'Transparent automation. Observable execution. Complete control.'}
              </p>
            </div>
            <div className="heading-meta">
              <span>
                <Clock size={13} /> Updated {stamp(data?.last_update)}
              </span>
              <Badge>
                <Radio size={12} />
                {data?.config.symbol || 'BTCUSD'}
              </Badge>
            </div>
          </div>
          <div className={'mode-banner ' + (data?.mode === 'testnet' ? 'testnet' : '')}>
            <Shield size={15} />
            <strong>
              {data?.mode === 'testnet'
                ? 'DELTA EXCHANGE TESTNET — NO REAL CAPITAL'
                : 'SIMULATED DATA — DEMO MODE'}
            </strong>
            <span>
              {data?.mode === 'testnet'
                ? 'Read-only · execution locked pending account verification'
                : 'Deterministic walkthrough · no exchange orders · accelerated replay clock'}
            </span>
          </div>
          {notice && (
            <div role="status" className="notice">
              {notice}
              <button aria-label="Dismiss notification" onClick={() => setNotice('')}>
                <X size={16} />
              </button>
            </div>
          )}
          {query.isError && (
            <div className="error-state" role="alert">
              <strong>Backend unavailable</strong>
              <p>Start FastAPI on the configured API URL. No simulated fallback is used.</p>
              <Button variant="outline" onClick={() => void query.refetch()}>
                Retry connection
              </Button>
            </div>
          )}
          {!data && !query.isError && (
            <div className="skeleton-grid">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div className="skeleton" key={i} />
              ))}
            </div>
          )}
          {data && (
            <>
              {(stale || data.error) && (
                <div className="callout warning">
                  {data.error ||
                    'Connection interrupted or data delayed. Displayed values may be stale.'}
                </div>
              )}
              {(screen === 'dashboard' || screen === 'risk') && (
                <div className="metric-grid">
                  {[
                    [
                      'Account equity',
                      money(data.account?.equity),
                      Wallet,
                      'Account settlement · USD',
                    ],
                    [
                      'Available margin',
                      money(data.account?.available_margin),
                      Shield,
                      'Available for new positions',
                    ],
                    [
                      'Unrealized P&L',
                      signed(data.account?.unrealized_pnl),
                      TrendingUp,
                      'Across open positions',
                    ],
                    [
                      'Session realized P&L',
                      signed(data.account?.realized_pnl),
                      BarChart3,
                      'Since strategy session start',
                    ],
                  ].map(([label, value, Icon, caption], i) => {
                    const I = Icon as typeof Wallet;
                    return (
                      <div className="metric" key={String(label)}>
                        <div className="metric-label">
                          {String(label)}
                          <I size={16} />
                        </div>
                        <div
                          className={
                            'metric-value ' +
                            (i > 1
                              ? ((i === 2
                                  ? data.account?.unrealized_pnl
                                  : data.account?.realized_pnl) || 0) >= 0
                                ? 'positive'
                                : 'negative'
                              : '')
                          }
                        >
                          {String(value)}
                        </div>
                        <div className="metric-caption">
                          <span className="tiny-dot" />
                          {String(caption)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {screen === 'dashboard' && (
                <>
                  <div className="dashboard-main">
                    {chart}
                    {strategy}
                  </div>
                  <div className="dashboard-secondary">
                    <Panel
                      title="Latest trading signal"
                      eyebrow="DECISION ENGINE"
                      action={
                        <Badge tone={latest ? 'cyan' : 'neutral'}>
                          {latest?.side || 'MONITORING'}
                        </Badge>
                      }
                    >
                      {latest ? (
                        <>
                          <div className="signal-summary">
                            <span
                              className={
                                'signal-icon ' + (latest.side === 'BUY' ? 'positive' : 'negative')
                              }
                            >
                              {latest.side === 'BUY' ? <ArrowUpRight /> : <ArrowDownLeft />}
                            </span>
                            <div>
                              <strong>
                                {latest.side} · {latest.symbol}
                              </strong>
                              <p>
                                {stamp(latest.timestamp)} · {latest.timeframe} completed candle
                              </p>
                            </div>
                            <span className="mono">{money(latest.price)}</span>
                          </div>
                          <p className="explanation">{latest.explanation}</p>
                          <div className="signal-footer">
                            <Badge tone={latest.status === 'REJECTED' ? 'red' : 'green'}>
                              {latest.status}
                            </Badge>
                            <button className="text-link" onClick={() => inspect(latest.id)}>
                              <Eye size={14} />
                              Inspect decision
                            </button>
                          </div>
                        </>
                      ) : (
                        <Empty text="Monitoring market conditions. No actionable signal detected." />
                      )}
                    </Panel>
                    <Panel
                      title="Risk at a glance"
                      eyebrow="CAPITAL PROTECTION"
                      action={<Shield size={18} className="cyan" />}
                    >
                      <Exposure data={data} />
                      <div className="risk-mini">
                        <span>Daily realized loss</span>
                        <strong>
                          {money(data.account?.daily_loss)}{' '}
                          <span>/ {money(data.risk_config.daily_loss_limit)}</span>
                        </strong>
                      </div>
                      <div className="risk-mini">
                        <span>Risk configuration</span>
                        <Badge tone={data.risk_config.confirmed ? 'green' : 'amber'}>
                          {data.risk_config.confirmed ? 'CONFIRMED' : 'REQUIRES SETUP'}
                        </Badge>
                      </div>
                      <Link href="/risk" className="text-link">
                        Manage risk limits <ChevronRight size={14} />
                      </Link>
                    </Panel>
                  </div>
                  <Panel
                    title="Active positions"
                    action={<Badge>{data.positions.length} OPEN</Badge>}
                  >
                    <Positions data={data} select={setDetail} />
                  </Panel>
                  <Panel
                    title="Recent execution events"
                    action={
                      <Link href="/logs" className="text-link">
                        View all logs <ChevronRight size={14} />
                      </Link>
                    }
                  >
                    <Events events={data.events.slice(0, 5)} select={setEvent} />
                  </Panel>
                </>
              )}
              {screen === 'trading' && (
                <>
                  <div className="dashboard-main">
                    {chart}
                    {strategy}
                  </div>
                  <TradingTabs data={data} select={setDetail} inspect={inspect} event={setEvent} />
                </>
              )}
              {screen === 'strategy' && (
                <>
                  <div className="dashboard-main">
                    <Panel title="Configure EMA Crossover" eyebrow="STRATEGY PARAMETERS">
                      <StrategyForm
                        key={JSON.stringify(data.config)}
                        data={data}
                        busy={busy}
                        save={(c) => action('/api/strategy/config', 'PUT', c)}
                      />
                    </Panel>
                    {strategy}
                  </div>
                  <Panel
                    title="How the strategy makes a decision"
                    eyebrow="DETERMINISTIC · TRACEABLE"
                  >
                    <div className="flow">
                      {[
                        'Completed candle',
                        'EMA calculation',
                        'Crossover signal',
                        'Risk validation',
                        'Order execution',
                        'Position monitor',
                      ].map((s, i) => (
                        <div key={s}>
                          <span>{String(i + 1).padStart(2, '0')}</span>
                          <strong>{s}</strong>
                          {i < 5 && <ChevronRight size={16} />}
                        </div>
                      ))}
                    </div>
                    <p className="explanation">
                      BUY when the previous fast EMA was at or below the slow EMA and the latest
                      fast EMA crosses above it. SELL uses the reverse comparison. An opposite
                      signal closes the existing position; it does not immediately reverse it.
                    </p>
                    <p className="explanation">
                      Signals use completed candles only, after at least{' '}
                      {data.config.slow_period + 1} candles. Each candle is evaluated once.
                      Explanations and indicator values come from the backend.
                    </p>
                  </Panel>
                  <Panel title="Emergency controls">
                    <div className="emergency">
                      <div>
                        <strong>Stop automation safely</strong>
                        <p>
                          Disables new strategy orders. Existing positions remain open; protective
                          exits and monitoring continue.
                        </p>
                      </div>
                      <Button
                        variant="destructive"
                        disabled={busy}
                        onClick={() => void action('/api/strategy/emergency-stop')}
                      >
                        <Square size={14} />
                        Emergency stop
                      </Button>
                    </div>
                  </Panel>
                </>
              )}
              {screen === 'positions' && (
                <Panel
                  title="Open positions"
                  action={<Badge>{data.positions.length} ACTIVE</Badge>}
                >
                  <Positions data={data} select={setDetail} />
                  <p className="table-note">
                    Stopping the bot does not close positions. Protective exits continue while the
                    Demo backend runs. Manual closing is not enabled.
                  </p>
                </Panel>
              )}
              {screen === 'orders' && <Orders data={data} inspect={inspect} select={setDetail} />}
              {screen === 'risk' && (
                <>
                  <div className="dashboard-secondary">
                    <Panel title="Exposure utilization">
                      <Exposure data={data} />
                      <div className="risk-spark">
                        <ResponsiveContainer width="100%" height={100}>
                          <AreaChart
                            data={data.candles
                              .slice(-40)
                              .map((c) => ({ time: c.time, price: c.close }))}
                          >
                            <defs>
                              <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.2} />
                                <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <Tooltip
                              contentStyle={{ background: '#111c2e', border: '1px solid #263449' }}
                            />
                            <Area
                              dataKey="price"
                              stroke="#38bdf8"
                              fill="url(#area)"
                              type="monotone"
                            />
                          </AreaChart>
                        </ResponsiveContainer>
                        <small>
                          Underlying candle close · {data.mode === 'demo' ? 'simulated' : 'Testnet'}
                        </small>
                      </div>
                    </Panel>
                    <Panel title="Configure risk limits">
                      <RiskForm
                        data={data}
                        busy={busy}
                        save={(c) => action('/api/risk/config', 'PUT', c)}
                      />
                    </Panel>
                  </div>
                  <Panel title="Risk rules">
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Rule</th>
                            <th>Configured limit</th>
                            <th>Current value</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[
                            [
                              'Position size',
                              `${data.risk_config.max_quantity} contracts`,
                              `${data.config.quantity} contracts`,
                              data.config.quantity <= data.risk_config.max_quantity,
                            ],
                            [
                              'Account exposure',
                              `${data.risk_config.max_exposure_pct}%`,
                              data.account
                                ? `${((data.account.exposure / data.account.equity) * 100).toFixed(2)}%`
                                : 'Unavailable',
                              !!data.account &&
                                data.account.exposure <=
                                  (data.account.equity * data.risk_config.max_exposure_pct) / 100,
                            ],
                            [
                              'Daily loss',
                              money(data.risk_config.daily_loss_limit),
                              money(data.account?.daily_loss),
                              !!data.account &&
                                data.account.daily_loss < data.risk_config.daily_loss_limit,
                            ],
                            [
                              'Concurrent positions',
                              '1',
                              String(data.positions.length),
                              data.positions.length <= 1,
                            ],
                            [
                              'Stop-loss requirement',
                              'Required',
                              `${data.config.stop_loss_pct}%`,
                              data.config.stop_loss_pct > 0,
                            ],
                          ].map(([rule, limit, current, passed]) => (
                            <tr key={String(rule)}>
                              <td>{String(rule)}</td>
                              <td>{String(limit)}</td>
                              <td>{String(current)}</td>
                              <td>
                                <Badge tone={passed ? 'green' : 'amber'}>
                                  {passed ? 'PASSED' : 'NOT READY'}
                                </Badge>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Panel>
                  <Panel title="Rejected decisions">
                    {data.decisions.filter((d) => d.status === 'REJECTED').length ? (
                      data.decisions
                        .filter((d) => d.status === 'REJECTED')
                        .map((d) => (
                          <button className="decision-row" key={d.id} onClick={() => inspect(d.id)}>
                            <Badge tone="red">REJECTED</Badge>
                            <span>{d.explanation}</span>
                            <Eye size={16} />
                          </button>
                        ))
                    ) : (
                      <Empty text="No risk-rejected signals" />
                    )}
                  </Panel>
                </>
              )}
              {screen === 'logs' && (
                <Panel
                  title="Execution timeline"
                  eyebrow="AUDIT TRAIL"
                  action={
                    <div className="log-filters">
                      <select
                        aria-label="Filter event severity"
                        value={logSeverity}
                        onChange={(e) => setLogSeverity(e.target.value)}
                      >
                        <option value="ALL">All severities</option>
                        <option>INFO</option>
                        <option>WARNING</option>
                        <option>ERROR</option>
                      </select>
                      <select
                        aria-label="Filter event type"
                        value={logFilter}
                        onChange={(e) => setLogFilter(e.target.value)}
                      >
                        <option value="ALL">All events</option>
                        {Array.from(new Set(data.events.map((e) => e.type))).map((t) => (
                          <option key={t}>{t}</option>
                        ))}
                      </select>
                    </div>
                  }
                >
                  <Events
                    events={data.events.filter(
                      (e) =>
                        (logFilter === 'ALL' || e.type === logFilter) &&
                        (logSeverity === 'ALL' || e.severity === logSeverity),
                    )}
                    select={setEvent}
                  />
                </Panel>
              )}
              {screen === 'settings' && (
                <>
                  <Panel title="Exchange connection" eyebrow="ENVIRONMENT">
                    <div className="settings-row">
                      <div>
                        <strong>Delta Exchange Testnet</strong>
                        <p>
                          {data.mode === 'demo'
                            ? 'Demo Mode · no exchange connection'
                            : data.exchange_connected
                              ? 'Market data connected · execution locked'
                              : 'Disconnected · configure backend credentials'}
                        </p>
                      </div>
                      <Badge tone={data.exchange_connected ? 'green' : 'amber'}>
                        {data.exchange_connected ? 'CONNECTED' : 'NOT CONNECTED'}
                      </Badge>
                    </div>
                    <div className="settings-row">
                      <div>
                        <strong>Backend connectivity</strong>
                        <p>
                          {connection} · Last market update {stamp(data.last_update)}
                        </p>
                      </div>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => void action('/api/connection/test')}
                      >
                        Test connection
                      </Button>
                    </div>
                    <p className="table-note">
                      Credentials are configured through backend environment variables. Never enter
                      secrets in the browser. Change operating mode through ALGOLENS_MODE and
                      restart the backend.
                    </p>
                  </Panel>
                  <Panel title="Application preferences">
                    <Preferences />
                  </Panel>
                  <Panel title="Strategy defaults">
                    <div className="settings-row">
                      <span>
                        EMA {data.config.fast_period}/{data.config.slow_period} ·{' '}
                        {data.config.timeframe} · {data.config.symbol}
                      </span>
                      <Link className="text-link" href="/strategy">
                        Edit strategy <ChevronRight size={14} />
                      </Link>
                    </div>
                  </Panel>
                </>
              )}
            </>
          )}
          <footer>
            <span>
              AlgoLens <span className="muted">/</span> Every decision. In focus.
            </span>
            <span>
              <Shield size={12} />{' '}
              {data?.mode === 'testnet'
                ? 'Testnet · no real capital'
                : 'Demo · no real exchange execution'}
            </span>
          </footer>
        </main>
      </div>
      <Dialog.Root
        open={!!selected || !!event || !!detail}
        onOpenChange={(open) => {
          if (!open) {
            inspect(null);
            setEvent(null);
            setDetail(null);
          }
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="drawer">
            <div className="drawer-head">
              <div>
                <div className="eyebrow">TRANSPARENCY, BUILT IN</div>
                <Dialog.Title>
                  {selected
                    ? 'Trade Decision Inspector'
                    : event
                      ? 'Event details'
                      : 'Trading details'}
                </Dialog.Title>
              </div>
              <Dialog.Close aria-label="Close inspector">
                <X />
              </Dialog.Close>
            </div>
            <Dialog.Description className="muted">
              {selected
                ? 'Trace the market snapshot, strategy evaluation, risk checks and exchange result.'
                : 'Structured backend data with identifiers and timestamps.'}
            </Dialog.Description>
            {decision ? (
              <>
                <div className="inspect-summary">
                  <Badge tone={decision.side === 'BUY' ? 'green' : 'red'}>{decision.side}</Badge>
                  <strong>{decision.symbol}</strong>
                  <span>{money(decision.price)}</span>
                </div>
                <p className="explanation">{decision.explanation}</p>
                <h3>Market snapshot</h3>
                <dl>
                  <dt>Signal time</dt>
                  <dd>{new Date(decision.timestamp).toLocaleString()}</dd>
                  <dt>Completed candle</dt>
                  <dd>{new Date(decision.candle_time * 1000).toISOString()}</dd>
                  <dt>Timeframe</dt>
                  <dd>{decision.timeframe}</dd>
                </dl>
                <h3>Strategy evaluation</h3>
                <dl>
                  <dt>Previous fast / slow</dt>
                  <dd>
                    {decision.previous_fast_ema.toFixed(4)} /{' '}
                    {decision.previous_slow_ema.toFixed(4)}
                  </dd>
                  <dt>Current fast / slow</dt>
                  <dd>
                    {decision.fast_ema.toFixed(4)} / {decision.slow_ema.toFixed(4)}
                  </dd>
                </dl>
                <h3>Risk evaluation</h3>
                {decision.risk_checks.length ? (
                  decision.risk_checks.map((c) => (
                    <div className="check-row" key={c.rule}>
                      <Check size={15} />
                      <div>
                        <strong>{c.rule}</strong>
                        <p>{c.detail}</p>
                      </div>
                      <Badge tone={c.status === 'PASSED' ? 'green' : 'red'}>{c.status}</Badge>
                    </div>
                  ))
                ) : (
                  <p className="muted">NOT EVALUATED · no new entry requested</p>
                )}
                <h3>Execution result</h3>
                <dl>
                  <dt>Status</dt>
                  <dd>{decision.status}</dd>
                  <dt>Order ID</dt>
                  <dd>{decision.order_id || 'No order created'}</dd>
                  <dt>Correlation ID</dt>
                  <dd>{decision.id}</dd>
                </dl>
                {data?.orders
                  .filter((o) => o.correlation_id === decision.id)
                  .map((o) => (
                    <pre key={o.id}>{JSON.stringify(o, null, 2)}</pre>
                  ))}
              </>
            ) : (
              <pre>{JSON.stringify(event || detail, null, 2)}</pre>
            )}
            {selected && !decision && (
              <p>
                Decision is outside the recent buffer. Retrieve its persisted record using the
                decisions API.
              </p>
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

function Exposure({ data }: { data: Snapshot }) {
  const current = data.account ? (data.account.exposure / data.account.equity) * 100 : 0;
  const utilization = (current / data.risk_config.max_exposure_pct) * 100;
  return (
    <>
      <div className="exposure-values">
        <strong>{data.account ? current.toFixed(2) + '%' : 'Unavailable'}</strong>
        <span>of {data.risk_config.max_exposure_pct}% maximum exposure</span>
      </div>
      <div className="progress-track">
        <div style={{ width: `${Math.min(utilization, 100)}%` }} />
      </div>
      <div className="progress-labels">
        <span>0%</span>
        <span>{utilization.toFixed(1)}% of limit used</span>
      </div>
    </>
  );
}
function Positions({ data, select }: { data: Snapshot; select: (v: unknown) => void }) {
  if (data.mode === 'testnet')
    return <Empty text="Position data unavailable in read-only Testnet mode" />;
  if (!data.positions.length) return <Empty text="No open positions" />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {[
              'Instrument',
              'Direction',
              'Size',
              'Entry price',
              'Mark price',
              'Unrealized P&L',
              'Stop loss',
              'Protection',
            ].map((t) => (
              <th key={t}>{t}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.positions.map((p) => (
            <tr
              key={p.id}
              onClick={() =>
                select({
                  ...p,
                  related_orders: data.orders.filter((o) => o.correlation_id === p.id),
                })
              }
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter') select(p);
              }}
            >
              <td>
                <strong>{p.symbol}</strong>
              </td>
              <td>
                <Badge tone={p.side === 'BUY' ? 'green' : 'red'}>
                  {p.side === 'BUY' ? 'LONG' : 'SHORT'}
                </Badge>
              </td>
              <td>{p.quantity}</td>
              <td>{money(p.entry_price)}</td>
              <td>{money(p.mark_price)}</td>
              <td className={p.unrealized_pnl >= 0 ? 'positive' : 'negative'}>
                {signed(p.unrealized_pnl)}
              </td>
              <td>{money(p.stop_loss)}</td>
              <td>
                <Badge tone="green">{p.protection}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Events({ events, select }: { events: TradingEvent[]; select: (e: TradingEvent) => void }) {
  return events.length ? (
    <div className="event-list">
      {events.map((e) => (
        <button className="event-row" key={e.event_id} onClick={() => select(e)}>
          <span className={'event-icon ' + (e.severity === 'ERROR' ? 'negative' : 'cyan')}>
            <Code2 size={15} />
          </span>
          <span className="event-time">{stamp(e.timestamp)}</span>
          <span className="event-content">
            <strong>{e.type.replaceAll('_', ' ')}</strong>
            <small>
              {String(
                e.payload.message || e.payload.explanation || e.payload.status || e.correlation_id,
              )}
            </small>
          </span>
          <Badge tone={e.severity === 'ERROR' ? 'red' : 'neutral'}>{e.severity}</Badge>
          <ChevronRight size={14} />
        </button>
      ))}
    </div>
  ) : (
    <Empty text="No execution events" />
  );
}
function Orders({
  data,
  inspect,
  select,
  openOnly = false,
}: {
  data: Snapshot;
  inspect: (id: string) => void;
  select: (v: unknown) => void;
  openOnly?: boolean;
}) {
  const [filter, setFilter] = useState(openOnly ? 'OPEN' : 'ALL'),
    [side, setSide] = useState('ALL'),
    [page, setPage] = useState(1),
    [from, setFrom] = useState(''),
    [to, setTo] = useState('');
  const params = new URLSearchParams({
    page: String(page),
    page_size: '15',
    symbol: data.config.symbol,
  });
  if (filter !== 'ALL') params.set('status', filter);
  if (side !== 'ALL') params.set('side', side);
  if (from) params.set('start', from + 'T00:00:00');
  if (to) params.set('end', to + 'T23:59:59.999999');
  const orders = useQuery({
    queryKey: ['orders', params.toString()],
    queryFn: () => api<{ items: Order[]; total: number }>('/api/orders?' + params),
    refetchInterval: 2000,
    retry: 1,
  });
  const items = orders.data?.items || [],
    total = orders.data?.total || 0;
  return (
    <Panel
      title={openOnly ? 'Open orders' : 'Order history'}
      action={<Badge>{total} ORDERS</Badge>}
    >
      <div className="tabs">
        {(openOnly ? ['OPEN'] : ['ALL', 'OPEN', 'FILLED', 'CANCELLED', 'REJECTED']).map((s) => (
          <button
            key={s}
            className={filter === s ? 'selected' : ''}
            onClick={() => {
              setFilter(s);
              setPage(1);
            }}
          >
            {s === 'ALL' ? 'All orders' : s.toLowerCase()}
          </button>
        ))}
        <select
          aria-label="Filter order side"
          value={side}
          onChange={(e) => {
            setSide(e.target.value);
            setPage(1);
          }}
        >
          <option value="ALL">All sides</option>
          <option>BUY</option>
          <option>SELL</option>
        </select>
      </div>
      <div className="order-dates">
        <label>
          From UTC{' '}
          <input
            aria-label="Orders from date"
            type="date"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <label>
          To UTC{' '}
          <input
            aria-label="Orders to date"
            type="date"
            value={to}
            min={from}
            onChange={(e) => {
              setTo(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <span>{data.config.symbol}</span>
      </div>
      {orders.isError ? (
        <p role="alert" className="negative table-note">
          Unable to load order history.
        </p>
      ) : orders.isPending ? (
        <p className="table-note">Loading orders…</p>
      ) : items.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  'Time',
                  'Order ID',
                  'Symbol',
                  'Side',
                  'Quantity / Filled',
                  'Price',
                  'Status',
                  'Decision',
                ].map((s) => (
                  <th key={s}>{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((o) => (
                <tr key={o.id}>
                  <td>{stamp(o.timestamp)}</td>
                  <td>
                    <button className="mono text-link" onClick={() => select(o)}>
                      {o.id}
                    </button>
                  </td>
                  <td>{o.symbol}</td>
                  <td className={o.side === 'BUY' ? 'positive' : 'negative'}>{o.side}</td>
                  <td>
                    {o.quantity} / {o.filled_quantity}
                  </td>
                  <td>{money(o.average_fill_price)}</td>
                  <td>
                    <Badge tone={o.status === 'FILLED' ? 'green' : 'amber'}>{o.status}</Badge>
                  </td>
                  <td>
                    <button className="text-link" onClick={() => inspect(o.correlation_id)}>
                      <Eye size={14} />
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty text="No matching orders" />
      )}
      <div className="pagination">
        <Button variant="ghost" disabled={page === 1} onClick={() => setPage(page - 1)}>
          Previous
        </Button>
        <span>Page {page}</span>
        <Button variant="ghost" disabled={page * 15 >= total} onClick={() => setPage(page + 1)}>
          Next
        </Button>
      </div>
    </Panel>
  );
}
function TradingTabs({
  data,
  select,
  inspect,
  event,
}: {
  data: Snapshot;
  select: (v: unknown) => void;
  inspect: (id: string) => void;
  event: (v: TradingEvent) => void;
}) {
  const [tab, setTab] = useState('Positions');
  return (
    <>
      <div className="tabs terminal-tabs">
        {['Positions', 'Open orders', 'Order history', 'Strategy events'].map((t) => (
          <button className={tab === t ? 'selected' : ''} key={t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === 'Positions' ? (
        <Panel title="Positions">
          <Positions data={data} select={select} />
        </Panel>
      ) : tab === 'Strategy events' ? (
        <Panel title="Strategy events">
          <Events events={data.events} select={event} />
        </Panel>
      ) : (
        <Orders
          key={tab}
          data={data}
          openOnly={tab === 'Open orders'}
          inspect={inspect}
          select={select}
        />
      )}
    </>
  );
}
function Preferences() {
  const { precision, setPrecision, notifications, setNotifications } = usePreferences();
  return (
    <div className="form-grid">
      <label>
        Price display precision
        <select value={precision} onChange={(e) => setPrecision(Number(e.target.value))}>
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
            <option key={n} value={n}>
              {n} decimal places
            </option>
          ))}
        </select>
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={notifications}
          onChange={(e) => setNotifications(e.target.checked)}
        />
        Show action success notifications
      </label>
      <p className="table-note">
        Preferences are saved on this device. Errors and connection-test results always remain
        visible. Instrument and candle timeframe are configured in Strategy Control.
      </p>
    </div>
  );
}
