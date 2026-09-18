
const repos = ["nextlevelbuilder/ui-ux-pro-max-skill","Leonxlnx/taste-skill","superdesigndev/superdesign-skill","bitjaru/styleseed","s0xDk/refactoring-ui-skill","xiaopu-ai/web-design","ConardLi/garden-skills","anthropics/skills","zarazhangrui/frontend-slides","plugin87/ux-ui-agent-skills","bergside/awesome-design-skills","feitangyuan/motion-web"];
for (const full of repos) {
  let done = false;
  for (const br of ["main","master"]) {
    try {
      const r = await fetch("https://raw.githubusercontent.com/" + full + "/" + br + "/README.md");
      if (!r.ok) continue;
      const t = await r.text();
      const hits = t.split("\n").map(l => l.trim()).filter(l => /npx skills|skills add|plugin marketplace|marketplace add|\/plugin install/i.test(l) && l.length > 3 && l.length < 200).slice(0, 4);
      console.log("### " + full);
      for (const h of hits) console.log("   " + h);
      if (!hits.length) console.log("   (no explicit install line found; see README)");
      done = true; break;
    } catch (e) {}
  }
  if (!done) console.log("### " + full + " -> README fetch failed");
}
