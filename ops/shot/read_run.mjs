
import { readFileSync } from "node:fs";
const j = JSON.parse(readFileSync("/home/yydh/hack/apps/papercast-server/data/runs/run_87aeca6d7d33/run.json", "utf8"));
console.log("run:", j.id, "|", j.status, "|", j.title);
console.log("source:", JSON.stringify(j.source));
console.log("createdAt:", new Date(j.createdAt).toISOString(), "digest?", !!j.digest, "articles?", (j.articles ?? []).length);
for (const s of j.stages) {
  console.log("  " + s.id.padEnd(11) + s.status.padEnd(9) + Math.round(s.progress) + "%  arts=" + s.artifacts.length + "  gate=" + (s.gate ? (s.gate.resolved ?? "未放行") : "-") + "  checks=" + (s.checks ?? []).length + "  logs=" + s.logs.length);
  for (const a of s.artifacts.slice(0, 4)) console.log("        - " + a.label + "  [" + a.kind + "]  " + (a.url ?? a.path));
  for (const c of (s.checks ?? []).slice(0, 3)) console.log("        check: " + c.label + " = " + c.state + " (" + c.detail + ")");
}
