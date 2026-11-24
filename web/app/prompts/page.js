"use client";
import { useEffect, useState } from "react";
import { Badge, GATEWAY, KEYS, authHeaders } from "../ui";

const H = authHeaders(KEYS.alice);

function Compare({ label, a, b, unit, lowerIsBetter }) {   // two plain bars: baseline vs best
  const max = Math.max(a, b) || 1;
  return (
    <div style={{ margin: "14px 0" }}>
      <b>{label}</b> <span className="muted">{lowerIsBetter ? "(lower is better)" : "(higher is better)"}</span>
      <div className="bar base" style={{ width: `${(a / max) * 100}%`, minWidth: 80, marginTop: 6 }}>baseline {a}{unit}</div>
      <div className="bar" style={{ width: `${(b / max) * 100}%`, minWidth: 80, marginTop: 4 }}>best {b}{unit}</div>
    </div>);
}

export default function Prompts() {
  const [versions, setVersions] = useState([]);
  const [eps, setEps] = useState(0.1);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { fetch(`${GATEWAY}/prompts/sentiment/versions`, { headers: H }).then((r) => r.json()).then(setVersions).catch(() => {}); }, []);

  async function run() {
    setBusy(true);
    const r = await fetch(`${GATEWAY}/prompts/optimise`, { method: "POST", headers: H, body: JSON.stringify({ name: "sentiment", epsilon: eps }) });
    setReport(await r.json()); setBusy(false);
  }

  return (
    <main className="page">
      <p className="eyebrow">Prompt optimisation</p>
      <h1 style={{ fontSize: 44 }}>Same task, fewer tokens.</h1>
      <p className="lead">Five immutable versions of one sentiment prompt. The optimiser scores each on a 20-example golden set and picks the cheapest one within epsilon of the baseline score.</p>
      <table>
        <thead><tr><th>Version</th><th>Words</th><th>Template</th></tr></thead>
        <tbody>{versions.map((v) => (
          <tr key={v.version}><td className="mono">v{v.version}</td><td>{v.template.split(/\s+/).length}</td><td className="muted mono" style={{ whiteSpace: "pre-wrap" }}>{v.template}</td></tr>))}</tbody>
      </table>
      <div className="panel row">
        <label>epsilon (allowed score drop) <input type="number" step="0.05" min="0" max="1" value={eps} onChange={(e) => setEps(+e.target.value)} style={{ width: 80 }} /></label>
        <button className="btn primary" onClick={run} disabled={busy}>{busy ? "Running..." : "Run optimiser"}</button>
      </div>
      {report && <div className="panel" data-testid="report">
        <Badge color="green">picked v{report.best.version}</Badge>
        <Badge color="amber">{report.cost_saved_pct}% cost saved</Badge>
        <Compare label="Score on golden set" a={report.baseline.score} b={report.best.score} unit="" />
        <Compare label="Average input tokens" a={report.baseline.avg_input_tokens} b={report.best.avg_input_tokens} unit="" lowerIsBetter />
        <Compare label="Cost per 1,000 calls (USD, assumed prices)" a={report.baseline.cost_per_1k_calls_usd} b={report.best.cost_per_1k_calls_usd} unit="" lowerIsBetter />
        <p className="muted">{report.notes}</p>
      </div>}
    </main>);
}
