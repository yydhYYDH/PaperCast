// 打印一条 run 的阶段/产物/闸门概览。
// 用法：node ops/shot/read_run.mjs [runId 或 run.json 路径]   缺省看最新一条 run
import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const WS = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RUNS = process.env.PAPERCAST_DATA_DIR || WS + "/var/runs";

function newestRun() {
  const ds = readdirSync(RUNS).filter((d) => statSync(join(RUNS, d)).isDirectory());
  return ds.sort((a, b) => statSync(join(RUNS, b)).mtimeMs - statSync(join(RUNS, a)).mtimeMs)[0];
}

const arg = process.argv[2];
const file = !arg
  ? join(RUNS, newestRun(), "run.json")
  : arg.endsWith(".json")
    ? arg
    : join(RUNS, arg, "run.json");
if (!existsSync(file)) {
  console.error("找不到 run.json：" + file + "（用法：node ops/shot/read_run.mjs [runId]）");
  process.exit(1);
}
const j = JSON.parse(readFileSync(file, "utf8"));
console.log("run:", j.id, "|", j.status, "|", j.title);
console.log("source:", JSON.stringify(j.source));
console.log("createdAt:", new Date(j.createdAt).toISOString(), "digest?", !!j.digest, "articles?", (j.articles ?? []).length);
for (const s of j.stages) {
  console.log("  " + s.id.padEnd(11) + s.status.padEnd(9) + Math.round(s.progress) + "%  arts=" + s.artifacts.length + "  gate=" + (s.gate ? (s.gate.resolved ?? "未放行") : "-") + "  checks=" + (s.checks ?? []).length + "  logs=" + s.logs.length);
  for (const a of s.artifacts.slice(0, 4)) console.log("        - " + a.label + "  [" + a.kind + "]  " + (a.url ?? a.path));
  for (const c of (s.checks ?? []).slice(0, 3)) console.log("        check: " + c.label + " = " + c.state + " (" + c.detail + ")");
}
