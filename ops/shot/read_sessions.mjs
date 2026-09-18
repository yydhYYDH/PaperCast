
import { readFileSync } from "node:fs";
import { zstdDecompressSync } from "node:zlib";
const dir = process.env.HOME + "/.dsh/sessions/--home-yydh-hack--";
const sessions = ["session-9a2e73c4-97bf-4bc2-9357-5d16ed4abba4", "session-a1420e6d-6203-4fc2-aa53-b1f197a2241c", "session-b5026512-4b3d-49de-a6a8-f6c4b29dc59f"];
for (const s of sessions) {
  let text = "";
  try { text = zstdDecompressSync(readFileSync(dir + "/" + s + "/session.jsonl.zstd")).toString("utf8"); }
  catch (e) { console.log("!! " + s + " " + e.message); continue; }
  const lines = text.split("\n").filter(Boolean);
  console.log("\n########## " + s + " (" + lines.length + " lines) ##########");
  let shown = 0;
  for (const line of lines) {
    let j; try { j = JSON.parse(line); } catch { continue; }
    const role = j.role ?? j.message?.role ?? j.type;
    if (role !== "user" && role !== "human") continue;
    const content = j.content ?? j.message?.content;
    let txt = typeof content === "string" ? content : Array.isArray(content) ? content.map((c) => c.text ?? c.content ?? "").join(" ") : "";
    txt = txt.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    if (!txt || txt.length < 12) continue;
    console.log("USER> " + txt.slice(0, 700));
    if (++shown >= 8) break;
  }
}
