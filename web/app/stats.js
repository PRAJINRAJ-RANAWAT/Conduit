// Server-side: reads the saved benchmark file. Never invents numbers.
import fs from "fs";
import path from "path";

export function readBenchStats() {
  const dir = process.env.BENCH_DIR || path.join(process.cwd(), "..", "bench", "results");
  try { return JSON.parse(fs.readFileSync(path.join(dir, "stats.json"), "utf8")); }
  catch { return null; }   // no benchmark run yet
}
