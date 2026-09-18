
const H = { "Accept": "application/vnd.github+json", "User-Agent": "r" };
async function readme(full) {
  for (const p of ["README.md", "README_EN.md"]) {
    const r = await fetch("https://api.github.com/repos/" + full + "/contents/" + p, { headers: H });
    if (!r.ok) continue;
    const j = await r.json();
    return Buffer.from(j.content, "base64").toString("utf8");
  }
  return "";
}
for (const full of ["Paper2Poster/Paper2Poster", "showlab/Paper2Video", "QuZhan51496/paper2anything", "HKUDS/Paper2Slides"]) {
  const t = await readme(full);
  console.log("\n########## " + full + " (" + t.length + " chars) ##########");
  const lines = t.split("\n");
  const keep = lines.filter(l => /^#{1,3} |^\s*[-*]\s|\|\s|python |pip |--|input|output|\.pptx|\.mp4|\.pdf|CLI|API|stage/i.test(l)).slice(0, 45);
  console.log(keep.join("\n").slice(0, 2600));
  await new Promise(s => setTimeout(s, 400));
}
