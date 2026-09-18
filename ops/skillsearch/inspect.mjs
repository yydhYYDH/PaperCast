
import { readdirSync, statSync, readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
// 工作区根由脚本位置推导（ops/skillsearch/*.mjs → 上两级）
const WS = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const root = process.env.UPSTREAM_DEST || WS + "/reference/upstream";
function walk(dir, depth, out, base) {
  if (depth > 2) return;
  let ents = [];
  try { ents = readdirSync(dir); } catch { return; }
  for (const e of ents) {
    if (e === ".git") continue;
    const p = join(dir, e);
    let st; try { st = statSync(p); } catch { continue; }
    if (st.isDirectory()) { out.dirs.push(base + e + "/"); walk(p, depth + 1, out, base + e + "/"); }
    else { out.files.push([base + e, st.size]); }
  }
}
for (const repo of readdirSync(root)) {
  const dir = join(root, repo);
  if (!statSync(dir).isDirectory()) continue;
  const out = { dirs: [], files: [] };
  walk(dir, 0, out, "");
  console.log("\n########## " + repo + " ##########");
  console.log("DIRS: " + out.dirs.slice(0, 30).join(" | "));
  const exts = {};
  for (const [f, s] of out.files) { const e = extname(f) || "(none)"; exts[e] = (exts[e] || 0) + 1; }
  console.log("FILES(" + out.files.length + "): " + Object.entries(exts).sort((a,b)=>b[1]-a[1]).slice(0,12).map(([k,v])=>k+":"+v).join(" "));
  console.log("TOP FILES: " + out.files.filter(f=>!f[0].includes("/")).map(f=>f[0]).slice(0,18).join(", "));
  // frontmatter of every SKILL.md
  const skills = out.files.filter(([f]) => /SKILL\.md$/i.test(f)).slice(0, 8);
  for (const [f] of skills) {
    const txt = readFileSync(join(dir, f), "utf8").slice(0, 700);
    const name = (txt.match(/^name:\s*(.+)$/m) || [])[1] || "?";
    const descRaw = (txt.match(/description:\s*([\s\S]{0,300}?)\n[a-z]+:/i) || txt.match(/description:\s*(.+)/) || [])[1] || "";
    console.log("  SKILL " + f + " :: name=" + name + " :: " + descRaw.replace(/\s+/g, " ").slice(0, 200));
  }
}
