// Zero-downtime rolling update under live load (bonus).
//
// cd.yml starts this, then `kubectl rollout restart`s the backend AND the
// frontend while it runs. The thresholds are the claim: not one request may
// fail, through the Ingress, while every pod of both Deployments is replaced.
//
//   BASE_URL=http://localhost:8081 HOST_HEADER=civicpulse.local k6 run load/k6-rolling.js
//
// Reads only. A rolling update is about requests in flight when a pod goes
// away; a POST adds nothing to that test but triage latency and rate-limit 429s.
//
// What makes it pass (and what each one prevents):
//   maxUnavailable: 0 + readinessProbe  capacity never dips; a new pod gets
//                                       traffic only once it can serve it
//   preStop sleep                       the pod stays up while endpoint removal
//                                       propagates to ingress-nginx
//   SIGTERM drain (app/main.py)         in-flight requests finish before exit
import http from 'k6/http'
import { check } from 'k6'

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8081'
const HOST_HEADER = __ENV.HOST_HEADER || ''
const params = HOST_HEADER ? { headers: { Host: HOST_HEADER } } : {}

export const options = {
  scenarios: {
    steady: {
      // Constant ARRIVAL rate, not constant VUs: if a pod stalls, requests
      // keep coming rather than politely waiting, as real users would.
      executor: 'constant-arrival-rate',
      rate: 20,
      timeUnit: '1s',
      duration: __ENV.DURATION || '150s',
      preAllocatedVUs: 20,
      maxVUs: 60,
    },
  },
  thresholds: {
    http_req_failed: ['rate==0'],
    checks: ['rate==1'],
  },
  summaryTrendStats: ['avg', 'p(95)', 'p(99)', 'max'],
}

const PATHS = ['/api/stats', '/api/complaints?page=1&page_size=10', '/']

export default function () {
  const path = PATHS[Math.floor(Math.random() * PATHS.length)]
  const res = http.get(`${BASE_URL}${path}`, params)
  check(res, { 'status is 200': (r) => r.status === 200 })
}
