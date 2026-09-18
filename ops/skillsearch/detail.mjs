
const H = { "Accept": "application/vnd.github+json", "User-Agent": "skill-search" };
async function ls(full, sub) {
  const r = await fetch("https://api.github.com/repos/" + full + "/contents/" + sub, { headers: H });
  if (!r.ok) return "!!" + r.status;
  const j = await r.json();
  return (Array.isArray(j) ? j : []).map(e => e.name.replace(/\.md$/, "")).join(", ");
}
const targets = [
  ["Leonxlnx/taste-skill", "skills"],
  ["superdesigndev/superdesign-skill", "skills"],
  ["ConardLi/garden-skills", "skills"],
  ["JimLiu/baoyu-design", "skills"],
  ["nextlevelbuilder/ui-ux-pro-max-skill", "stack"],
  ["bitjaru/styleseed", "skills"],
  ["bergside/awesome-design-skills", "skills"],
  ["plugin87/ux-ui-agent-skills", "components"],
  ["anthropics/skills", ""],
  ["anthropics/skills", "skills"],
];
for (const [full, sub] of targets) {
  console.log("### " + full + (sub ? " /" + sub : "") + " => " + (await ls(full, sub)).slice(0, 900));
  await new Promise(s => setTimeout(s, 600));
}
// extra topic searches for other frontend angles
const qs = ["claude skill shadcn", "claude skill react component", "claude skill figma", "claude skill three.js webgl", "claude skill tailwind", "claude skill design system", "claude skill landing page", "claude skill accessibility wcag"];
const found = new Map();
for (const q of qs) {
  const r = await fetch("https://api.github.com/search/repositories?q=" + encodeURIComponent(q) + "&sort=stars&per_page=8", { headers: H });
  if (r.ok) { const j = await r.json(); for (const it of j.items ?? []) { if (!found.has(it.full_name)) found.set(it.full_name, it.stargazers_count + "\t" + it.full_name + "\t" + (it.description ?? "").replace(/\s+/g, " ").slice(0, 120)); } }
  await new Promise(s => setTimeout(s, 1200));
}
console.log("=== EXTRA ===");
for (const v of [...found.values()].sort((a, b) => parseInt(b) - parseInt(a)).slice(0, 30)) console.log(v);
