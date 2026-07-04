"""Build the interactive seed-influence explorer for the hedonium experiment.

Reads lineage.json from each hedonium run, computes per-seed influence on every
generation (selection winner = 100% pass-through, crossover = 50% per parent,
summed over paths — the influence model documented in CLAUDE.md), and emits a
self-contained Plotly widget:

- Stacked-area chart of all 18 seeds' influence share over generations
- Model selector (buttons) for the 4 runs
- The hedonium-shockwave seed is always drawn on top with a fixed color so its
  fate is visible without interaction; hovering any band reveals seed details.

Usage:
    python3 widgets/build_hedonium_influence_explorer.py
"""
import json
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from analyze import compute_influence_forward, get_initial_essay_names  # noqa: E402

RUNS = [
    ("hedonium_runs/sonnet-5", "Claude Sonnet 5"),
    ("hedonium_runs/gpt-5.5", "GPT-5.5"),
    ("hedonium_runs/kimi-k2.5", "Kimi K2.5"),
    ("hedonium_runs/fable-5", "Claude Fable 5"),
]
OUT = os.path.join(BASE_DIR, "assets", "hedonium_influence_explorer.html")


def trajectories(run_dir):
    with open(os.path.join(run_dir, "lineage.json")) as f:
        lin = json.load(f)
    names = get_initial_essay_names(lin)
    num_gens = max(int(k) for k in lin)
    out = []
    for i, name in enumerate(names):
        inf = compute_influence_forward(lin, 0, i, num_gens)
        totals = [sum(inf[g][j] for j in range(len(lin[str(g)]))) / len(lin[str(g)])
                  for g in range(num_gens + 1)]
        out.append({"name": name, "traj": [round(t, 4) for t in totals]})
    return out


def main():
    data = {}
    for run_subdir, label in RUNS:
        run_dir = os.path.join(BASE_DIR, run_subdir)
        if not os.path.exists(os.path.join(run_dir, "lineage.json")):
            print(f"Skipping {label}: no lineage.json")
            continue
        data[label] = trajectories(run_dir)
    payload = json.dumps(data)

    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{margin:0;padding:12px 16px;font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;background:#fff;color:#222}
h1{font-size:16px;margin:0 0 2px}
p.sub{font-size:12.5px;color:#666;margin:0 0 10px;max-width:760px}
.btns{margin-bottom:8px}
button{border:1px solid #ccc;background:#f6f6f6;border-radius:6px;padding:6px 12px;margin-right:6px;font-size:13px;cursor:pointer}
button.active{background:#1f77b4;color:#fff;border-color:#1f77b4}
#chart{width:100%;height:520px}
</style></head><body>
<h1>Seed influence over generations</h1>
<p class="sub">Each band is one of the 18 seed essays; band height = share of the final population's ancestry attributable to that seed at each generation (selection = 100% pass-through to the winner, crossover = 50% per parent, summed over all paths). The <b>hedonium-shockwave</b> seed is the dark red band. Hover for exact values; click a model to switch runs.</p>
<div class="btns" id="btns"></div>
<div id="chart"></div>
<script>
const DATA = __PAYLOAD__;
const models = Object.keys(DATA);
const HEDONIUM = "hedonium-shockwave";
const palette = ["#8dd3c7","#ffffb3","#bebada","#fb8072","#80b1d3","#fdb462","#b3de69","#fccde5","#d9d9d9","#bc80bd","#ccebc5","#ffed6f","#a6cee3","#b2df8a","#fdbf6f","#cab2d6","#ffff99"];
function draw(model){
  const seeds = DATA[model];
  // order: hedonium last so it stacks on top
  const ordered = seeds.filter(s=>s.name!==HEDONIUM).concat(seeds.filter(s=>s.name===HEDONIUM));
  let ci=0;
  const traces = ordered.map(s=>{
    const isH = s.name===HEDONIUM;
    return {
      x: s.traj.map((_,i)=>i), y: s.traj, name: s.name,
      stackgroup:"one", mode:"lines",
      line:{width: isH?1.5:0.5, color: isH? "#b2182b" : palette[(ci++)%palette.length]},
      fillcolor: isH? "rgba(178,24,43,0.9)" : undefined,
      hovertemplate: s.name+": %{y:.1%} at gen %{x}<extra></extra>"
    };
  });
  Plotly.newPlot("chart", traces, {
    margin:{l:50,r:10,t:10,b:40},
    xaxis:{title:"generation", dtick:1},
    yaxis:{title:"influence share", tickformat:".0%", range:[0,1]},
    legend:{font:{size:9}}, hovermode:"closest"
  }, {displayModeBar:false, responsive:true});
}
const btns = document.getElementById("btns");
models.forEach((m,i)=>{
  const b=document.createElement("button"); b.textContent=m; if(i===0)b.classList.add("active");
  b.onclick=()=>{document.querySelectorAll("button").forEach(x=>x.classList.remove("active"));b.classList.add("active");draw(m);};
  btns.appendChild(b);
});
draw(models[0]);
</script></body></html>"""
    html = html.replace("__PAYLOAD__", payload)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(html)
    print(f"Wrote {OUT} ({os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    main()
