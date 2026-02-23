"""Generate a standalone HTML visualization of lineage.json for a run."""

import json
import os
import html as html_mod


def generate_lineage_html(run_dir: str):
    """Read lineage.json, metadata.json, and essay texts from run_dir, write lineage.html."""
    lineage_path = os.path.join(run_dir, "lineage.json")
    metadata_path = os.path.join(run_dir, "metadata.json")

    with open(lineage_path) as f:
        lineage = json.load(f)
    with open(metadata_path) as f:
        metadata = json.load(f)

    nodes = []
    edges = []

    def nid(gen: int, idx: int) -> str:
        return f"g{gen}_{idx}"

    num_gens = max(int(k) for k in lineage) + 1

    # Load all essay texts and summaries
    texts = {}  # nid -> text
    summaries = {}  # nid -> summary

    for gen_str, entries in lineage.items():
        gen = int(gen_str)
        gen_dir = os.path.join(run_dir, f"gen_{gen:03d}")
        for idx, entry in enumerate(entries):
            op = entry["op"]
            label = entry.get("source", "") or ""
            if label:
                label = os.path.splitext(label)[0][:30]
            nodes.append({
                "id": nid(gen, idx),
                "gen": gen,
                "idx": idx,
                "label": label,
                "op": op,
            })

            # Load text
            txt_path = os.path.join(gen_dir, f"{idx:04d}.txt")
            if os.path.exists(txt_path):
                with open(txt_path) as f:
                    texts[nid(gen, idx)] = f.read()

            # Load summary if exists
            summary_path = os.path.join(gen_dir, f"{idx:04d}.summary.txt")
            if os.path.exists(summary_path):
                with open(summary_path) as f:
                    summaries[nid(gen, idx)] = f.read()

            if op == "selection":
                winner = entry["winner"]
                for p in entry["parents"]:
                    edges.append({
                        "source": nid(gen - 1, p),
                        "target": nid(gen, idx),
                        "type": "selected" if p == winner else "eliminated",
                    })
            elif op == "crossover":
                for p in entry["parents"]:
                    edges.append({
                        "source": nid(gen - 1, p),
                        "target": nid(gen, idx),
                        "type": "crossover",
                    })

    run_name = os.path.basename(run_dir)
    model = metadata.get("model", "unknown")

    html = _build_html(nodes, edges, texts, summaries, run_name, model, num_gens)
    out_path = os.path.join(run_dir, "lineage.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Lineage visualization saved to {out_path}")


def _build_html(nodes, edges, texts, summaries, run_name, model, num_gens):
    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)
    texts_json = json.dumps(texts)
    summaries_json = json.dumps(summaries)
    has_summaries = "true" if summaries else "false"

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lineage — {html_mod.escape(run_name)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0d1117; color: #c9d1d9; }}
  #header {{ position: sticky; top: 0; z-index: 10; background: #161b22; border-bottom: 1px solid #30363d; padding: 12px 20px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
  #header h1 {{ font-size: 16px; font-weight: 600; }}
  #header .meta {{ font-size: 13px; color: #8b949e; }}
  #controls {{ display: flex; gap: 8px; align-items: center; }}
  .sep {{ width: 1px; height: 20px; background: #30363d; margin: 0 4px; }}
  #filters {{ display: flex; gap: 8px; margin-left: auto; font-size: 12px; align-items: center; }}
  .filter-btn {{ display: flex; align-items: center; gap: 5px; background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 4px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; user-select: none; }}
  .filter-btn:hover {{ background: #30363d; }}
  .filter-btn.active {{ border-color: #58a6ff; }}
  .filter-btn.off {{ opacity: 0.4; }}
  .filter-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  .filter-line {{ width: 14px; height: 2px; }}
  .toggle-btn {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 4px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; }}
  .toggle-btn:hover {{ background: #30363d; }}
  .toggle-btn.active {{ background: #1f6feb; border-color: #1f6feb; }}
  #graph-container {{ overflow-x: auto; overflow-y: hidden; }}
  svg {{ display: block; }}
  .node {{ cursor: pointer; }}
  .node circle {{ stroke-width: 1.5; transition: r 0.15s, opacity 0.15s; }}
  .node.in-lineage circle {{ stroke-width: 3; }}
  .node.selected-node circle {{ r: 18; stroke-width: 3; }}
  .node text {{ font-size: 11px; fill: #c9d1d9; pointer-events: none; transition: opacity 0.15s; }}
  .node.dimmed circle {{ opacity: 0.15; }}
  .node.dimmed text {{ opacity: 0.15; }}
  .edge {{ fill: none; stroke-width: 1.2; transition: opacity 0.15s; }}
  .edge.selected {{ stroke: #58a6ff; }}
  .edge.eliminated {{ stroke: #f8514966; stroke-dasharray: 4 3; }}
  .edge.crossover {{ stroke: #3fb95088; }}
  .edge.hidden-type {{ display: none !important; }}
  .edge.in-lineage {{ stroke-width: 3 !important; opacity: 1 !important; }}
  .edge.in-lineage.selected {{ stroke: #58a6ff; }}
  .edge.in-lineage.eliminated {{ stroke: #f85149; }}
  .edge.in-lineage.crossover {{ stroke: #3fb950; }}
  .edge.dimmed {{ opacity: 0.07 !important; }}
  .gen-label {{ font-size: 13px; fill: #8b949e; font-weight: 600; }}
  .tooltip {{ position: fixed; background: #1c2129; border: 1px solid #30363d; border-radius: 6px; padding: 8px 12px; font-size: 12px; pointer-events: none; display: none; z-index: 20; max-width: 280px; }}
  .tooltip .tt-title {{ font-weight: 600; margin-bottom: 4px; }}
  .tooltip .tt-dim {{ color: #8b949e; }}
  #text-panel {{ border-top: 1px solid #30363d; background: #161b22; display: none; }}
  #text-panel-header {{ display: flex; align-items: center; gap: 12px; padding: 12px 20px; border-bottom: 1px solid #30363d; }}
  #text-panel-header h2 {{ font-size: 14px; font-weight: 600; }}
  #text-panel-header .influence-badge {{ font-size: 12px; color: #8b949e; font-weight: 400; }}
  #text-panel-header .close-btn {{ margin-left: auto; background: none; border: none; color: #8b949e; font-size: 18px; cursor: pointer; padding: 0 6px; }}
  #text-panel-header .close-btn:hover {{ color: #c9d1d9; }}
  #text-content {{ padding: 20px; max-height: 60vh; overflow-y: auto; white-space: pre-wrap; font-size: 14px; line-height: 1.7; color: #c9d1d9; }}
</style>
</head>
<body>
<div id="header">
  <h1>Lineage</h1>
  <span class="meta">{html_mod.escape(run_name)} &middot; {html_mod.escape(model)} &middot; {num_gens} generations</span>
  <div id="controls">
    <button class="toggle-btn active" id="btn-summary" onclick="setMode('summary')">Summary</button>
    <button class="toggle-btn" id="btn-full" onclick="setMode('full')">Full Text</button>
    <div class="sep"></div>
    <button class="toggle-btn active" id="btn-influence" onclick="toggleInfluence()">Influence</button>
  </div>
  <div id="filters">
    <button class="filter-btn active" id="filter-selected" onclick="toggleFilter('selected')">
      <div class="filter-dot" style="background:#58a6ff"></div> Winner
    </button>
    <button class="filter-btn active" id="filter-eliminated" onclick="toggleFilter('eliminated')">
      <div class="filter-line" style="background:#f85149"></div> Eliminated
    </button>
    <button class="filter-btn active" id="filter-crossover" onclick="toggleFilter('crossover')">
      <div class="filter-dot" style="background:#3fb950"></div> Crossover
    </button>
    <div class="sep"></div>
    <div class="filter-btn" style="cursor:default"><div class="filter-dot" style="background:#f0883e"></div> Initial</div>
  </div>
</div>
<div id="tooltip" class="tooltip"></div>
<div id="graph-container"><svg id="canvas"></svg></div>
<div id="text-panel">
  <div id="text-panel-header">
    <h2 id="text-panel-title"></h2>
    <span class="influence-badge" id="influence-badge"></span>
    <button class="close-btn" onclick="deselectNode()">&times;</button>
  </div>
  <div id="text-content"></div>
</div>
<script>
const nodes = {nodes_json};
const edges = {edges_json};
const texts = {texts_json};
const summaries = {summaries_json};
const hasSummaries = {has_summaries};
const numGens = {num_gens};

let displayMode = hasSummaries ? "summary" : "full";
let selectedNodeId = null;
let influenceMode = true;
const visibleTypes = {{ selected: true, eliminated: true, crossover: true }};

// Build adjacency maps
// For lineage tracing (only winning/crossover)
const winChildrenOf = {{}};
const winParentsOf = {{}};
// Full adjacency with edge type info for influence
const edgesFrom = {{}};  // source -> [{{target, type}}]
const edgesTo = {{}};    // target -> [{{source, type}}]
edges.forEach(e => {{
  if (!edgesFrom[e.source]) edgesFrom[e.source] = [];
  edgesFrom[e.source].push({{ target: e.target, type: e.type }});
  if (!edgesTo[e.target]) edgesTo[e.target] = [];
  edgesTo[e.target].push({{ source: e.source, type: e.type }});
  if (e.type === "eliminated") return;
  if (!winChildrenOf[e.source]) winChildrenOf[e.source] = [];
  winChildrenOf[e.source].push(e.target);
  if (!winParentsOf[e.target]) winParentsOf[e.target] = [];
  winParentsOf[e.target].push(e.source);
}});

function getFullLineage(nodeId) {{
  const lineageSet = new Set();
  const aQueue = [nodeId];
  while (aQueue.length) {{
    const cur = aQueue.pop();
    if (lineageSet.has(cur)) continue;
    lineageSet.add(cur);
    (winParentsOf[cur] || []).forEach(p => aQueue.push(p));
  }}
  const dQueue = [nodeId];
  while (dQueue.length) {{
    const cur = dQueue.pop();
    if (lineageSet.has(cur) && cur !== nodeId) continue;
    lineageSet.add(cur);
    (winChildrenOf[cur] || []).forEach(c => dQueue.push(c));
  }}
  return lineageSet;
}}

// Compute influence weights from a source node.
// Selection winner = 1.0 pass-through, crossover = 0.5 per parent.
// Influence is SUMMED over all paths so that the total influence of all
// gen-0 ancestors on any later node adds up to 1.0.
function computeInfluence(nodeId) {{
  const influence = {{}};
  const nodeGen = {{}};
  nodes.forEach(n => {{ nodeGen[n.id] = n.gen; }});
  const selectedGen = nodeGen[nodeId];

  influence[nodeId] = 1.0;

  // Sort all node ids by generation for ordered traversal
  const allIds = nodes.map(n => n.id);

  // Forward pass: propagate to descendants, processing generation by generation
  const fwdIds = allIds.filter(id => nodeGen[id] > selectedGen);
  fwdIds.sort((a, b) => nodeGen[a] - nodeGen[b]);

  for (const id of fwdIds) {{
    // Sum contributions from all parents
    let total = 0;
    (edgesTo[id] || []).forEach(e => {{
      if (e.type === "eliminated") return;
      const parentInf = influence[e.source] || 0;
      if (parentInf === 0) return;
      const weight = e.type === "selected" ? 1.0 : 0.5;
      total += parentInf * weight;
    }});
    if (total > 0) influence[id] = total;
  }}

  // Backward pass: propagate to ancestors, processing generation by generation (descending)
  const bwdIds = allIds.filter(id => nodeGen[id] < selectedGen);
  bwdIds.sort((a, b) => nodeGen[b] - nodeGen[a]);

  for (const id of bwdIds) {{
    // Sum contributions from all children
    let total = 0;
    (edgesFrom[id] || []).forEach(e => {{
      if (e.type === "eliminated") return;
      const childInf = influence[e.target] || 0;
      if (childInf === 0) return;
      const weight = e.type === "selected" ? 1.0 : 0.5;
      total += childInf * weight;
    }});
    if (total > 0) influence[id] = total;
  }}

  return influence;
}}

function toggleFilter(type) {{
  visibleTypes[type] = !visibleTypes[type];
  const btn = document.getElementById("filter-" + type);
  btn.classList.toggle("active", visibleTypes[type]);
  btn.classList.toggle("off", !visibleTypes[type]);
  applyEdgeFilters();
}}

function applyEdgeFilters() {{
  edgeEls.forEach(el => {{
    const type = el.dataset.type;
    if (!visibleTypes[type]) {{
      el.classList.add("hidden-type");
    }} else {{
      el.classList.remove("hidden-type");
    }}
  }});
}}

function toggleInfluence() {{
  influenceMode = !influenceMode;
  document.getElementById("btn-influence").classList.toggle("active", influenceMode);
  if (selectedNodeId) {{
    selectNode(selectedNodeId);
  }}
}}

function setMode(mode) {{
  displayMode = mode;
  document.getElementById("btn-summary").classList.toggle("active", mode === "summary");
  document.getElementById("btn-full").classList.toggle("active", mode === "full");
  if (selectedNodeId) showText(selectedNodeId);
}}

if (!hasSummaries) {{
  document.getElementById("btn-summary").style.display = "none";
  document.getElementById("btn-full").classList.add("active");
  displayMode = "full";
}}

const COL_W = 120;
const ROW_H = 52;
const PAD_TOP = 70;
const PAD_LEFT = 100;
const NODE_R = 14;

const genCounts = {{}};
nodes.forEach(n => {{ genCounts[n.gen] = (genCounts[n.gen] || 0) + 1; }});
const maxPop = Math.max(...Object.values(genCounts));

const posMap = {{}};
nodes.forEach(n => {{
  const x = PAD_LEFT + n.gen * COL_W;
  const genSize = genCounts[n.gen];
  const totalH = (genSize - 1) * ROW_H;
  const startY = PAD_TOP + (maxPop - 1) * ROW_H / 2 - totalH / 2;
  const y = startY + n.idx * ROW_H;
  posMap[n.id] = {{ x, y }};
}});

const totalW = PAD_LEFT + (numGens) * COL_W + 60;
const totalH = PAD_TOP + maxPop * ROW_H + 40;

const svg = document.getElementById("canvas");
svg.setAttribute("width", totalW);
svg.setAttribute("height", totalH);
svg.setAttribute("viewBox", `0 0 ${{totalW}} ${{totalH}}`);

// Generation labels
for (let g = 0; g < numGens; g++) {{
  const x = PAD_LEFT + g * COL_W;
  const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
  label.setAttribute("x", x);
  label.setAttribute("y", PAD_TOP - 30);
  label.setAttribute("text-anchor", "middle");
  label.setAttribute("class", "gen-label");
  label.textContent = g === 0 ? "Initial" : `Gen ${{g}}`;
  svg.appendChild(label);
}}

// Draw edges
const edgeEls = [];
edges.forEach(e => {{
  const s = posMap[e.source];
  const t = posMap[e.target];
  if (!s || !t) return;
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  const mx = (s.x + t.x) / 2;
  path.setAttribute("d", `M${{s.x}},${{s.y}} C${{mx}},${{s.y}} ${{mx}},${{t.y}} ${{t.x}},${{t.y}}`);
  path.setAttribute("class", `edge ${{e.type}}`);
  path.dataset.source = e.source;
  path.dataset.target = e.target;
  path.dataset.type = e.type;
  svg.appendChild(path);
  edgeEls.push(path);
}});

// Draw nodes
const opColors = {{ initial: "#f0883e", selection: "#58a6ff", crossover: "#3fb950" }};
const tooltip = document.getElementById("tooltip");
const nodeElMap = {{}};

nodes.forEach(n => {{
  const pos = posMap[n.id];
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  g.setAttribute("class", "node");
  g.setAttribute("transform", `translate(${{pos.x}},${{pos.y}})`);
  g.dataset.id = n.id;

  const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  circle.setAttribute("r", NODE_R);
  circle.setAttribute("fill", opColors[n.op] + "33");
  circle.setAttribute("stroke", opColors[n.op]);
  g.appendChild(circle);

  const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
  text.setAttribute("text-anchor", "middle");
  text.setAttribute("dy", "4");
  text.setAttribute("font-size", "10");
  text.textContent = n.idx;
  g.appendChild(text);

  g.addEventListener("mouseenter", (ev) => {{
    let html = `<div class="tt-title">Gen ${{n.gen}} #${{n.idx}}</div>`;
    html += `<div class="tt-dim">Type: ${{n.op}}</div>`;
    if (n.label) html += `<div class="tt-dim">Source: ${{n.label}}</div>`;
    const parentEdges = edges.filter(e => e.target === n.id);
    if (parentEdges.length > 0) {{
      const parents = parentEdges.map(e => e.source).join(", ");
      html += `<div class="tt-dim">Parents: ${{parents}}</div>`;
    }}
    if (influenceMode && selectedNodeId && currentInfluence) {{
      const inf = currentInfluence[n.id];
      if (inf !== undefined) {{
        html += `<div class="tt-dim">Influence: ${{(inf * 100).toFixed(1)}}%</div>`;
      }}
    }}
    tooltip.innerHTML = html;
    tooltip.style.display = "block";
    tooltip.style.left = (ev.clientX + 12) + "px";
    tooltip.style.top = (ev.clientY - 10) + "px";
  }});
  g.addEventListener("mousemove", (ev) => {{
    tooltip.style.left = (ev.clientX + 12) + "px";
    tooltip.style.top = (ev.clientY - 10) + "px";
  }});
  g.addEventListener("mouseleave", () => {{ tooltip.style.display = "none"; }});

  g.addEventListener("click", (ev) => {{
    ev.stopPropagation();
    if (selectedNodeId === n.id) deselectNode();
    else selectNode(n.id);
  }});

  svg.appendChild(g);
  nodeElMap[n.id] = g;
}});

let currentInfluence = null;

function selectNode(nodeId) {{
  selectedNodeId = nodeId;

  if (influenceMode) {{
    currentInfluence = computeInfluence(nodeId);
    applyInfluenceView(nodeId, currentInfluence);
  }} else {{
    currentInfluence = null;
    applyLineageView(nodeId);
  }}
  showText(nodeId);
}}

function applyLineageView(nodeId) {{
  const lineage = getFullLineage(nodeId);

  const lineageEdgeSet = new Set();
  edgeEls.forEach(el => {{
    if (lineage.has(el.dataset.source) && lineage.has(el.dataset.target)) {{
      lineageEdgeSet.add(el);
    }}
  }});

  edgeEls.forEach(el => {{
    el.style.strokeWidth = "";
    el.style.opacity = "";
    if (lineageEdgeSet.has(el)) {{
      el.classList.add("in-lineage");
      el.classList.remove("dimmed");
    }} else {{
      el.classList.remove("in-lineage");
      el.classList.add("dimmed");
    }}
  }});

  Object.entries(nodeElMap).forEach(([id, el]) => {{
    const circle = el.querySelector("circle");
    const text = el.querySelector("text");
    circle.style.opacity = "";
    text.style.opacity = "";
    if (lineage.has(id)) {{
      el.classList.add("in-lineage");
      el.classList.remove("dimmed");
      el.classList.toggle("selected-node", id === nodeId);
    }} else {{
      el.classList.remove("in-lineage", "selected-node");
      el.classList.add("dimmed");
    }}
  }});
}}

function applyInfluenceView(nodeId, influence) {{
  // Clear lineage classes
  edgeEls.forEach(el => {{
    el.classList.remove("in-lineage", "dimmed");
    const s = el.dataset.source;
    const t = el.dataset.target;
    const sInf = influence[s] || 0;
    const tInf = influence[t] || 0;
    const edgeInf = Math.min(sInf, tInf);
    if (edgeInf > 0.001 && el.dataset.type !== "eliminated") {{
      el.style.opacity = Math.max(0.1, edgeInf).toString();
      el.style.strokeWidth = (1.2 + edgeInf * 2.5).toString();
    }} else {{
      el.style.opacity = "0.05";
      el.style.strokeWidth = "";
    }}
  }});

  Object.entries(nodeElMap).forEach(([id, el]) => {{
    el.classList.remove("in-lineage", "dimmed");
    el.classList.toggle("selected-node", id === nodeId);
    const inf = influence[id] || 0;
    const circle = el.querySelector("circle");
    const text = el.querySelector("text");
    if (inf > 0.001) {{
      circle.style.opacity = Math.max(0.15, inf).toString();
      text.style.opacity = Math.max(0.3, inf).toString();
    }} else {{
      circle.style.opacity = "0.08";
      text.style.opacity = "0.08";
    }}
  }});
}}

function deselectNode() {{
  selectedNodeId = null;
  currentInfluence = null;
  edgeEls.forEach(el => {{
    el.classList.remove("in-lineage", "dimmed");
    el.style.strokeWidth = "";
    el.style.opacity = "";
  }});
  Object.values(nodeElMap).forEach(el => {{
    el.classList.remove("in-lineage", "dimmed", "selected-node");
    const circle = el.querySelector("circle");
    const text = el.querySelector("text");
    circle.style.opacity = "";
    text.style.opacity = "";
  }});
  document.getElementById("text-panel").style.display = "none";
  document.getElementById("influence-badge").textContent = "";
}}

function showText(nodeId) {{
  const node = nodes.find(n => n.id === nodeId);
  const panel = document.getElementById("text-panel");
  const title = document.getElementById("text-panel-title");
  const content = document.getElementById("text-content");
  const badge = document.getElementById("influence-badge");

  let label = node.label ? ` — ${{node.label}}` : "";
  title.textContent = `Gen ${{node.gen}} #${{node.idx}}${{label}} (${{node.op}})`;

  if (influenceMode && currentInfluence) {{
    const inf = currentInfluence[nodeId];
    badge.textContent = inf !== undefined ? `Influence: ${{(inf * 100).toFixed(1)}}%` : "";
  }} else {{
    badge.textContent = "";
  }}

  if (displayMode === "summary" && summaries[nodeId]) {{
    content.textContent = summaries[nodeId];
  }} else if (texts[nodeId]) {{
    content.textContent = texts[nodeId];
  }} else {{
    content.textContent = "(text not available)";
  }}
  panel.style.display = "block";
}}

document.addEventListener("click", (ev) => {{
  if (selectedNodeId && !ev.target.closest(".node") && !ev.target.closest("#text-panel") && !ev.target.closest("#header")) {{
    deselectNode();
  }}
}});
</script>
</body>
</html>"""


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python lineage.py <run-dir>")
        sys.exit(1)
    generate_lineage_html(sys.argv[1])
