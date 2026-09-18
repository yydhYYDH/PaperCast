
const queries = [
  "claude skill frontend",
  "claude skills ui design",
  "claude skill web design",
  "agent skills frontend",
  "claude skill css tailwind",
  "awesome claude skills",
  "claude skills marketplace",
  "topic:claude-skills",
];
const out = new Map();
async function gh(q, extra = "") {
  const url = "https://api.github.com/search/repositories?q=" + encodeURIComponent(q) + "&sort=stars&per_page=15" + extra;
  const r = await fetch(url, { headers: { "Accept": "application/vnd.github+json", "User-Agent": "skill-search" } });
  if (!r.ok) { console.error("ERR", q, r.status, (await r.text()).slice(0, 200)); return; }
  const j = await r.json();
  for (const it of j.items ?? []) {
    const prev = out.get(it.full_name);
    if (!prev || prev.stars < it.stargazers_count) {
      out.set(it.full_name, { full: it.full_name, stars: it.stargazers_count, desc: (it.description ?? "").replace(/\s+/g, " ").slice(0, 150), pushed: (it.pushed_at ?? "").slice(0, 10) });
    }
  }
}
for (const q of queries) { await gh(q); await new Promise(r => setTimeout(r, 1500)); }
const list = [...out.values()].sort((a, b) => b.stars - a.stars);
console.log("TOTAL", list.length);
for (const r of list.slice(0, 60)) console.log(r.stars + "\t" + r.full + "\t" + r.pushed + "\t" + r.desc);
