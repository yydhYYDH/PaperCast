
import { readdirSync, statSync, readFileSync, existsSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const WS = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const UP = process.env.UPSTREAM_DEST || WS + "/reference/upstream";
function list(d, depth = 2, base = "") {
  const out = [];
  let es = []; try { es = readdirSync(d); } catch { return out; }
  for (const e of es) {
    if (e === ".git" || e === "node_modules") continue;
    const p = join(d, e);
    if (statSync(p).isDirectory()) { out.push(base + e + "/"); if (depth > 0) out.push(...list(p, depth - 1, base + e + "/")); }
    else out.push(base + e);
  }
  return out;
}
console.log("===== paper2anything skills =====");
console.log(list(UP + "/paper2anything/skills", 1).slice(0, 60).join("\n"));
console.log("\n===== paper2x =====");
console.log(list(UP + "/paper2x", 2).slice(0, 60).join("\n"));
const rd = UP + "/paper2anything/README.md";
if (existsSync(rd)) {
  const t = readFileSync(rd, "utf8");
  const i = t.indexOf("| Skill |");
  console.log("\n===== paper2anything skill table =====\n" + t.slice(i, i + 1800));
  const u = t.indexOf("## Usage");
  console.log("\n===== usage =====\n" + t.slice(u, u + 1500));
}
