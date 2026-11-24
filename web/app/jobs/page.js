"use client";
import { useEffect, useState } from "react";
import { GATEWAY, KEYS, StatusBadge, authHeaders } from "../ui";

const H = authHeaders(KEYS.alice);

export default function Jobs() {
  const [n, setN] = useState(6);
  const [failing, setFailing] = useState(1);
  const [ids, setIds] = useState([]);       // jobs submitted from this page
  const [rows, setRows] = useState([]);
  const [dead, setDead] = useState([]);
  const [msg, setMsg] = useState("");

  async function submit() {
    setMsg("submitting...");
    const run = Date.now();
    const made = [];
    for (let i = 0; i < n; i++) {
      const doomed = i < failing;          // the first `failing` jobs always fail -> end in the DLQ
      const r = await fetch(`${GATEWAY}/jobs`, { method: "POST",
        headers: { ...H, "Idempotency-Key": `ui-${run}-${i}` },
        body: JSON.stringify({ prompt: `ui job ${i}`, fail_times: doomed ? 99 : 0 }) });
      if (r.status === 202 || r.status === 200) made.push((await r.json()).id);
    }
    setIds((old) => [...made, ...old]);
    setMsg(`submitted ${made.length} jobs (${failing} will fail 3 times; that takes ~35s because of the 5s + 30s retry delays)`);
  }

  useEffect(() => {      // poll every 1.5s
    const t = setInterval(async () => {
      try {
        const all = await (await fetch(`${GATEWAY}/jobs`, { headers: H })).json();
        setRows(all.filter((j) => ids.includes(j.id)));
        setDead(await (await fetch(`${GATEWAY}/jobs?status=DEAD`, { headers: H })).json());
      } catch { /* gateway not reachable; try again */ }
    }, 1500);
    return () => clearInterval(t);
  }, [ids]);

  return (
    <main className="page">
      <p className="eyebrow">Async jobs</p>
      <h1 style={{ fontSize: 44 }}>Queue some work.</h1>
      <p className="lead">Jobs are saved in Postgres, queued in RabbitMQ and run by a worker. Failed jobs retry after 5s, then 30s, then land in the dead-letter queue.</p>
      <div className="panel row">
        <label>Jobs <input type="number" min="1" max="50" value={n} onChange={(e) => setN(+e.target.value)} style={{ width: 70 }} /></label>
        <label>of which always fail <input type="number" min="0" max="50" value={failing} onChange={(e) => setFailing(+e.target.value)} style={{ width: 70 }} /></label>
        <button className="btn primary" onClick={submit}>Submit</button>
        <span className="muted">{msg}</span>
      </div>
      <table data-testid="jobs-table">
        <thead><tr><th>Job</th><th>Status</th><th>Attempts</th><th>Last error</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan="4" className="muted">No jobs yet. Submit some above.</td></tr>}
          {rows.map((j) => (
            <tr key={j.id}><td className="mono">{j.id.slice(0, 8)}</td><td><StatusBadge status={j.status} /></td>
              <td>{j.attempts}</td><td className="muted">{j.error || "-"}</td></tr>))}
        </tbody>
      </table>
      <section style={{ border: 0 }}>
        <p className="eyebrow">Dead-letter queue</p>
        <table>
          <thead><tr><th>Job</th><th>Attempts</th><th>Error</th></tr></thead>
          <tbody>
            {dead.length === 0 && <tr><td colSpan="3" className="muted">Empty.</td></tr>}
            {dead.slice(0, 10).map((j) => (<tr key={j.id}><td className="mono">{j.id.slice(0, 8)}</td><td>{j.attempts}</td><td className="muted">{j.error}</td></tr>))}
          </tbody>
        </table>
      </section>
    </main>);
}
