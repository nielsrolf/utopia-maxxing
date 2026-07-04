"""Build the final-generation essay reader widget for the hedonium experiment.

Embeds every final-generation essay from each of the 4 runs into a
self-contained HTML widget with:
- model tabs
- an essay list (with word count + per-essay hedonium-seed influence)
- a reading pane (first essay opens by default so the widget is informative
  without interaction)

Usage:
    python3 widgets/build_hedonium_essay_reader.py
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from analyze import compute_influence_forward, get_initial_essay_names  # noqa: E402

RUNS = [
    ("hedonium_runs/sonnet-5", "Claude Sonnet 5"),
    ("hedonium_runs/gpt-5.5", "GPT-5.5"),
    ("hedonium_runs/kimi-k2.5", "Kimi K2.5"),
    ("hedonium_runs/fable-5", "Claude Fable 5"),
]
OUT = os.path.join(BASE_DIR, "assets", "hedonium_essay_reader.html")


def collect(run_dir):
    with open(os.path.join(run_dir, "lineage.json")) as f:
        lin = json.load(f)
    names = get_initial_essay_names(lin)
    hed_idx = next(i for i, n in enumerate(names) if "hedonium" in n)
    num_gens = max(int(k) for k in lin)
    inf = compute_influence_forward(lin, 0, hed_idx, num_gens)
    gen_dir = os.path.join(run_dir, f"gen_{num_gens:03d}")
    essays = []
    for j, fname in enumerate(sorted(f for f in os.listdir(gen_dir) if f.endswith(".txt"))):
        text = open(os.path.join(gen_dir, fname)).read()
        essays.append({
            "id": fname.replace(".txt", ""),
            "words": len(text.split()),
            "hedonium": round(inf[num_gens][j], 3),
            "text": text,
        })
    return {"final_gen": num_gens, "essays": essays}


def main():
    data = {label: collect(os.path.join(BASE_DIR, sub)) for sub, label in RUNS
            if os.path.exists(os.path.join(BASE_DIR, sub, "lineage.json"))}
    payload = json.dumps(data)
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body{margin:0;padding:12px 16px;font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;background:#fff;color:#222}
h1{font-size:16px;margin:0 0 2px}
p.sub{font-size:12.5px;color:#666;margin:0 0 10px;max-width:760px}
.tabs button{border:1px solid #ccc;background:#f6f6f6;border-radius:6px;padding:6px 12px;margin:0 6px 8px 0;font-size:13px;cursor:pointer}
.tabs button.active{background:#1f77b4;color:#fff;border-color:#1f77b4}
.layout{display:flex;gap:14px;align-items:flex-start}
.list{flex:0 0 250px;max-height:520px;overflow-y:auto;border:1px solid #e2e2e2;border-radius:8px}
.item{padding:8px 10px;border-bottom:1px solid #eee;font-size:12.5px;cursor:pointer}
.item:hover{background:#f4f8fc}
.item.sel{background:#e3effa}
.item .meta{color:#888;font-size:11px}
.item .hed{color:#b2182b;font-weight:600}
.pane{flex:1;max-height:520px;overflow-y:auto;border:1px solid #e2e2e2;border-radius:8px;padding:14px 18px;font-size:13.5px;line-height:1.55;white-space:pre-wrap}
</style></head><body>
<h1>Read the evolved utopias (final generation)</h1>
<p class="sub">All 18 essays from each model's final generation. The red percentage is the fraction of that essay's ancestry that traces back to the one-sentence <b>hedonium-shockwave</b> seed. Click an essay to read it in full.</p>
<div class="tabs" id="tabs"></div>
<div class="layout"><div class="list" id="list"></div><div class="pane" id="pane"></div></div>
<script>
const DATA = __PAYLOAD__;
const models = Object.keys(DATA);
let cur = models[0];
function renderList(){
  const d = DATA[cur];
  const list = document.getElementById("list");
  list.innerHTML = "";
  d.essays.forEach((e,i)=>{
    const div=document.createElement("div");
    div.className="item"+(i===0?" sel":"");
    div.innerHTML = `<b>Essay ${e.id}</b> <span class="meta">· ${e.words} words · gen ${d.final_gen}</span><br><span class="meta">hedonium ancestry: <span class="hed">${(e.hedonium*100).toFixed(1)}%</span></span>`;
    div.onclick=()=>{document.querySelectorAll(".item").forEach(x=>x.classList.remove("sel"));div.classList.add("sel");document.getElementById("pane").textContent=e.text;};
    list.appendChild(div);
  });
  document.getElementById("pane").textContent = d.essays[0].text;
}
const tabs=document.getElementById("tabs");
models.forEach((m,i)=>{
  const b=document.createElement("button"); b.textContent=m; if(i===0)b.classList.add("active");
  b.onclick=()=>{cur=m;document.querySelectorAll(".tabs button").forEach(x=>x.classList.remove("active"));b.classList.add("active");renderList();};
  tabs.appendChild(b);
});
renderList();
</script></body></html>"""
    html = html.replace("__PAYLOAD__", payload)
    with open(OUT, "w") as f:
        f.write(html)
    print(f"Wrote {OUT} ({os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    main()
