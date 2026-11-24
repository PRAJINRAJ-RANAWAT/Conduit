"use client";
import { useState } from "react";
import { Badge, GATEWAY, KEYS, authHeaders } from "../ui";

async function ask(key, prompt) {
  const r = await fetch(`${GATEWAY}/v1/chat/completions`, {
    method: "POST", headers: authHeaders(key),
    body: JSON.stringify({ max_tokens: 20, messages: [{ role: "user", content: prompt }] }) });
  const body = await r.json().catch(() => ({}));
  const h = (n) => r.headers.get(n);
  return { status: r.status, body, cache: h("x-conduit-cache"), provider: h("x-conduit-provider"),
           tokens: h("x-ratelimit-remaining-tokens"), retry: h("retry-after") };
}

export default function Playground() {
  const [tenant, setTenant] = useState("alice");
  const [prompt, setPrompt] = useState("Say hello to Conduit");
  const [res, setRes] = useState(null);
  const [strip, setStrip] = useState([]);
  const [busy, setBusy] = useState(false);

  async function send() {
    setBusy(true); setRes(await ask(KEYS[tenant], prompt)); setBusy(false);
  }

  async function burst() {   // 20 requests, one every 80 ms, so you can watch the limiter react
    setStrip([]); setBusy(true);
    const jobs = [];
    for (let i = 0; i < 20; i++) {
      // every 4th prompt repeats an earlier one, so some answers come from the cache
      jobs.push(ask(KEYS[tenant], `${prompt} #${i % 4 === 3 ? 0 : i}`).then(
        (r) => setStrip((s) => [...s, { i, ...r }])));
      await new Promise((ok) => setTimeout(ok, 80));
    }
    await Promise.all(jobs); setBusy(false);
  }

  const color = (r) => (r.status === 429 ? "var(--red)" : r.cache === "hit" ? "var(--amber)" : r.status === 200 ? "var(--green)" : "#888");
  return (
    <main className="page">
      <p className="eyebrow">Playground</p>
      <h1 style={{ fontSize: 44 }}>Send a request.</h1>
      <p className="lead">Pick a demo tenant. <b>bob</b> has a tiny quota (300 tokens/min), so he hits the rate limiter fast. <b>alice</b> has a big one.</p>
      <div className="panel">
        <div className="row" style={{ marginBottom: 12 }}>
          <label>Tenant key&nbsp;
            <select value={tenant} onChange={(e) => setTenant(e.target.value)}>
              <option value="alice">alice (key-alice, 60k tokens/min)</option>
              <option value="bob">bob (key-bob, 300 tokens/min)</option>
            </select></label>
        </div>
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={send} disabled={busy}>Send</button>
          <button className="btn" onClick={burst} disabled={busy}>Burst test (20 requests)</button>
        </div>
      </div>

      {res && <div className="panel" data-testid="result">
        <Badge color={res.status === 200 ? "green" : "red"}>HTTP {res.status}</Badge>
        {res.cache && <Badge color={res.cache === "hit" ? "amber" : "grey"}>cache: {res.cache}</Badge>}
        {res.provider && <Badge color="blue">provider: {res.provider}</Badge>}
        {res.tokens && <Badge>remaining tokens: {res.tokens}</Badge>}
        {res.retry && <Badge color="red">retry after {res.retry}s</Badge>}
        <div className="pre" style={{ marginTop: 12 }}>{res.body?.choices?.[0]?.message?.content || JSON.stringify(res.body)}</div>
      </div>}

      {strip.length > 0 && <div className="panel">
        <b>Burst results</b> <span className="muted">green = answered · amber = cache hit · red = 429 rate limited</span>
        <div className="strip" data-testid="strip">
          {strip.sort((a, b) => a.i - b.i).map((r) => (
            <div key={r.i} className="sq" style={{ background: color(r) }} title={`#${r.i}: HTTP ${r.status}`}>{r.status}</div>))}
        </div>
        <span className="muted">
          200: {strip.filter((r) => r.status === 200 && r.cache !== "hit").length} ·
          cache hits: {strip.filter((r) => r.cache === "hit").length} ·
          429: {strip.filter((r) => r.status === 429).length}
        </span>
      </div>}
    </main>);
}
