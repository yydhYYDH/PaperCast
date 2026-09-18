
const repos = [
  "nextlevelbuilder/ui-ux-pro-max-skill",
  "Leonxlnx/taste-skill",
  "zarazhangrui/frontend-slides",
  "ConardLi/garden-skills",
  "JimLiu/baoyu-design",
  "bergside/awesome-design-skills",
  "superdesigndev/superdesign-skill",
  "s0xDk/refactoring-ui-skill",
  "plugin87/ux-ui-agent-skills",
  "xiaopu-ai/web-design",
  "nateherkai/scroll-craft",
  "bitjaru/styleseed",
  "dominikmartn/hue",
  "Anthropic/skills",
  "wilwaldon/Claude-Code-Frontend-Design-Toolkit",
];
const H = { "Accept": "application/vnd.github+json", "User-Agent": "skill-search" };
for (const full of repos) {
  try {
    const r = await fetch("https://api.github.com/repos/" + full, { headers: H });
    if (!r.ok) { console.log("!! " + full + " -> " + r.status); await new Promise(s => setTimeout(s, 600)); continue; }
    const j = await r.json();
    const c = await fetch("https://api.github.com/repos/" + full + "/contents", { headers: H });
    let entries = [];
    if (c.ok) { const cj = await c.json(); entries = (Array.isArray(cj) ? cj : []).map(e => e.name + (e.type === "dir" ? "/" : "")); }
    console.log("### " + full + " | stars=" + j.stargazers_count + " | license=" + (j.license?.spdx_id ?? "-") + " | pushed=" + (j.pushed_at ?? "").slice(0, 10) + " | archived=" + j.archived);
    console.log("TOP: " + entries.join(" "));
    console.log("DESC: " + (j.description ?? ""));
  } catch (e) { console.log("!! " + full + " err " + e.message); }
  await new Promise(s => setTimeout(s, 700));
}
