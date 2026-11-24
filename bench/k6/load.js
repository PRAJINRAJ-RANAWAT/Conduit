// Load test of the full stack: gateway -> Redis (limiter, cache) -> mock LLM -> Postgres (usage),
// and POST /jobs -> Postgres + RabbitMQ -> worker. Three things run at once:
//   capacity : 50 virtual users on the "loadtest" tenant (huge quota) -> measures speed
//   jobs     : 20 job submissions per second
//   limited  : 3 users on the tiny-quota "bob" tenant -> proves the limiter says 429 under load
import http from 'k6/http';
import { Rate } from 'k6/metrics';

const BASE = __ENV.BASE || 'http://host.docker.internal:8080';
http.setResponseCallback(http.expectedStatuses(200, 202, 429));   // 429 is a valid answer, not an error
const got429 = new Rate('got_429');
const cacheHit = new Rate('cache_hit');

export const options = {
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],   // k6 skips p99 by default
  scenarios: {
    capacity: { executor: 'ramping-vus', exec: 'chat', startVUs: 0,
      stages: [{ duration: '10s', target: 50 }, { duration: '40s', target: 50 }, { duration: '5s', target: 0 }] },
    jobs: { executor: 'constant-arrival-rate', exec: 'job', rate: 20, timeUnit: '1s',
      duration: '55s', preAllocatedVUs: 10 },
    limited: { executor: 'constant-vus', exec: 'limited', vus: 3, duration: '55s' },
  },
  // Thresholds that always pass: they only make k6 report per-scenario percentiles in the summary.
  thresholds: {
    'http_req_duration{scenario:capacity}': ['p(50)>=0'],
    'http_req_duration{scenario:jobs}': ['p(50)>=0'],
    'http_req_duration{scenario:limited}': ['p(50)>=0'],
    'http_req_failed{scenario:capacity}': ['rate>=0'],
    'got_429{scenario:capacity}': ['rate>=0'],
    'got_429{scenario:limited}': ['rate>=0'],
    'cache_hit{scenario:capacity}': ['rate>=0'],
    'http_reqs{scenario:capacity}': ['count>=0'],
    'http_reqs{scenario:jobs}': ['count>=0'],
    'http_reqs{scenario:limited}': ['count>=0'],
  },
};

const json = (key) => ({ headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' } });
const chatBody = (text) => JSON.stringify({ max_tokens: 20, messages: [{ role: 'user', content: text }] });

export function chat() {
  // 70% brand-new questions (cache miss), 30% from a pool of 20 repeated ones (cache hit)
  const text = Math.random() < 0.3 ? `repeat-${Math.floor(Math.random() * 20)}` : `new-${__VU}-${__ITER}`;
  const r = http.post(`${BASE}/v1/chat/completions`, chatBody(text), json('key-load'));
  got429.add(r.status === 429);
  cacheHit.add(r.headers['X-Conduit-Cache'] === 'hit');
}

export function job() {
  const p = json('key-load');
  p.headers['Idempotency-Key'] = `k6-${__ENV.RUN}-${__VU}-${__ITER}`;
  http.post(`${BASE}/jobs`, JSON.stringify({ prompt: 'load test job' }), p);
}

export function limited() {
  const r = http.post(`${BASE}/v1/chat/completions`, chatBody(`bob-${__VU}-${__ITER}`), json('key-bob'));
  got429.add(r.status === 429);
}

export function handleSummary(data) {
  return { [`/bench/results/${__ENV.LABEL}/summary.json`]: JSON.stringify(data, null, 1) };
}
