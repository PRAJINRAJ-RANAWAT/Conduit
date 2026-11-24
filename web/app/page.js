import { readBenchStats } from "./stats";

export const dynamic = "force-dynamic";   // read the stats file on every request

const NOT = "not measured yet";
const GITHUB = process.env.NEXT_PUBLIC_GITHUB_URL || "#";

function Stat({ n, label }) {
  return <div className="stat"><div className="n">{n}</div><div className="l">{label}</div></div>;
}

function Flow() {  // client -> gateway -> limiter -> cache -> LLM, plus the async path
  const box = (x, y, w, t, sub, hot) => (
    <g key={t}><rect x={x} y={y} width={w} height="58" rx="12" fill={hot ? "#E8501A" : "#fff"} stroke="#E4E0D6" />
      <text x={x + w / 2} y={y + 25} textAnchor="middle" fontWeight="700" fontSize="14" fill={hot ? "#fff" : "#1B1A17"}>{t}</text>
      <text x={x + w / 2} y={y + 44} textAnchor="middle" fontSize="11" fill={hot ? "#fff" : "#6F6B62"}>{sub}</text></g>);
  const arrow = (x1, y1, x2, y2) => <line key={`${x1}${y1}${x2}${y2}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#6F6B62" strokeWidth="2" markerEnd="url(#a)" />;
  return (
    <svg viewBox="0 0 980 300" width="100%" role="img" aria-label="Request flow diagram">
      <defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#6F6B62" /></marker></defs>
      <text x="0" y="22" fontSize="12" fontWeight="700" fill="#E8501A" letterSpacing="1.5">SYNC PATH</text>
      {box(0, 36, 120, "Client", "your app")}{box(170, 36, 130, "Gateway", "auth by API key", true)}
      {box(350, 36, 150, "Rate limiter", "Redis · Lua token bucket")}{box(550, 36, 130, "Cache", "Redis")}
      {box(730, 36, 140, "Mock LLM", "provider A → B")}
      {arrow(120, 65, 170, 65)}{arrow(300, 65, 350, 65)}{arrow(500, 65, 550, 65)}{arrow(680, 65, 730, 65)}
      <text x="0" y="170" fontSize="12" fontWeight="700" fill="#E8501A" letterSpacing="1.5">ASYNC PATH (POST /jobs)</text>
      {box(170, 184, 130, "Postgres", "job saved first")}{box(350, 184, 150, "RabbitMQ", "persistent + confirms")}
      {box(550, 184, 130, "Worker", "ack after save")}{box(730, 184, 140, "DLQ", "after 3 failures")}
      {arrow(235, 94, 235, 184)}{arrow(300, 213, 350, 213)}{arrow(500, 213, 550, 213)}{arrow(680, 213, 730, 213)}
      <text x="510" y="285" fontSize="11" fill="#6F6B62">failed jobs wait in delay queues (5s, 30s) and come back to the worker</text>
    </svg>);
}

const Row = ({ what, direct, conduit }) => (
  <tr><td>{what}</td><td className="c"><span className={direct ? "yes" : "no"}>{direct ? "✓" : "✕"}</span></td>
    <td className="c"><span className={conduit ? "yes" : "no"}>{conduit ? "✓" : "✕"}</span></td></tr>);

export default function Home() {
  const s = readBenchStats();
  return (
    <main>
      <div className="hero">
        <p className="eyebrow">Rate-limited · Cached · Queued</p>
        <h1>One gateway between your apps and every LLM.</h1>
        <p className="lead">Conduit checks who is calling, how much they may spend, whether we already know the answer, and which provider is healthy, before a single token is bought.</p>
        <div className="row" style={{ marginTop: 28 }}>
          <a className="btn primary" href="/playground">Try the playground</a>
          <a className="btn" href={GITHUB}>GitHub</a>
        </div>
        <div className="stats">
          <Stat n={s ? `${s.capacity_p99_ms} ms` : NOT} label="p99 latency, 50 concurrent users (k6, saved run)" />
          <Stat n={s ? `${s.capacity_rps} req/s` : NOT} label="throughput on one laptop, mock LLM with 0.2s delay" />
          <Stat n={s ? `${s.jobs_lost} of ${s.jobs_submitted}` : NOT} label="jobs lost during the load test" />
        </div>
      </div>

      <section id="flow">
        <p className="eyebrow">How a request flows</p>
        <h2>Every call takes the same short road.</h2>
        <Flow />
      </section>

      <section>
        <p className="eyebrow">What it does</p>
        <h2>Four jobs, one service.</h2>
        <div className="cards">
          <div className="card"><div className="num">1</div><h3>Limit</h3><p>Each tenant gets a token bucket in Redis. We reserve tokens before the call and settle with real usage after.</p></div>
          <div className="card"><div className="num">2</div><h3>Cache</h3><p>Same question twice? Answer from Redis. No provider call, no cost.</p></div>
          <div className="card"><div className="num">3</div><h3>Queue</h3><p>Bulk work goes through RabbitMQ with retries, a dead-letter queue and no duplicate runs.</p></div>
          <div className="card"><div className="num">4</div><h3>Optimise prompts</h3><p>Score prompt versions on a golden set and pick the cheapest one that is still good enough.</p></div>
        </div>
      </section>

      <section>
        <p className="eyebrow">Why bother</p>
        <h2>Direct vs through Conduit.</h2>
        <table style={{ marginTop: 20 }}>
          <thead><tr><th>Feature</th><th className="c">Calling an LLM directly</th><th className="c">Through Conduit</th></tr></thead>
          <tbody>
            <Row what="Per-tenant rate limits" direct={false} conduit />
            <Row what="Response caching" direct={false} conduit />
            <Row what="Retries with backoff + dead-letter queue" direct={false} conduit />
            <Row what="Usage and cost tracking" direct={false} conduit />
            <Row what="Failover to a second provider" direct={false} conduit />
            <Row what="Works with one provider" direct conduit />
          </tbody>
        </table>
      </section>

      <section>
        <p className="eyebrow">FAQ</p>
        <h2>Short answers.</h2>
        <details><summary>Does this call real AI models?</summary><p>No. Everything runs against a mock LLM so tests and load runs cost nothing. Quality scores come from a deterministic simulator.</p></details>
        <details><summary>Where do the numbers on this page come from?</summary><p>From <code className="mono">bench/results/</code>, written by the k6 run. If there is no run yet, the page says &quot;not measured yet&quot;.</p></details>
        <details><summary>What happens if Redis or RabbitMQ goes down?</summary><p>See <code className="mono">chaos/RESULTS.md</code>: chat returns a fast 503 without Redis; jobs return 503 without RabbitMQ and are accepted again on retry.</p></details>
      </section>
    </main>);
}
