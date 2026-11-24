import "./globals.css";

export const metadata = { title: "Conduit - LLM traffic control", description: "Rate-limited, cached, queued LLM gateway" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <nav><div className="in">
          <a className="logo" href="/">Con<b>duit</b></a>
          <div className="links">
            <a href="/#flow">How it works</a><a href="/playground">Playground</a><a href="/jobs">Jobs</a>
            <a href="/prompts">Prompts</a><a href="/metrics">Metrics</a>
          </div>
          <a href="/playground" className="muted" style={{ textDecoration: "none" }}>Sign in</a>
          <a className="btn primary" href="/playground">Try the playground</a>
        </div></nav>
        {children}
        <footer>Built by Prajinraj Ranawat · a portfolio project · every number on this site comes from a saved run</footer>
      </body>
    </html>
  );
}
