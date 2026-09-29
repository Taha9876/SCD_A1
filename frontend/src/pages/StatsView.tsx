import { useCallback, useEffect, useState } from 'react'

import { ApiError, getProviders, getStats } from '../api/client'
import {
  CATEGORIES,
  PRIORITIES,
  STATUSES,
  STATUS_LABELS,
  type Priority,
  type ProvidersInfo,
  type StatsResponse,
} from '../api/types'
import {
  IconAlert,
  IconBolt,
  IconCheck,
  IconDatabase,
  IconInbox,
  IconInfo,
  IconMinus,
  IconRefresh,
} from '../components/Icon'
import { CATEGORY_ICON } from '../components/Badge'
import { Alert, Tile } from '../components/ui'

/**
 * Chart decisions, made in this order: form, then colour.
 *
 * Category counts are ONE series (a count) across six identities, so the form
 * is a horizontal bar chart and the colour is ONE hue -- the sequential accent.
 * Six categorical hues would claim six series that do not exist, and would
 * need a legend restating labels the axis already carries.
 *
 * Priority is severity, not identity, so it uses the fixed status palette and
 * a 100%-stacked bar: the question an operator asks is "how much of the queue
 * is urgent", which is a mix, not six magnitudes. Light-mode `warning` sits
 * below 3:1 on the surface by design, so the relief rule applies -- every
 * segment carries a direct label, the legend pairs an icon with a word, and a
 * table view is one click away. Colour is never the only channel.
 *
 * Status is four numbers. A chart would be decoration, so it is four numbers.
 */

const PRIORITY_ICON = { high: IconAlert, normal: IconInfo, low: IconMinus } as const
const PRIORITY_CLASS: Record<Priority, string> = {
  high: 'mix-high',
  normal: 'mix-normal',
  low: 'mix-low',
}

export function StatsView() {
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [providers, setProviders] = useState<ProvidersInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [showTable, setShowTable] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // Fetched together but tolerated separately: the observability panel
      // failing should not hide the statistics.
      const [statsResult, providerResult] = await Promise.allSettled([
        getStats(),
        getProviders(),
      ])
      if (statsResult.status === 'fulfilled') setStats(statsResult.value)
      else throw statsResult.reason
      setProviders(providerResult.status === 'fulfilled' ? providerResult.value : null)
    } catch (err) {
      setError(err instanceof ApiError ? err.body.detail : 'Could not load statistics.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const s = stats?.stats
  const categoryRows = s
    ? CATEGORIES.map((c) => ({ name: c, count: s.by_category[c] ?? 0 })).sort(
        (a, b) => b.count - a.count,
      )
    : []
  const maxCategory = Math.max(1, ...categoryRows.map((r) => r.count))

  const priorityRows = s
    ? PRIORITIES.map((p) => ({ name: p, count: s.by_priority[p] ?? 0 }))
    : []
  const priorityTotal = priorityRows.reduce((sum, r) => sum + r.count, 0)

  const highCount = s?.by_priority.high ?? 0
  const openCount = s?.by_status.open ?? 0
  const fallbackCount = providers?.recent.filter((r) => r.fallback).length ?? 0
  const recentCount = providers?.recent.length ?? 0

  return (
    <section>
      <div className="page-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
        <div>
          <h2>Statistics</h2>
          <p className="lede">Aggregates across every complaint on record.</p>
        </div>
        <button type="button" className="button button-quiet" onClick={() => void load()} disabled={loading}>
          <IconRefresh />
          Refresh
        </button>
      </div>

      {error && <Alert tone="error">{error}</Alert>}

      {s && (
        <>
          {/* Exactly one hero figure per view. */}
          <div className="tiles">
            <Tile
              hero
              label="Complaints recorded"
              value={s.total.toLocaleString()}
              icon={<IconInbox />}
              testId="total-complaints"
            />
            <Tile
              label="High priority"
              value={highCount.toLocaleString()}
              tone={highCount > 0 ? 'critical' : undefined}
              icon={<IconAlert />}
              foot={
                s.total > 0 ? `${Math.round((highCount / s.total) * 100)}% of the queue` : undefined
              }
            />
            <Tile
              label="Still open"
              value={openCount.toLocaleString()}
              icon={<IconInfo />}
              foot={`${(s.by_status.resolved ?? 0).toLocaleString()} resolved`}
            />
            <Tile
              label="Triage fallbacks"
              value={fallbackCount.toLocaleString()}
              icon={<IconBolt />}
              foot={
                recentCount > 0
                  ? `of the last ${recentCount} triaged`
                  : 'no triage activity yet'
              }
            />
          </div>

          {/* --- Cache state, rendered because it is demonstrable ---------- */}
          <div className="panel panel-pad" style={{ marginBottom: '1.25rem' }}>
            <div className="panel-head">
              <h3>
                <IconDatabase
                  style={{ display: 'inline', width: 15, height: 15, verticalAlign: '-2px', marginRight: 6 }}
                />
                Response cache
              </h3>
              <span className="panel-note">
                30&nbsp;s TTL, invalidated on every write
              </span>
            </div>
            <p>
              This response was served from cache:{' '}
              <span
                className={`badge badge-${stats.cacheHit ? 'hit' : 'miss'}`}
                data-testid="cache-badge"
              >
                {stats.cacheHit ? <IconCheck /> : <IconRefresh />}
                {stats.cacheHit ? 'HIT' : 'MISS'}
              </span>
            </p>
            <p className="panel-note" style={{ marginTop: '0.4rem' }}>
              {stats.cacheHit
                ? 'This response came from Redis, not Postgres.'
                : 'Computed fresh; the next request within 30 seconds will be a HIT.'}
            </p>
          </div>

          {/* --- Category magnitude: one series, one hue -------------------- */}
          <div className="panel panel-pad" style={{ marginBottom: '1.25rem' }}>
            <div className="panel-head">
              <h3>Complaints by category</h3>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setShowTable((v) => !v)}
                aria-expanded={showTable}
              >
                {showTable ? 'Show chart' : 'Show table'}
              </button>
            </div>

            {showTable ? (
              <div className="table-wrap">
                <table>
                  <caption>Complaints by category, highest first</caption>
                  <thead>
                    <tr>
                      <th scope="col">Category</th>
                      <th scope="col">Complaints</th>
                      <th scope="col">Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {categoryRows.map((row) => (
                      <tr key={row.name}>
                        <td style={{ textTransform: 'capitalize' }}>{row.name}</td>
                        <td>{row.count}</td>
                        <td>
                          {s.total > 0 ? `${Math.round((row.count / s.total) * 100)}%` : '0%'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <ul className="bars">
                {categoryRows.map((row) => (
                  <li className="bar-row" key={row.name} tabIndex={0}>
                    <span className={`bar-label cat-${row.name}`}>
                      {/* Identity rides the icon; magnitude stays one hue. */}
                      {(() => {
                        const Icon = CATEGORY_ICON[row.name]
                        return <Icon className="cat-ink" />
                      })()}
                      {row.name}
                    </span>
                    <span className="bar-track">
                      <span
                        className="bar-fill"
                        style={{ width: `${(row.count / maxCategory) * 100}%` }}
                      />
                    </span>
                    {/* Value at the tip -- the axis it replaces. */}
                    <span className="bar-count">{row.count}</span>
                    <span className="bar-tip" role="tooltip">
                      {row.name}: {row.count} of {s.total}
                      {s.total > 0 && ` (${Math.round((row.count / s.total) * 100)}%)`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* --- Priority mix: severity, so the status palette -------------- */}
          <div className="panel panel-pad" style={{ marginBottom: '1.25rem' }}>
            <div className="panel-head">
              <h3>Priority mix</h3>
              <span className="panel-note">Decided by triage, not by the citizen</span>
            </div>

            <div
              className="mix"
              role="img"
              aria-label={priorityRows
                .map((r) => `${r.name}: ${r.count}`)
                .join(', ')}
            >
              {priorityRows.map((row) =>
                row.count === 0 ? null : (
                  <span
                    key={row.name}
                    className={`mix-seg ${PRIORITY_CLASS[row.name]}`}
                    style={{ flexBasis: `${(row.count / Math.max(1, priorityTotal)) * 100}%` }}
                  >
                    {/* Direct label -- only when it fits, never clipped. */}
                    {(row.count / Math.max(1, priorityTotal)) > 0.08 ? row.count : ''}
                  </span>
                ),
              )}
            </div>

            {/* Legend: icon + word + count. Identity never rests on hue. */}
            <ul className="legend">
              {priorityRows.map((row) => {
                const Icon = PRIORITY_ICON[row.name]
                return (
                  <li key={row.name}>
                    <span
                      className="key"
                      style={{
                        background:
                          row.name === 'high'
                            ? 'var(--critical)'
                            : row.name === 'normal'
                              ? 'var(--warning)'
                              : 'var(--good)',
                      }}
                    />
                    <Icon />
                    {row.name}
                    <b>{row.count}</b>
                  </li>
                )
              })}
            </ul>
          </div>

          {/* --- Status: four numbers, so four numbers --------------------- */}
          <div className="panel panel-pad" style={{ marginBottom: '1.25rem' }}>
            <div className="panel-head">
              <h3>Pipeline</h3>
              <span className="panel-note">Transitions enforced by the server</span>
            </div>
            <div className="pipeline">
              {STATUSES.map((st) => (
                <div className="pipe-step" key={st}>
                  <div className="pipe-label">{STATUS_LABELS[st]}</div>
                  <div className="pipe-value">{(s.by_status[st] ?? 0).toLocaleString()}</div>
                </div>
              ))}
            </div>
          </div>

          <p className="panel-note" style={{ marginBottom: '1.25rem' }}>
            Generated {new Date(s.generated_at).toLocaleString()}
          </p>
        </>
      )}

      {/* --- Provider observability ------------------------------------- */}
      {providers && (
        <div className="panel panel-pad providers-panel">
          <div className="panel-head">
            <h3>Triage provider</h3>
            <span className="panel-note">The last {providers.recent.length} outcomes</span>
          </div>

          <p>
            Active: <code>{providers.active_provider}</code> (configured as{' '}
            <code>{providers.configured_provider}</code>)
          </p>
          <p style={{ marginTop: '0.3rem' }}>
            Triage cache: {providers.triage_cache.hits}/{providers.triage_cache.lookups} hits
            &mdash; {(providers.triage_cache.hit_rate * 100).toFixed(1)}% hit rate
          </p>

          {providers.recent.length > 0 && (
            <div className="table-wrap" style={{ marginTop: '0.9rem' }}>
              <table className="recent-table">
                <caption>Last {providers.recent.length} triage outcomes</caption>
                <thead>
                  <tr>
                    <th scope="col">Provider</th>
                    <th scope="col">Latency</th>
                    <th scope="col">Cache</th>
                    <th scope="col">Fallback</th>
                    <th scope="col">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {providers.recent.map((record, index) => (
                    <tr key={index} className={record.fallback ? 'row-degraded' : undefined}>
                      <td>
                        <span className={record.fallback ? 'dot dot-warn' : 'dot'} />
                        {record.provider}
                      </td>
                      <td>{record.latency_ms} ms</td>
                      <td>{record.cache_hit ? 'hit' : 'miss'}</td>
                      <td>{record.fallback ? `yes (${record.error_class})` : 'no'}</td>
                      <td>
                        {record.category} / {record.priority}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
