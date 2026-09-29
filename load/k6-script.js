/**
 * k6 load profile for the HPA demonstration.
 *
 *   k6 run --env BASE_URL=http://civicpulse.local:8081 load/k6-script.js
 *
 * In another terminal, capture the scale-out:
 *
 *   kubectl get hpa backend-hpa -n civicpulse -w | tee docs/evidence/hpa-watch.txt
 *   kubectl get pods -n civicpulse -l app.kubernetes.io/name=backend -w
 *
 * Shape of the run, and why:
 *
 *   0-1m    warm-up at 5 VUs        establishes a baseline below the 60% target
 *   1-2m    ramp to 60 VUs          the step that should trigger scale-up
 *   2-5m    hold at 60 VUs          long enough to see replicas actually arrive
 *   5-6m    ramp down to 0          the scale-down stabilisation window starts
 *
 * The step at 1m is the measurement that matters. Note the wall-clock time it
 * happens, then the time `kubectl get hpa -w` first shows a higher replica
 * count. That gap is the HPA lag, and it is the number the engineering notes ask
 * for. It is not one delay but four stacked: the kubelet's 10s metrics window,
 * metrics-server's ~15s scrape, the HPA controller's 15s sync loop, and then
 * pod scheduling plus image pull plus the startupProbe. Roughly 45-75s on a
 * local cluster before new capacity serves its first request.
 *
 * That lag is precisely why autoscaling is not a substitute for capacity
 * planning: for a minute after the load arrives, you are serving it with the
 * pods you already had.
 *
 * Reads dominate on purpose. POST /api/complaints is rate-limited to 10 per
 * minute per IP -- correctly, because it is what stands between one bored user
 * with a for loop and a whole day of free LLM quota. Hammering it would measure
 * the rate limiter, not the autoscaler.
 */

import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter, Rate, Trend } from 'k6/metrics'

const BASE_URL = __ENV.BASE_URL || 'http://civicpulse.local:8081'

const cacheHits = new Counter('civicpulse_stats_cache_hits')
const cacheMisses = new Counter('civicpulse_stats_cache_misses')
const rateLimited = new Counter('civicpulse_rate_limited')
const triageLatency = new Trend('civicpulse_triage_latency_ms')
const failed = new Rate('civicpulse_failed_requests')

export const options = {
  scenarios: {
    hpa_demo: {
      executor: 'ramping-vus',
      startVUs: 5,
      stages: [
        { duration: '1m', target: 5 },   // baseline
        { duration: '1m', target: 60 },  // the step
        { duration: '3m', target: 60 },  // hold, so capacity can catch up
        { duration: '1m', target: 0 },   // release
      ],
      gracefulRampDown: '15s',
    },
  },
  thresholds: {
    // A rolling update under this load must drop nothing. This threshold is
    // what turns "zero-downtime" from a claim into a pass/fail.
    civicpulse_failed_requests: ['rate<0.01'],
    http_req_duration: ['p(95)<2000'],
  },
}

const LOCATIONS = [
  'Street 12, G-9/4, Islamabad',
  'Lane 6, Nazimabad Block 2, Karachi',
  'Model Town Link Road, Lahore',
  'Chaklala Scheme 3, Rawalpindi',
  'Peoples Colony, Faisalabad',
]

const COMPLAINTS = [
  'Burst water main flooding the street since morning, water entering houses.',
  'Transformer is sparking badly and a live wire is hanging over the footpath.',
  'Garbage has not been lifted from our lane for two weeks, kachra everywhere.',
  'Very big pothole in the middle of the road, a motorcycle accident happened.',
  'Street lights of our whole lane are not working, it is dark after maghrib.',
]

function pick(list) {
  return list[Math.floor(Math.random() * list.length)]
}

export default function () {
  // --- Read path: what the autoscaler is actually being measured on ---------
  const list = http.get(`${BASE_URL}/api/complaints?page=1&page_size=10`, {
    tags: { name: 'GET /api/complaints' },
  })
  failed.add(list.status !== 200)
  check(list, { 'list returns 200': (r) => r.status === 200 })

  const stats = http.get(`${BASE_URL}/api/stats`, { tags: { name: 'GET /api/stats' } })
  failed.add(stats.status !== 200)
  check(stats, { 'stats returns 200': (r) => r.status === 200 })

  // Tracking this is how you report a real hit rate rather than asserting one.
  if (stats.headers['X-Cache'] === 'HIT') cacheHits.add(1)
  else if (stats.headers['X-Cache'] === 'MISS') cacheMisses.add(1)

  // --- Write path: sampled, not hammered -----------------------------------
  // 1 in 50 iterations, so the rate limiter is exercised (some 429s are
  // EXPECTED and correct) without the run becoming a test of the limiter.
  if (Math.random() < 0.02) {
    const payload = JSON.stringify({
      text: `${pick(COMPLAINTS)} Ref ${__VU}-${__ITER}.`,
      location: pick(LOCATIONS),
    })
    const created = http.post(`${BASE_URL}/api/complaints`, payload, {
      headers: { 'Content-Type': 'application/json' },
      tags: { name: 'POST /api/complaints' },
    })

    if (created.status === 429) {
      // Not a failure. The limiter doing its job is a pass.
      rateLimited.add(1)
      check(created, {
        '429 carries Retry-After': (r) => r.headers['Retry-After'] !== undefined,
      })
    } else {
      failed.add(created.status !== 201)
      check(created, { 'submit returns 201': (r) => r.status === 201 })
      if (created.status === 201) {
        const body = created.json()
        triageLatency.add(body.triage_latency_ms)
        check(created, {
          'category is from the enum': (r) =>
            ['water', 'electricity', 'sanitation', 'roads', 'streetlights', 'other'].includes(
              r.json().category,
            ),
        })
      }
    }
  }

  sleep(0.5 + Math.random() * 0.5)
}

export function handleSummary(data) {
  const hits = data.metrics.civicpulse_stats_cache_hits?.values?.count ?? 0
  const misses = data.metrics.civicpulse_stats_cache_misses?.values?.count ?? 0
  const total = hits + misses
  const hitRate = total > 0 ? ((hits / total) * 100).toFixed(1) : 'n/a'

  return {
    stdout: `
CivicPulse load summary
-----------------------
  /api/stats cache      ${hits} HIT / ${misses} MISS  (${hitRate}% hit rate)
  429 responses         ${data.metrics.civicpulse_rate_limited?.values?.count ?? 0} (expected: the limiter working)
  failed request rate   ${((data.metrics.civicpulse_failed_requests?.values?.rate ?? 0) * 100).toFixed(2)}%
  p95 latency           ${(data.metrics.http_req_duration?.values?.['p(95)'] ?? 0).toFixed(0)} ms

Now put the replica timeline from \`kubectl get hpa -w\` next to this run's
start time. The gap between the 1m step and the first replica increase is your
HPA lag -- write it into docs/ENGINEERING-NOTES.md Q5.
`,
    'load/results/summary.json': JSON.stringify(data, null, 2),
  }
}
