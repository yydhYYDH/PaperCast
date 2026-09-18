
import { readFileSync } from "node:fs";
const O = "/home/yydh/hack/var/sessions/";
function textOf(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((c) => c.text ?? "").join(" ");
  return "";
}
for (let i = 1; i <= 5; i++) {
  const lines = readFileSync(O + "sess-" + i + ".jsonl", "utf8").split("\n").filter(Boolean);
  console.log("\n############ sess-" + i + " ############");
  for (const l of lines) {
    let j; try { j = JSON.parse(l); } catch { continue; }
    if (j.type === "session/title") { console.log("  [TITLE] " + JSON.stringify(j.data).slice(0, 200)); continue; }
    if (j.type === "user/message") {
      const t = textOf(j.data?.content ?? j.data).replace(/\s+/g, " ").trim();
      if (t.length > 8) console.log("  U> " + t.slice(0, 260));
      continue;
    }
    if (j.type === "agent/inbox/spliced") {
      for (const ins of j.data?.inserted ?? []) {
        if (ins.source?.kind !== "user") continue;
        const t = textOf(ins.content).replace(/\s+/g, " ").trim();
        if (t.length > 8) console.log("  U* " + t.slice(0, 260));
      }
    }
  }
}
