"""Generate a standalone explorer.html that combines cross-run analytics with per-run lineage views.

Usage:
    python explorer.py          # generates explorer.html
    python -m http.server 2943  # serve from project root
    # Open http://localhost:2943/explorer.html
"""

import asyncio
import glob
import json
import os
import html as html_mod

import numpy as np
from openai import AsyncOpenAI
from cache_on_disk import DCache
from sklearn.manifold import TSNE
from sklearn.metrics.pairwise import cosine_similarity

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE_DIR, "runs")
CACHE_DIR = os.path.join(BASE_DIR, ".cache")

oai = AsyncOpenAI()


@DCache(os.path.join(CACHE_DIR, "summaries"))
async def summarize(text: str) -> str:
    response = await oai.responses.create(
        model="gpt-5.2",
        input=f"Summarize the following text in up to 2000 words and focus on a descriptive (non prose) description of what kind of utopia it describes:\n\n{text}",
        reasoning={"effort": "none"},
    )
    return response.output_text.strip()


@DCache(os.path.join(CACHE_DIR, "embeddings"))
async def get_embedding(text: str, model: str) -> list[float]:
    response = await oai.embeddings.create(input=text[:128000], model=model)
    return response.data[0].embedding


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_documents() -> list[dict]:
    """Load all documents from all runs."""
    docs = []
    for metadata_path in glob.glob(os.path.join(RUNS_DIR, "**", "metadata.json"), recursive=True):
        with open(metadata_path) as f:
            metadata = json.load(f)
        run_dir = os.path.dirname(metadata_path)
        run_id = os.path.relpath(run_dir, RUNS_DIR)
        for gen_path in sorted(glob.glob(os.path.join(run_dir, "gen_*"))):
            gen_id = int(os.path.basename(gen_path).replace("gen_", ""))
            for doc_path in sorted(glob.glob(os.path.join(gen_path, "*.txt"))):
                if doc_path.endswith(".summary.txt"):
                    continue
                doc_idx = int(os.path.splitext(os.path.basename(doc_path))[0])
                with open(doc_path) as f:
                    content = f.read()
                docs.append({
                    "run": run_id,
                    "generation": gen_id,
                    "doc_idx": doc_idx,
                    "model": metadata["model"],
                    "content": content,
                    "file_path": os.path.relpath(doc_path, BASE_DIR),
                })
    return docs


async def compute_summaries_and_embeddings(docs: list[dict]):
    """Compute summaries and embeddings for all docs (cached)."""
    sem = asyncio.Semaphore(20)

    async def process(doc):
        async with sem:
            summary = await summarize(doc["content"])
            embedding = await get_embedding(summary, "text-embedding-3-small")
            doc["summary"] = summary
            doc["embedding"] = embedding

    await asyncio.gather(*(process(d) for d in docs))


# ---------------------------------------------------------------------------
# Analytics computation
# ---------------------------------------------------------------------------

def compute_run_labels(docs: list[dict], runs: list[str]) -> dict[str, str]:
    """Create display labels, disambiguating duplicate models."""
    model_for_run = {}
    for doc in docs:
        if doc["run"] not in model_for_run:
            model_for_run[doc["run"]] = doc["model"]

    model_totals: dict[str, int] = {}
    for run in runs:
        m = model_for_run[run]
        model_totals[m] = model_totals.get(m, 0) + 1

    model_seen: dict[str, int] = {}
    labels = {}
    for run in runs:
        m = model_for_run[run]
        model_seen[m] = model_seen.get(m, 0) + 1
        if model_totals[m] > 1:
            labels[run] = f"{m} #{model_seen[m]}"
        else:
            labels[run] = m
    return labels


def compute_tsne(docs: list[dict]) -> np.ndarray:
    """Compute t-SNE on all document embeddings at once."""
    embeddings = np.array([d["embedding"] for d in docs])
    perp = min(30, len(docs) - 1)
    tsne = TSNE(n_components=2, random_state=42, perplexity=perp)
    return tsne.fit_transform(embeddings)


def compute_variance_per_gen(docs: list[dict], runs: list[str]) -> dict[str, list]:
    """Compute total variance (trace of cov matrix) per generation for each run."""
    result = {}
    for run in runs:
        run_docs = [d for d in docs if d["run"] == run]
        gens = sorted(set(d["generation"] for d in run_docs))
        variances = []
        for gen in gens:
            gen_embs = np.array([d["embedding"] for d in run_docs if d["generation"] == gen])
            if len(gen_embs) < 2:
                variances.append(0.0)
                continue
            mean_emb = np.mean(gen_embs, axis=0)
            cov = np.cov(gen_embs - mean_emb, rowvar=False)
            variances.append(float(np.trace(cov)))
        result[run] = {"generations": gens, "variances": variances}
    return result


def compute_heatmaps(docs: list[dict], runs: list[str], generations: list[int]):
    """Compute dot-product and cosine-similarity matrices per generation."""
    # Compute centroids
    centroids = {}
    for run in runs:
        for gen in generations:
            gen_docs = [d for d in docs if d["run"] == run and d["generation"] == gen]
            if gen_docs:
                embs = np.array([d["embedding"] for d in gen_docs])
                centroids[(run, gen)] = np.mean(embs, axis=0)

    dot_matrices = {}
    cos_matrices = {}

    for gen in generations:
        # Dot product of centroids
        dot_m = np.zeros((len(runs), len(runs)))
        for i, r1 in enumerate(runs):
            for j, r2 in enumerate(runs):
                if (r1, gen) in centroids and (r2, gen) in centroids:
                    dot_m[i, j] = float(np.dot(centroids[(r1, gen)], centroids[(r2, gen)]))
        dot_matrices[gen] = dot_m.tolist()

        # Mean pairwise cosine similarity
        cos_m = np.zeros((len(runs), len(runs)))
        for i, r1 in enumerate(runs):
            docs_r1 = [d for d in docs if d["run"] == r1 and d["generation"] == gen]
            if not docs_r1:
                continue
            emb_r1 = np.array([d["embedding"] for d in docs_r1])
            for j, r2 in enumerate(runs):
                if j < i:
                    cos_m[i, j] = cos_m[j, i]
                    continue
                docs_r2 = [d for d in docs if d["run"] == r2 and d["generation"] == gen]
                if not docs_r2:
                    continue
                emb_r2 = np.array([d["embedding"] for d in docs_r2])
                sim = cosine_similarity(emb_r1, emb_r2)
                cos_m[i, j] = float(sim.mean())
        # Fill lower triangle
        for i in range(len(runs)):
            for j in range(i):
                cos_m[i, j] = cos_m[j, i]
        cos_matrices[gen] = cos_m.tolist()

    return dot_matrices, cos_matrices


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def build_explorer_html(
    docs: list[dict],
    tsne_coords: np.ndarray,
    runs: list[str],
    run_labels: dict[str, str],
    generations: list[int],
    variance_data: dict,
    dot_matrices: dict,
    cos_matrices: dict,
) -> str:
    """Build the complete explorer.html."""

    # Prepare lightweight doc records for JSON embedding (no full text, no embeddings)
    doc_records = []
    for i, d in enumerate(docs):
        doc_records.append({
            "run": d["run"],
            "gen": d["generation"],
            "idx": d["doc_idx"],
            "model": d["model"],
            "summary": d["summary"],
            "file_path": d["file_path"],
            "x": float(tsne_coords[i, 0]),
            "y": float(tsne_coords[i, 1]),
        })

    # Find which runs have lineage.html
    run_has_lineage = {}
    for run in runs:
        lpath = os.path.join(RUNS_DIR, run, "lineage.html")
        run_has_lineage[run] = os.path.exists(lpath)

    data_json = json.dumps({
        "docs": doc_records,
        "runs": runs,
        "runLabels": run_labels,
        "runHasLineage": run_has_lineage,
        "generations": generations,
        "variance": {run: {"generations": v["generations"], "variances": v["variances"]} for run, v in variance_data.items()},
        "dotMatrices": {str(k): v for k, v in dot_matrices.items()},
        "cosMatrices": {str(k): v for k, v in cos_matrices.items()},
    })

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Utopia Evolution Explorer</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#0d1117; color:#c9d1d9; }}

#header {{ position:sticky; top:0; z-index:20; background:#161b22; border-bottom:1px solid #30363d; padding:12px 20px; display:flex; align-items:center; gap:16px; flex-wrap:wrap; }}
#header h1 {{ font-size:18px; font-weight:600; }}

.tab-bar {{ display:flex; gap:4px; }}
.tab-btn {{ background:#21262d; border:1px solid #30363d; color:#8b949e; padding:6px 16px; border-radius:6px; font-size:13px; cursor:pointer; user-select:none; white-space:nowrap; }}
.tab-btn:hover {{ background:#30363d; color:#c9d1d9; }}
.tab-btn.active {{ background:#1f6feb; border-color:#1f6feb; color:#fff; }}

.tab-content {{ display:none; }}
.tab-content.active {{ display:block; }}

/* Overview tab */
#overview {{ padding:20px; }}
.charts-row {{ display:flex; gap:20px; flex-wrap:wrap; margin-top:20px; }}
.chart-box {{ flex:1; min-width:380px; background:#161b22; border:1px solid #30363d; border-radius:8px; overflow:hidden; }}
.chart-box .chart-title {{ padding:10px 16px; font-size:13px; font-weight:600; border-bottom:1px solid #30363d; }}

#tsne-container {{ background:#161b22; border:1px solid #30363d; border-radius:8px; overflow:hidden; }}

/* Text panel */
#text-panel {{ background:#161b22; border:1px solid #30363d; border-radius:8px; margin-top:16px; display:none; }}
#text-panel-header {{ display:flex; align-items:center; gap:12px; padding:12px 16px; border-bottom:1px solid #30363d; }}
#text-panel-header h2 {{ font-size:14px; font-weight:600; }}
#text-panel-header .close-btn {{ margin-left:auto; background:none; border:none; color:#8b949e; font-size:18px; cursor:pointer; padding:0 6px; }}
#text-panel-header .close-btn:hover {{ color:#c9d1d9; }}
.toggle-btn {{ background:#21262d; border:1px solid #30363d; color:#c9d1d9; padding:4px 12px; border-radius:6px; font-size:12px; cursor:pointer; }}
.toggle-btn:hover {{ background:#30363d; }}
.toggle-btn.active {{ background:#1f6feb; border-color:#1f6feb; }}
#text-content {{ padding:16px; max-height:50vh; overflow-y:auto; white-space:pre-wrap; font-size:14px; line-height:1.7; }}

/* Run tab iframe */
.run-iframe {{ width:100%; height:calc(100vh - 60px); border:none; background:#0d1117; }}
</style>
</head>
<body>
<div id="header">
  <h1>Utopia Evolution Explorer</h1>
  <div class="tab-bar" id="tab-bar"></div>
</div>

<div class="tab-content active" id="tab-overview">
  <div id="overview">
    <div id="tsne-container"><div id="tsne-plot"></div></div>
    <div id="text-panel">
      <div id="text-panel-header">
        <h2 id="text-panel-title"></h2>
        <button class="toggle-btn active" id="btn-summary" onclick="setTextMode('summary')">Summary</button>
        <button class="toggle-btn" id="btn-full" onclick="setTextMode('full')">Full Text</button>
        <button class="close-btn" onclick="closeTextPanel()">&times;</button>
      </div>
      <div id="text-content"></div>
    </div>
    <div class="charts-row">
      <div class="chart-box"><div class="chart-title">Embedding Variance per Generation</div><div id="variance-plot"></div></div>
    </div>
    <div class="charts-row">
      <div class="chart-box"><div class="chart-title">Centroid Dot Product</div><div id="dot-plot"></div></div>
      <div class="chart-box"><div class="chart-title">Mean Pairwise Cosine Similarity</div><div id="cos-plot"></div></div>
    </div>
  </div>
</div>

<script>
const DATA = {data_json};

// ---- Tab management ----
const tabBar = document.getElementById('tab-bar');
const overviewBtn = document.createElement('button');
overviewBtn.className = 'tab-btn active';
overviewBtn.textContent = 'Overview';
overviewBtn.onclick = () => switchTab('overview');
tabBar.appendChild(overviewBtn);

const runTabs = {{}};
DATA.runs.forEach(run => {{
  const btn = document.createElement('button');
  btn.className = 'tab-btn';
  btn.textContent = DATA.runLabels[run];
  btn.onclick = () => switchTab(run);
  tabBar.appendChild(btn);
  runTabs[run] = btn;

  // Create tab content (iframe)
  const div = document.createElement('div');
  div.className = 'tab-content';
  div.id = 'tab-' + run.replace(/[^a-zA-Z0-9]/g, '_');
  if (DATA.runHasLineage[run]) {{
    const iframe = document.createElement('iframe');
    iframe.className = 'run-iframe';
    iframe.src = '';
    iframe.dataset.src = 'runs/' + run + '/lineage.html';
    div.appendChild(iframe);
  }} else {{
    div.innerHTML = '<p style="padding:40px;color:#8b949e;">No lineage.html available for this run.</p>';
  }}
  document.body.appendChild(div);
}});

function switchTab(tab) {{
  // Deactivate all
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  if (tab === 'overview') {{
    overviewBtn.classList.add('active');
    document.getElementById('tab-overview').classList.add('active');
  }} else {{
    runTabs[tab].classList.add('active');
    const divId = 'tab-' + tab.replace(/[^a-zA-Z0-9]/g, '_');
    const div = document.getElementById(divId);
    div.classList.add('active');
    // Lazy load iframe
    const iframe = div.querySelector('iframe');
    if (iframe && !iframe.src.includes('lineage.html')) {{
      iframe.src = iframe.dataset.src;
    }}
  }}
}}

// ---- Color palette ----
const RUN_COLORS = ['#e6194b','#3cb44b','#ffe119','#4363d8','#f58231','#911eb4','#42d4f4','#f032e6','#bfef45','#fabed4'];
const runColorMap = {{}};
DATA.runs.forEach((run, i) => {{ runColorMap[run] = RUN_COLORS[i % RUN_COLORS.length]; }});

// ---- t-SNE plot ----
(function() {{
  const gens = DATA.generations;

  function makeTraces(gen, showLegend) {{
    return DATA.runs.map(run => {{
      const pts = DATA.docs.filter(d => d.run === run && d.gen === gen);
      return {{
        x: pts.map(d => d.x),
        y: pts.map(d => d.y),
        mode: 'markers',
        name: DATA.runLabels[run],
        marker: {{ color: runColorMap[run], size: 8, opacity: 0.85, line: {{ width: 0.5, color: '#ffffff55' }} }},
        text: pts.map(d => `${{DATA.runLabels[d.run]}}<br>Gen ${{d.gen}} #${{d.idx}}`),
        customdata: pts.map((d, i) => DATA.docs.indexOf(d)),
        hovertemplate: '%{{text}}<extra></extra>',
        showlegend: showLegend,
      }};
    }});
  }}

  const allX = DATA.docs.map(d => d.x);
  const allY = DATA.docs.map(d => d.y);
  const xMin = Math.min(...allX), xMax = Math.max(...allX);
  const yMin = Math.min(...allY), yMax = Math.max(...allY);
  const padX = (xMax - xMin) * 0.06, padY = (yMax - yMin) * 0.06;

  const frames = gens.map(gen => ({{
    data: makeTraces(gen, false),
    name: String(gen),
  }}));

  Plotly.newPlot('tsne-plot', {{
    data: makeTraces(gens[0], true),
    layout: {{
      title: {{ text: 't-SNE of utopia embeddings across generations', font: {{ color: '#c9d1d9' }} }},
      paper_bgcolor: '#161b22',
      plot_bgcolor: '#0d1117',
      font: {{ color: '#c9d1d9' }},
      xaxis: {{ range: [xMin - padX, xMax + padX], title: 't-SNE 1', gridcolor: '#21262d', zerolinecolor: '#30363d' }},
      yaxis: {{ range: [yMin - padY, yMax + padY], title: 't-SNE 2', gridcolor: '#21262d', zerolinecolor: '#30363d' }},
      legend: {{ bgcolor: 'rgba(0,0,0,0)' }},
      height: 600,
      sliders: [{{
        steps: gens.map(gen => ({{
          args: [[String(gen)], {{ frame: {{ duration: 300, redraw: true }}, mode: 'immediate' }}],
          label: String(gen),
          method: 'animate',
        }})),
        currentvalue: {{ prefix: 'Generation: ', font: {{ color: '#c9d1d9' }} }},
        pad: {{ t: 50 }},
        font: {{ color: '#c9d1d9' }},
      }}],
      updatemenus: [{{
        type: 'buttons', showactive: false, y: 0, x: 0.5, xanchor: 'center',
        buttons: [
          {{ label: 'Play', method: 'animate', args: [null, {{ frame: {{ duration: 500, redraw: true }}, fromcurrent: true }}] }},
          {{ label: 'Pause', method: 'animate', args: [[null], {{ frame: {{ duration: 0, redraw: true }}, mode: 'immediate' }}] }},
        ],
        font: {{ color: '#c9d1d9' }},
      }}],
    }},
    frames: frames,
  }});

  // Click handler for t-SNE points
  document.getElementById('tsne-plot').on('plotly_click', function(data) {{
    if (data.points && data.points.length > 0) {{
      const pt = data.points[0];
      const docIdx = pt.customdata;
      if (docIdx !== undefined && docIdx !== null) {{
        showTextPanel(docIdx);
      }}
    }}
  }});
}})();

// ---- Text panel ----
let textMode = 'summary';
let currentDocIdx = null;

function setTextMode(mode) {{
  textMode = mode;
  document.getElementById('btn-summary').classList.toggle('active', mode === 'summary');
  document.getElementById('btn-full').classList.toggle('active', mode === 'full');
  if (currentDocIdx !== null) showTextPanel(currentDocIdx);
}}

function showTextPanel(docIdx) {{
  currentDocIdx = docIdx;
  const doc = DATA.docs[docIdx];
  const panel = document.getElementById('text-panel');
  const title = document.getElementById('text-panel-title');
  const content = document.getElementById('text-content');

  title.textContent = `${{DATA.runLabels[doc.run]}} — Gen ${{doc.gen}} #${{doc.idx}}`;

  if (textMode === 'summary') {{
    content.textContent = doc.summary;
  }} else {{
    content.textContent = 'Loading...';
    fetch(doc.file_path)
      .then(r => r.text())
      .then(text => {{
        if (currentDocIdx === docIdx) content.textContent = text;
      }})
      .catch(() => {{ content.textContent = '(failed to load full text)'; }});
  }}
  panel.style.display = 'block';
}}

function closeTextPanel() {{
  document.getElementById('text-panel').style.display = 'none';
  currentDocIdx = null;
}}

// ---- Variance plot ----
(function() {{
  const traces = DATA.runs.map(run => {{
    const v = DATA.variance[run];
    if (!v) return null;
    return {{
      x: v.generations,
      y: v.variances,
      mode: 'lines+markers',
      name: DATA.runLabels[run],
      line: {{ color: runColorMap[run], width: 2 }},
      marker: {{ color: runColorMap[run], size: 5 }},
    }};
  }}).filter(Boolean);

  Plotly.newPlot('variance-plot', traces, {{
    paper_bgcolor: '#161b22',
    plot_bgcolor: '#0d1117',
    font: {{ color: '#c9d1d9' }},
    xaxis: {{ title: 'Generation', gridcolor: '#21262d', zerolinecolor: '#30363d' }},
    yaxis: {{ title: 'Total Variance', gridcolor: '#21262d', zerolinecolor: '#30363d' }},
    legend: {{ bgcolor: 'rgba(0,0,0,0)' }},
    height: 350,
    margin: {{ l: 60, r: 20, t: 20, b: 50 }},
  }});
}})();

// ---- Heatmap helpers ----
function makeHeatmap(divId, matricesObj, title) {{
  const gens = DATA.generations;
  const labels = DATA.runs.map(r => DATA.runLabels[r]);

  // Global color range
  let allVals = [];
  gens.forEach(g => {{
    const m = matricesObj[String(g)];
    if (m) m.forEach(row => row.forEach(v => allVals.push(v)));
  }});
  const zMin = Math.min(...allVals), zMax = Math.max(...allVals);

  const frames = gens.map(gen => {{
    const m = matricesObj[String(gen)] || [];
    return {{
      data: [{{
        z: m, x: labels, y: labels,
        type: 'heatmap', colorscale: 'RdBu', zmid: 0, zmin: zMin, zmax: zMax,
        text: m.map(row => row.map(v => v.toFixed(3))),
        texttemplate: '%{{text}}',
        hovertemplate: '%{{y}} vs %{{x}}: %{{z:.4f}}<extra></extra>',
      }}],
      name: String(gen),
    }};
  }});

  const firstM = matricesObj[String(gens[0])] || [];
  Plotly.newPlot(divId, {{
    data: [{{
      z: firstM, x: labels, y: labels,
      type: 'heatmap', colorscale: 'RdBu', zmid: 0, zmin: zMin, zmax: zMax,
      text: firstM.map(row => row.map(v => v.toFixed(3))),
      texttemplate: '%{{text}}',
      hovertemplate: '%{{y}} vs %{{x}}: %{{z:.4f}}<extra></extra>',
    }}],
    layout: {{
      paper_bgcolor: '#161b22',
      plot_bgcolor: '#0d1117',
      font: {{ color: '#c9d1d9', size: 11 }},
      height: 400,
      margin: {{ l: 120, r: 20, t: 20, b: 80 }},
      sliders: [{{
        steps: gens.map(gen => ({{
          args: [[String(gen)], {{ frame: {{ duration: 300, redraw: true }}, mode: 'immediate' }}],
          label: String(gen),
          method: 'animate',
        }})),
        currentvalue: {{ prefix: 'Generation: ', font: {{ color: '#c9d1d9' }} }},
        pad: {{ t: 40 }},
        font: {{ color: '#c9d1d9' }},
      }}],
      updatemenus: [{{
        type: 'buttons', showactive: false, y: 0, x: 0.5, xanchor: 'center',
        buttons: [
          {{ label: 'Play', method: 'animate', args: [null, {{ frame: {{ duration: 500, redraw: true }}, fromcurrent: true }}] }},
          {{ label: 'Pause', method: 'animate', args: [[null], {{ frame: {{ duration: 0, redraw: true }}, mode: 'immediate' }}] }},
        ],
        font: {{ color: '#c9d1d9' }},
      }}],
    }},
    frames: frames,
  }});
}}

makeHeatmap('dot-plot', DATA.dotMatrices, 'Centroid Dot Product');
makeHeatmap('cos-plot', DATA.cosMatrices, 'Mean Pairwise Cosine Similarity');
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("Loading documents...")
    docs = load_documents()
    print(f"  {len(docs)} documents from {len(set(d['run'] for d in docs))} runs")

    print("Computing summaries and embeddings (cached)...")
    await compute_summaries_and_embeddings(docs)

    runs = sorted(set(d["run"] for d in docs))
    generations = sorted(set(d["generation"] for d in docs))
    run_labels_map = compute_run_labels(docs, runs)

    # Generate lineage.html for each run
    from lineage import generate_lineage_html
    for run in runs:
        run_dir = os.path.join(RUNS_DIR, run)
        lineage_path = os.path.join(run_dir, "lineage.json")
        if os.path.exists(lineage_path):
            print(f"  Generating lineage.html for {run}...")
            generate_lineage_html(run_dir)

    print("Computing t-SNE...")
    tsne_coords = compute_tsne(docs)

    print("Computing analytics...")
    variance_data = compute_variance_per_gen(docs, runs)
    dot_matrices, cos_matrices = compute_heatmaps(docs, runs, generations)

    print("Generating explorer.html...")
    html = build_explorer_html(
        docs, tsne_coords, runs, run_labels_map, generations,
        variance_data, dot_matrices, cos_matrices,
    )

    out_path = os.path.join(BASE_DIR, "explorer.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Done! Wrote {out_path}")
    print(f"Serve with: python -m http.server 2943")
    print(f"Open: http://localhost:2943/explorer.html")


if __name__ == "__main__":
    asyncio.run(main())
