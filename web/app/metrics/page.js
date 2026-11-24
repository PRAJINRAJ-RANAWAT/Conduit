"use client";
import { useEffect, useState } from "react";
import { GATEWAY } from "../ui";

const Card = ({ label, value, sub }) => (
  <div className="stat"><div className="n">{value}</div><div className="l">{label}{sub && <><br /><span className="mono">{sub}</span></>}</div></div>);

export default function Metrics() {
  const [s, setS] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const load = () => fetch(`${GATEWAY}/stats`).then((r) => r.json()).then((d) => { setS(d); setErr(""); }).catch(() => setErr("gateway not reachable"));
    load(); const t = setInterval(load, 2000); return () => clearInterval(t);
  }, []);

  const hits = s?.cache_hit || 0, misses = s?.cache_miss || 0;
  const ratio = hits + misses ? `${Math.round((100 * hits) / (hits + misses))}%` : "-";
  return (
    <main className="page">
      <p className="eyebrow">Metrics</p>
      <h1 style={{ fontSize: 44 }}>Live counters.</h1>
      <p className="lead">Real counters from the running gateway (Redis, RabbitMQ and Postgres). They refresh every 2 seconds.</p>
      {err && <p className="no">{err}</p>}
      {s && <div className="grid5" data-testid="metrics">
        <Card label="chat requests" value={s.requests || 0} />
        <Card label="cache hit ratio" value={ratio} sub={`${hits} hits / ${misses} misses`} />
        <Card label="429 responses" value={s.rate_limited || 0} />
        <Card label="queue depth" value={s.queue_depth} sub="jobs waiting in RabbitMQ" />
        <Card label="DLQ size" value={s.dlq_size} sub="dead jobs" />
        <Card label="jobs in flight" value={s.inflight} sub="dispatched + running + retrying" />
        <Card label="queued per tenant" value={Object.values(s.queued_by_tenant).reduce((a, b) => a + b, 0)}
              sub={Object.entries(s.queued_by_tenant).map(([k, v]) => `${k}:${v}`).join(" ") || "none waiting"} />
        <Card label="time to start (p95, last 5 min)" value={s.time_to_start_ms_last_5min.p95 == null ? "-" : `${Math.round(s.time_to_start_ms_last_5min.p95)} ms`}
              sub={`p50 ${s.time_to_start_ms_last_5min.p50 == null ? "-" : Math.round(s.time_to_start_ms_last_5min.p50)} ms · ${s.time_to_start_ms_last_5min.n} jobs`} />
        <Card label="active dispatcher" value={s.dispatcher_leader ? s.dispatcher_leader.slice(0, 8) : "none"} sub="holds the Postgres advisory lock" />
        <Card label="provider A circuit" value={s.circuits.A} />
        <Card label="provider B circuit" value={s.circuits.B} />
        <Card label="jobs by status" value={Object.values(s.jobs).reduce((a, b) => a + b, 0)} sub={Object.entries(s.jobs).map(([k, v]) => `${k}:${v}`).join(" ")} />
      </div>}
    </main>);
}
