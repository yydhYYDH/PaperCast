
import { readFileSync } from "node:fs";
import { zstdDecompressSync } from "node:zlib";
const dir = process.env.HOME + "/.dsh/sessions/--home-yydh-hack--";
const s = "session-b5026512-4b3d-49de-a6a8-f6c4b29dc59f";
const text = zstdDecompressSync(readFileSync(dir + "/" + s + "/session.jsonl.zstd")).toString("utf8");
console.log("len", text.length);
console.log("=== first 1200 ===");
console.log(text.slice(0, 1200));
console.log("=== keys of first json ===");
try { const j = JSON.parse(text.split("\n")[0]); console.log(Object.keys(j)); } catch (e) { console.log("parse fail", e.message); }
