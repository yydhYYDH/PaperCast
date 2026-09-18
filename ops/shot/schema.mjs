
import { readFileSync } from "node:fs";
const O = "/home/yydh/hack/var/sessions/";
for (let i = 1; i <= 5; i++) {
  const lines = readFileSync(O + "sess-" + i + ".jsonl", "utf8").split("\n").filter(Boolean);
  const types = {};
  for (const l of lines) { try { const j = JSON.parse(l); const k = j.type + ":" + (j.role ?? j.message?.role ?? ""); types[k] = (types[k] ?? 0) + 1; } catch {} }
  console.log("\n##### sess-" + i + " (" + lines.length + " lines) #####");
  console.log("types: " + JSON.stringify(types));
  if (i === 1) {
    for (const l of lines.slice(0, 5)) { try { const j = JSON.parse(l); console.log("sample: " + JSON.stringify(j).slice(0, 500)); } catch {} }
  }
}
