
const repos = ["QuZhan51496/paper2anything","pickxiguapi/paper2x","flyanx/paper-to-wechat","kangw24/paper2content","Paper2Poster/Paper2Poster","HKUDS/Paper2Slides","showlab/Paper2Video","yhbcode000/paper-share-skills","op7418/guizang-social-card-skill","aiworkskills/wechat-article-skills","OpenDCAI/Paper2Any","icip-cas/PPTAgent"];
const H = { "Accept": "application/vnd.github+json", "User-Agent": "skill-search" };
for (const full of repos) {
  try {
    const r = await fetch("https://api.github.com/repos/" + full, { headers: H });
    if (!r.ok) { console.log("MISSING\t" + full + "\t" + r.status); continue; }
    const j = await r.json();
    console.log("OK\t" + full + "\tstars=" + j.stargazers_count + "\tsizeKB=" + j.size + "\tlicense=" + (j.license?.spdx_id ?? "-") + "\tpushed=" + (j.pushed_at ?? "").slice(0,10) + "\tlang=" + j.language);
  } catch (e) { console.log("ERR\t" + full + "\t" + e.message); }
  await new Promise(s => setTimeout(s, 400));
}
