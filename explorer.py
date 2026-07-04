"""Generate a standalone explorer.html that combines cross-run analytics with per-run lineage views.

Usage:
    python explorer.py                              # auto-discover all experiment dirs
    python explorer.py --output my_explorer.html    # custom output path
    python explorer.py --dirs "Baseline:runs" "No Top Seed:no_top_seed_runs"
    python -m http.server 2943                      # serve from project root
    # Open http://localhost:2943/explorer.html
"""

import argparse
import asyncio
import glob
import json
import os
import html as html_mod

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
from openai import AsyncOpenAI
from cache_on_disk import DCache
from sklearn.manifold import TSNE
from sklearn.metrics.pairwise import cosine_similarity

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, ".cache")

oai = AsyncOpenAI()

# Short display names for models
MODEL_SHORT_NAMES = {
    "claude-sonnet-4-6": "Claude",
    "gpt-5": "GPT-5",
    "google/gemini-3.1-pro-preview": "Gemini",
    "moonshotai/kimi-k2-0905": "Kimi",
    "qwen/qwen3.5-397b-a17b": "Qwen",
}

# Default experiment directories (label -> relative path)
# runs/ is split into Baseline and Path Dep based on directory naming
DEFAULT_EXPERIMENT_DIRS = {
    "Baseline": "runs",
    "Path Dep": "runs",
    "No Top Seed": "no_top_seed_runs",
    "Prompt Generic": "prompt_generic_runs",
    "Prompt Meaning": "prompt_meaning_runs",
    "Prompt Space": "prompt_space_runs",
}


def short_model_name(model: str) -> str:
    return MODEL_SHORT_NAMES.get(model, model)


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

def _is_path_dep_run(run_dirname: str) -> bool:
    return run_dirname.startswith("path-dep")


def load_documents(experiment_dirs: dict[str, str] | None = None) -> list[dict]:
    """Load all documents from all experiment directories.

    experiment_dirs: dict of {label: relative_path} from BASE_DIR.
    For the special case of runs/ dir, Baseline and Path Dep are auto-split.
    """
    if experiment_dirs is None:
        experiment_dirs = DEFAULT_EXPERIMENT_DIRS

    docs = []
    seen_run_dirs = set()  # avoid double-counting runs/ which appears for both Baseline and Path Dep

    for label, rel_path in experiment_dirs.items():
        abs_path = os.path.join(BASE_DIR, rel_path)
        if not os.path.isdir(abs_path):
            continue

        for metadata_path in glob.glob(os.path.join(abs_path, "**", "metadata.json"), recursive=True):
            run_dir = os.path.dirname(metadata_path)

            # Avoid processing the same run_dir twice
            if run_dir in seen_run_dirs:
                continue

            # For runs/ dir, split by path-dep prefix
            run_rel_to_dir = os.path.relpath(run_dir, abs_path)
            top_dirname = run_rel_to_dir.split(os.sep)[0]

            if rel_path == "runs":
                is_pd = _is_path_dep_run(top_dirname)
                if label == "Baseline" and is_pd:
                    continue
                if label == "Path Dep" and not is_pd:
                    continue

            seen_run_dirs.add(run_dir)

            with open(metadata_path) as f:
                metadata = json.load(f)

            run_id = os.path.relpath(run_dir, abs_path)
            # Unique run key includes the experiment dir to avoid collisions
            run_key = f"{rel_path}/{run_id}" if rel_path != "runs" else f"runs/{run_id}"
            run_dir_rel = os.path.relpath(run_dir, BASE_DIR)

            for gen_path in sorted(glob.glob(os.path.join(run_dir, "gen_*"))):
                gen_id = int(os.path.basename(gen_path).replace("gen_", ""))
                for doc_path in sorted(glob.glob(os.path.join(gen_path, "*.txt"))):
                    if doc_path.endswith(".summary.txt"):
                        continue
                    doc_idx = int(os.path.splitext(os.path.basename(doc_path))[0])
                    with open(doc_path) as f:
                        content = f.read()
                    docs.append({
                        "run": run_key,
                        "run_dir_rel": run_dir_rel,  # relative path from BASE_DIR for lineage iframe
                        "experiment": label,
                        "generation": gen_id,
                        "doc_idx": doc_idx,
                        "model": metadata["model"],
                        "short_model": short_model_name(metadata["model"]),
                        "content": content,
                        "file_path": os.path.relpath(doc_path, BASE_DIR),
                    })

    return docs


async def compute_summaries_and_embeddings(docs: list[dict]):
    """Compute summaries and embeddings for all docs (cached)."""
    sem = asyncio.Semaphore(500)

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
    """Create display labels: 'Experiment / ShortModel'."""
    info_for_run = {}
    for doc in docs:
        if doc["run"] not in info_for_run:
            info_for_run[doc["run"]] = {
                "experiment": doc["experiment"],
                "short_model": doc["short_model"],
            }

    labels = {}
    for run in runs:
        info = info_for_run[run]
        labels[run] = f"{info['experiment']} / {info['short_model']}"
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
        dot_m = np.full((len(runs), len(runs)), np.nan)
        for i, r1 in enumerate(runs):
            for j, r2 in enumerate(runs):
                if (r1, gen) in centroids and (r2, gen) in centroids:
                    dot_m[i, j] = float(np.dot(centroids[(r1, gen)], centroids[(r2, gen)]))
        dot_matrices[gen] = [[None if np.isnan(v) else v for v in row] for row in dot_m]

        cos_m = np.full((len(runs), len(runs)), np.nan)
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
        for i in range(len(runs)):
            for j in range(i):
                cos_m[i, j] = cos_m[j, i]
        cos_matrices[gen] = [[None if np.isnan(v) else v for v in row] for row in cos_m]

    return dot_matrices, cos_matrices


# ---------------------------------------------------------------------------
# Heatmap image generation (matplotlib)
# ---------------------------------------------------------------------------

PRESETS = {
    "All": {"experiments": None},
    "Path Dependence": {"experiments": ["Baseline", "Path Dep"]},
    "Seed Sensitivity": {"experiments": ["Baseline", "No Top Seed"]},
    "Generic Prompt": {"experiments": ["Baseline", "Prompt Generic"]},
    "Meaning Prompt": {"experiments": ["Baseline", "Prompt Meaning"]},
    "Space Prompt": {"experiments": ["Baseline", "Prompt Space"]},
}

EXPERIMENT_ORDER = ["Baseline", "Path Dep", "No Top Seed", "Prompt Generic", "Prompt Meaning", "Prompt Space"]


def _filter_runs_for_preset(runs: list[str], run_meta: dict, preset_exps: list[str] | None) -> list[str]:
    """Filter runs to those matching preset experiments."""
    if preset_exps is None:
        return runs
    return [r for r in runs if run_meta[r]["experiment"] in preset_exps]


def _render_heatmap(matrix, labels, title, out_path, vmin=None, vmax=None, cmap='RdYlGn'):
    """Render a single heatmap to a PNG file."""
    n = len(labels)
    fig, ax = plt.subplots(figsize=(max(8, n * 0.6 + 2), max(6, n * 0.5 + 2)))

    # Mask None/NaN values
    masked = np.array([[v if v is not None else np.nan for v in row] for row in matrix])

    im = ax.imshow(masked, cmap=cmap, aspect='equal', vmin=vmin, vmax=vmax)

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)

    # Annotate cells
    for i in range(n):
        for j in range(n):
            v = masked[i, j]
            if not np.isnan(v):
                color = 'white' if abs(v - (vmin or 0)) < (((vmax or 1) - (vmin or 0)) * 0.3) else 'black'
                ax.text(j, i, f'{v:.3f}', ha='center', va='center', fontsize=7, color=color)

    ax.set_title(title, fontsize=12, pad=10)
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close(fig)


def _setup_heatmap_style():
    """Configure matplotlib for dark theme."""
    plt.rcParams.update({
        'figure.facecolor': '#0d1117',
        'axes.facecolor': '#161b22',
        'text.color': '#c9d1d9',
        'axes.labelcolor': '#c9d1d9',
        'xtick.color': '#8b949e',
        'ytick.color': '#8b949e',
    })


def generate_heatmap_images(
    docs: list[dict],
    runs: list[str],
    run_labels: dict[str, str],
    generations: list[int],
    cos_matrices: dict,
    out_dir: str,
):
    """Generate PNG heatmaps for final generation of each preset, plus animated GIFs."""
    _setup_heatmap_style()
    os.makedirs(out_dir, exist_ok=True)

    # Build run_meta lookup
    run_meta = {}
    for d in docs:
        if d["run"] not in run_meta:
            run_meta[d["run"]] = {"experiment": d["experiment"], "model": d["short_model"]}

    # Index mapping: full runs list -> matrix indices
    run_idx = {r: i for i, r in enumerate(runs)}

    for preset_name, preset_cfg in PRESETS.items():
        preset_runs = _filter_runs_for_preset(runs, run_meta, preset_cfg["experiments"])
        if len(preset_runs) < 2:
            continue

        labels = [run_labels[r] for r in preset_runs]
        slug = preset_name.lower().replace(' ', '_')

        # Find last generation that has data for at least some of these runs
        final_gen = generations[-1]

        # Extract submatrix for this preset at final generation
        full_cos = cos_matrices.get(final_gen)
        if full_cos is None:
            continue

        sub_matrix = [[full_cos[run_idx[r1]][run_idx[r2]] for r2 in preset_runs] for r1 in preset_runs]

        # Compute color range from non-null off-diagonal values across all gens
        all_offdiag = []
        for gen in generations:
            fc = cos_matrices.get(gen)
            if fc is None:
                continue
            for i, r1 in enumerate(preset_runs):
                for j, r2 in enumerate(preset_runs):
                    if i != j:
                        v = fc[run_idx[r1]][run_idx[r2]]
                        if v is not None:
                            all_offdiag.append(v)
        if not all_offdiag:
            continue
        vmin, vmax = min(all_offdiag), max(all_offdiag)

        # PNG of final generation
        png_path = os.path.join(out_dir, f'{slug}_cosine_gen{final_gen:03d}.png')
        _render_heatmap(
            sub_matrix, labels,
            f'{preset_name} — Cosine Similarity (Gen {final_gen})',
            png_path, vmin=vmin, vmax=vmax, cmap='RdYlGn',
        )
        print(f'  Wrote {png_path}')

        # Animated GIF over generations
        gif_path = os.path.join(out_dir, f'{slug}_cosine_evolution.gif')
        _render_heatmap_gif(
            cos_matrices, preset_runs, run_idx, labels, generations,
            f'{preset_name} — Cosine Similarity',
            gif_path, vmin=vmin, vmax=vmax, cmap='RdYlGn',
        )
        print(f'  Wrote {gif_path}')


def _render_heatmap_gif(
    matrices: dict, preset_runs: list[str], run_idx: dict,
    labels: list[str], generations: list[int],
    title: str, out_path: str, vmin=None, vmax=None, cmap='RdYlGn',
):
    """Render an animated GIF of heatmaps over generations."""
    n = len(labels)
    fig, ax = plt.subplots(figsize=(max(8, n * 0.6 + 2), max(6, n * 0.5 + 2)))

    def draw_frame(gen_idx):
        ax.clear()
        gen = generations[gen_idx]
        full_m = matrices.get(gen)
        if full_m is None:
            return

        sub = np.array([[
            full_m[run_idx[r1]][run_idx[r2]] if full_m[run_idx[r1]][run_idx[r2]] is not None else np.nan
            for r2 in preset_runs
        ] for r1 in preset_runs])

        im = ax.imshow(sub, cmap=cmap, aspect='equal', vmin=vmin, vmax=vmax)
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(labels, fontsize=8)

        for i in range(n):
            for j in range(n):
                v = sub[i, j]
                if not np.isnan(v):
                    color = 'white' if abs(v - (vmin or 0)) < (((vmax or 1) - (vmin or 0)) * 0.3) else 'black'
                    ax.text(j, i, f'{v:.3f}', ha='center', va='center', fontsize=7, color=color)

        ax.set_title(f'{title} (Gen {gen})', fontsize=12, pad=10)

    anim = animation.FuncAnimation(fig, draw_frame, frames=len(generations), interval=500)
    anim.save(out_path, writer='pillow', dpi=100)
    plt.close(fig)


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
    heatmap_dir: str,
) -> str:
    """Build the complete explorer.html."""

    doc_records = []
    for i, d in enumerate(docs):
        doc_records.append({
            "run": d["run"],
            "gen": d["generation"],
            "idx": d["doc_idx"],
            "model": d["short_model"],
            "experiment": d["experiment"],
            "summary": d["summary"],
            "file_path": d["file_path"],
            "x": float(tsne_coords[i, 0]),
            "y": float(tsne_coords[i, 1]),
        })

    # Collect experiment and model lists
    experiments = sorted(set(d["experiment"] for d in docs))
    models = sorted(set(d["short_model"] for d in docs))

    # Run metadata: experiment + model + lineage path
    run_meta = {}
    for run in runs:
        rdocs = [d for d in docs if d["run"] == run]
        if rdocs:
            run_dir_rel = rdocs[0]["run_dir_rel"]
            lpath = os.path.join(BASE_DIR, run_dir_rel, "lineage.html")
            run_meta[run] = {
                "experiment": rdocs[0]["experiment"],
                "model": rdocs[0]["short_model"],
                "hasLineage": os.path.exists(lpath),
                "lineagePath": run_dir_rel + "/lineage.html",
            }

    # Build heatmap image references per preset
    heatmap_rel = os.path.relpath(heatmap_dir, BASE_DIR)
    final_gen = generations[-1]
    heatmap_images = {}
    for preset_name in PRESETS:
        slug = preset_name.lower().replace(' ', '_')
        png = f'{slug}_cosine_gen{final_gen:03d}.png'
        gif = f'{slug}_cosine_evolution.gif'
        png_path = os.path.join(heatmap_dir, png)
        gif_path = os.path.join(heatmap_dir, gif)
        if os.path.exists(png_path):
            heatmap_images[preset_name] = {
                "png": f'{heatmap_rel}/{png}',
                "gif": f'{heatmap_rel}/{gif}' if os.path.exists(gif_path) else None,
            }

    data_json = json.dumps({
        "docs": doc_records,
        "runs": runs,
        "runLabels": run_labels,
        "runMeta": run_meta,
        "experiments": experiments,
        "models": models,
        "generations": generations,
        "variance": {run: {"generations": v["generations"], "variances": v["variances"]} for run, v in variance_data.items()},
        "heatmapImages": heatmap_images,
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

/* Layout: sidebar + main */
#app {{ display:flex; height:100vh; }}

#sidebar {{ width:220px; min-width:220px; background:#161b22; border-right:1px solid #30363d; display:flex; flex-direction:column; overflow-y:auto; }}
#sidebar-header {{ padding:12px 16px; border-bottom:1px solid #30363d; }}
#sidebar-header h1 {{ font-size:16px; font-weight:600; }}
#sidebar-nav {{ flex:1; overflow-y:auto; padding:8px 0; }}

.sidebar-section {{ padding:4px 12px; }}
.sidebar-section-title {{ font-size:10px; font-weight:600; text-transform:uppercase; color:#8b949e; letter-spacing:0.5px; padding:8px 4px 4px; }}

.nav-btn {{ display:block; width:100%; background:none; border:none; color:#8b949e; padding:5px 12px; border-radius:6px; font-size:12px; cursor:pointer; text-align:left; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.nav-btn:hover {{ background:#21262d; color:#c9d1d9; }}
.nav-btn.active {{ background:#1f6feb; color:#fff; }}

#main {{ flex:1; min-width:0; overflow:hidden; display:flex; flex-direction:column; }}

.tab-content {{ display:none; flex:1; overflow:auto; }}
.tab-content.active {{ display:flex; flex-direction:column; }}

/* Filter panel */
#filter-panel {{ background:#161b22; border-bottom:1px solid #30363d; padding:10px 20px; display:flex; gap:20px; flex-wrap:wrap; align-items:flex-start; flex-shrink:0; }}
.filter-group {{ display:flex; flex-direction:column; gap:4px; }}
.filter-group-title {{ font-size:11px; font-weight:600; text-transform:uppercase; color:#8b949e; letter-spacing:0.5px; }}
.filter-checks {{ display:flex; gap:8px; flex-wrap:wrap; }}
.filter-checks label {{ display:flex; align-items:center; gap:4px; font-size:13px; cursor:pointer; padding:2px 8px; border-radius:4px; }}
.filter-checks label:hover {{ background:#21262d; }}
.filter-checks input[type="checkbox"] {{ accent-color:#1f6feb; }}

.preset-group {{ display:flex; flex-direction:column; gap:4px; }}
.preset-buttons {{ display:flex; gap:4px; flex-wrap:wrap; }}
.preset-btn {{ background:#21262d; border:1px solid #30363d; color:#8b949e; padding:3px 10px; border-radius:4px; font-size:12px; cursor:pointer; white-space:nowrap; }}
.preset-btn:hover {{ background:#30363d; color:#c9d1d9; }}
.preset-btn.active {{ background:#238636; border-color:#238636; color:#fff; }}

.color-toggle {{ display:flex; align-items:center; gap:6px; margin-left:auto; }}
.color-toggle label {{ font-size:12px; cursor:pointer; }}
.color-toggle select {{ background:#21262d; border:1px solid #30363d; color:#c9d1d9; padding:3px 8px; border-radius:4px; font-size:12px; }}

/* Overview tab */
#overview {{ padding:20px; flex:1; overflow:auto; }}
.charts-row {{ display:flex; gap:20px; flex-wrap:wrap; margin-top:20px; }}
.chart-box {{ flex:1; min-width:380px; background:#161b22; border:1px solid #30363d; border-radius:8px; overflow:hidden; }}
.chart-box .chart-title {{ padding:10px 16px; font-size:13px; font-weight:600; border-bottom:1px solid #30363d; }}

#tsne-container {{ background:#161b22; border:1px solid #30363d; border-radius:8px; overflow:hidden; }}

/* Heatmap images */
.heatmap-section {{ margin-top:20px; }}
.heatmap-section h3 {{ font-size:14px; font-weight:600; margin-bottom:8px; }}
.heatmap-toggle {{ display:flex; gap:8px; margin-bottom:12px; }}
.heatmap-card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; overflow:hidden; margin-bottom:16px; }}
.heatmap-card .chart-title {{ padding:10px 16px; font-size:13px; font-weight:600; border-bottom:1px solid #30363d; display:flex; align-items:center; justify-content:space-between; }}
.heatmap-card img {{ width:100%; display:block; }}

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
.run-iframe {{ width:100%; flex:1; border:none; background:#0d1117; }}
</style>
</head>
<body>
<div id="app">
  <div id="sidebar">
    <div id="sidebar-header"><h1>Utopia Explorer</h1></div>
    <div id="sidebar-nav"></div>
  </div>
  <div id="main">
    <div class="tab-content active" id="tab-overview">
      <div id="filter-panel">
        <div class="filter-group">
          <div class="filter-group-title">Experiments</div>
          <div class="filter-checks" id="experiment-filters"></div>
        </div>
        <div class="filter-group">
          <div class="filter-group-title">Models</div>
          <div class="filter-checks" id="model-filters"></div>
        </div>
        <div class="preset-group">
          <div class="filter-group-title">Presets</div>
          <div class="preset-buttons" id="preset-buttons"></div>
        </div>
        <div class="color-toggle">
          <label for="color-mode">t-SNE color:</label>
          <select id="color-mode" onchange="updateTSNE()">
            <option value="experiment">By Experiment</option>
            <option value="model">By Model</option>
          </select>
        </div>
      </div>
      <div id="overview">
        <div id="tsne-container"><div id="tsne-plot"></div></div>
        <div id="text-panel">
          <div id="text-panel-header">
            <h2 id="text-panel-title"></h2>
            <button class="toggle-btn active" id="btn-summary">Summary</button>
            <button class="toggle-btn" id="btn-full">Full Text</button>
            <button class="close-btn" id="btn-close-text">&times;</button>
          </div>
          <div id="text-content"></div>
        </div>
        <div class="charts-row">
          <div class="chart-box"><div class="chart-title">Embedding Variance per Generation</div><div id="variance-plot"></div></div>
        </div>
        <div class="heatmap-section">
          <h3>Cosine Similarity Heatmaps</h3>
          <div id="heatmap-container"></div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const DATA = {data_json};

// ---- Filter state ----
const activeExperiments = new Set(DATA.experiments);
const activeModels = new Set(DATA.models);

function isRunVisible(run) {{
  const meta = DATA.runMeta[run];
  return meta && activeExperiments.has(meta.experiment) && activeModels.has(meta.model);
}}

function getVisibleRuns() {{
  return DATA.runs.filter(isRunVisible);
}}

// ---- Build filter checkboxes ----
function buildFilters() {{
  const expDiv = document.getElementById('experiment-filters');
  DATA.experiments.forEach(exp => {{
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.dataset.experiment = exp;
    cb.onchange = () => {{
      if (cb.checked) activeExperiments.add(exp); else activeExperiments.delete(exp);
      clearActivePreset();
      onFilterChange();
    }};
    label.appendChild(cb);
    label.appendChild(document.createTextNode(exp));
    expDiv.appendChild(label);
  }});

  const modelDiv = document.getElementById('model-filters');
  DATA.models.forEach(model => {{
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.dataset.model = model;
    cb.onchange = () => {{
      if (cb.checked) activeModels.add(model); else activeModels.delete(model);
      clearActivePreset();
      onFilterChange();
    }};
    label.appendChild(cb);
    label.appendChild(document.createTextNode(model));
    modelDiv.appendChild(label);
  }});
}}

// ---- Presets ----
const PRESETS = [
  {{ name: 'All', experiments: null, models: null }},
  {{ name: 'Path Dependence', experiments: ['Baseline', 'Path Dep'], models: null }},
  {{ name: 'Seed Sensitivity', experiments: ['Baseline', 'No Top Seed'], models: null }},
  {{ name: 'Generic Prompt', experiments: ['Baseline', 'Prompt Generic'], models: null }},
  {{ name: 'Meaning Prompt', experiments: ['Baseline', 'Prompt Meaning'], models: null }},
  {{ name: 'Space Prompt', experiments: ['Baseline', 'Prompt Space'], models: null }},
];
// Per-model presets
DATA.models.forEach(m => {{
  PRESETS.push({{ name: m, experiments: null, models: [m] }});
}});

let activePresetBtn = null;

function buildPresets() {{
  const div = document.getElementById('preset-buttons');
  PRESETS.forEach(preset => {{
    const btn = document.createElement('button');
    btn.className = 'preset-btn';
    btn.textContent = preset.name;
    btn.onclick = () => applyPreset(preset, btn);
    div.appendChild(btn);
  }});
}}

function clearActivePreset() {{
  if (activePresetBtn) {{ activePresetBtn.classList.remove('active'); activePresetBtn = null; }}
}}

function applyPreset(preset, btn) {{
  // Update experiment checkboxes
  const exps = preset.experiments || DATA.experiments;
  activeExperiments.clear();
  exps.forEach(e => {{ if (DATA.experiments.includes(e)) activeExperiments.add(e); }});
  document.querySelectorAll('#experiment-filters input').forEach(cb => {{
    cb.checked = activeExperiments.has(cb.dataset.experiment);
  }});

  // Update model checkboxes
  const mods = preset.models || DATA.models;
  activeModels.clear();
  mods.forEach(m => {{ if (DATA.models.includes(m)) activeModels.add(m); }});
  document.querySelectorAll('#model-filters input').forEach(cb => {{
    cb.checked = activeModels.has(cb.dataset.model);
  }});

  // Highlight preset button
  clearActivePreset();
  activePresetBtn = btn;
  btn.classList.add('active');

  onFilterChange();
}}

// ---- Sidebar navigation ----
const sidebarNav = document.getElementById('sidebar-nav');

// Overview button
const overviewSection = document.createElement('div');
overviewSection.className = 'sidebar-section';
const overviewBtn = document.createElement('button');
overviewBtn.className = 'nav-btn active';
overviewBtn.textContent = 'Overview';
overviewBtn.onclick = () => switchTab('overview');
overviewSection.appendChild(overviewBtn);
sidebarNav.appendChild(overviewSection);

// Group runs by experiment
const runsByExperiment = {{}};
DATA.runs.forEach(run => {{
  const meta = DATA.runMeta[run];
  if (!meta) return;
  if (!runsByExperiment[meta.experiment]) runsByExperiment[meta.experiment] = [];
  runsByExperiment[meta.experiment].push(run);
}});

const runNavBtns = {{}};
DATA.experiments.forEach(exp => {{
  const runs = runsByExperiment[exp];
  if (!runs || runs.length === 0) return;

  const section = document.createElement('div');
  section.className = 'sidebar-section';
  const title = document.createElement('div');
  title.className = 'sidebar-section-title';
  title.textContent = exp;
  section.appendChild(title);

  runs.forEach(run => {{
    const meta = DATA.runMeta[run];
    const btn = document.createElement('button');
    btn.className = 'nav-btn';
    btn.textContent = meta.model;
    btn.title = DATA.runLabels[run];
    btn.onclick = () => switchTab(run);
    section.appendChild(btn);
    runNavBtns[run] = btn;

    // Create tab content (iframe) in main area
    const div = document.createElement('div');
    div.className = 'tab-content';
    div.id = 'tab-' + run.replace(/[^a-zA-Z0-9]/g, '_');
    if (meta.hasLineage) {{
      const iframe = document.createElement('iframe');
      iframe.className = 'run-iframe';
      iframe.src = '';
      iframe.dataset.src = meta.lineagePath;
      div.appendChild(iframe);
    }} else {{
      div.innerHTML = '<p style="padding:40px;color:#8b949e;">No lineage.html available for this run.</p>';
    }}
    document.getElementById('main').appendChild(div);
  }});

  sidebarNav.appendChild(section);
}});

function switchTab(tab) {{
  // Deactivate all nav buttons
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  if (tab === 'overview') {{
    overviewBtn.classList.add('active');
    document.getElementById('tab-overview').classList.add('active');
  }} else {{
    if (runNavBtns[tab]) runNavBtns[tab].classList.add('active');
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

// ---- Color palettes ----
const EXPERIMENT_COLORS = {{}};
const EXP_PALETTE = ['#e6194b','#3cb44b','#4363d8','#f58231','#911eb4','#42d4f4','#f032e6','#bfef45','#fabed4','#ffe119'];
DATA.experiments.forEach((exp, i) => {{ EXPERIMENT_COLORS[exp] = EXP_PALETTE[i % EXP_PALETTE.length]; }});

const MODEL_COLORS = {{}};
const MOD_PALETTE = ['#ff6b6b','#51cf66','#339af0','#fcc419','#cc5de8'];
DATA.models.forEach((m, i) => {{ MODEL_COLORS[m] = MOD_PALETTE[i % MOD_PALETTE.length]; }});

// Marker shapes per model (for experiment color mode)
const MODEL_SHAPES = {{}};
const SHAPES = ['circle','square','diamond','cross','triangle-up'];
DATA.models.forEach((m, i) => {{ MODEL_SHAPES[m] = SHAPES[i % SHAPES.length]; }});

// Marker shapes per experiment (for model color mode)
const EXP_SHAPES = {{}};
DATA.experiments.forEach((e, i) => {{ EXP_SHAPES[e] = SHAPES[i % SHAPES.length]; }});

// ---- t-SNE coordinates (computed once, fixed) ----
const allX = DATA.docs.map(d => d.x);
const allY = DATA.docs.map(d => d.y);
const xMin = Math.min(...allX), xMax = Math.max(...allX);
const yMin = Math.min(...allY), yMax = Math.max(...allY);
const padX = (xMax - xMin) * 0.06, padY = (yMax - yMin) * 0.06;

function getColorMode() {{
  return document.getElementById('color-mode').value;
}}

function makeTSNETraces(gen) {{
  const colorMode = getColorMode();
  const visibleRuns = new Set(getVisibleRuns());

  if (colorMode === 'experiment') {{
    const groups = {{}};
    DATA.docs.forEach((d, i) => {{
      if (d.gen !== gen || !visibleRuns.has(d.run)) return;
      const key = d.experiment + '|' + d.model;
      if (!groups[key]) groups[key] = {{ exp: d.experiment, model: d.model, docs: [], indices: [] }};
      groups[key].docs.push(d);
      groups[key].indices.push(i);
    }});

    const seenLegend = new Set();
    return Object.values(groups).map(g => {{
      const legendKey = g.exp;
      const showLeg = !seenLegend.has(legendKey);
      seenLegend.add(legendKey);
      return {{
        x: g.docs.map(d => d.x),
        y: g.docs.map(d => d.y),
        mode: 'markers',
        name: g.exp,
        legendgroup: g.exp,
        showlegend: showLeg,
        marker: {{
          color: EXPERIMENT_COLORS[g.exp],
          symbol: MODEL_SHAPES[g.model],
          size: 9, opacity: 0.85,
          line: {{ width: 0.5, color: '#ffffff55' }},
        }},
        text: g.docs.map(d => `${{d.experiment}} / ${{d.model}}<br>Gen ${{d.gen}} #${{d.idx}}`),
        customdata: g.indices,
        hovertemplate: '%{{text}}<extra></extra>',
      }};
    }});
  }} else {{
    const groups = {{}};
    DATA.docs.forEach((d, i) => {{
      if (d.gen !== gen || !visibleRuns.has(d.run)) return;
      const key = d.model + '|' + d.experiment;
      if (!groups[key]) groups[key] = {{ exp: d.experiment, model: d.model, docs: [], indices: [] }};
      groups[key].docs.push(d);
      groups[key].indices.push(i);
    }});

    const seenLegend = new Set();
    return Object.values(groups).map(g => {{
      const legendKey = g.model;
      const showLeg = !seenLegend.has(legendKey);
      seenLegend.add(legendKey);
      return {{
        x: g.docs.map(d => d.x),
        y: g.docs.map(d => d.y),
        mode: 'markers',
        name: g.model,
        legendgroup: g.model,
        showlegend: showLeg,
        marker: {{
          color: MODEL_COLORS[g.model],
          symbol: EXP_SHAPES[g.exp],
          size: 9, opacity: 0.85,
          line: {{ width: 0.5, color: '#ffffff55' }},
        }},
        text: g.docs.map(d => `${{d.experiment}} / ${{d.model}}<br>Gen ${{d.gen}} #${{d.idx}}`),
        customdata: g.indices,
        hovertemplate: '%{{text}}<extra></extra>',
      }};
    }});
  }}
}}

let currentTSNEGen = DATA.generations[0];

function updateTSNE() {{
  const gens = DATA.generations;
  const traces = makeTSNETraces(currentTSNEGen);
  const frames = gens.map(gen => ({{
    data: makeTSNETraces(gen),
    name: String(gen),
  }}));

  Plotly.react('tsne-plot', {{
    data: traces,
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
        active: gens.indexOf(currentTSNEGen),
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

  // Re-attach click handler
  document.getElementById('tsne-plot').on('plotly_click', function(data) {{
    if (data.points && data.points.length > 0) {{
      const pt = data.points[0];
      const docIdx = pt.customdata;
      if (docIdx !== undefined && docIdx !== null) {{
        showTextPanel(docIdx);
      }}
    }}
  }});
}}

// Track slider changes to remember current generation
document.getElementById('tsne-plot').addEventListener('plotly_sliderchange', function(e) {{
  if (e && e.detail && e.detail.slider && e.detail.slider.active !== undefined) {{
    currentTSNEGen = DATA.generations[e.detail.slider.active];
  }}
}});

// ---- Text panel ----
let textMode = 'summary';
let currentDocIdx = null;

function setTextMode(mode) {{
  textMode = mode;
  document.getElementById('btn-summary').classList.toggle('active', mode === 'summary');
  document.getElementById('btn-full').classList.toggle('active', mode === 'full');
  if (currentDocIdx !== null) showTextPanel(currentDocIdx);
}}

// Attach text panel button handlers via JS (not inline onclick, which can conflict)
document.getElementById('btn-summary').addEventListener('click', function(e) {{
  e.stopPropagation();
  setTextMode('summary');
}});
document.getElementById('btn-full').addEventListener('click', function(e) {{
  e.stopPropagation();
  setTextMode('full');
}});
document.getElementById('btn-close-text').addEventListener('click', function(e) {{
  e.stopPropagation();
  closeTextPanel();
}});

function showTextPanel(docIdx) {{
  currentDocIdx = docIdx;
  const doc = DATA.docs[docIdx];
  const panel = document.getElementById('text-panel');
  const title = document.getElementById('text-panel-title');
  const content = document.getElementById('text-content');

  title.textContent = `${{doc.experiment}} / ${{doc.model}} — Gen ${{doc.gen}} #${{doc.idx}}`;

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
function updateVariancePlot() {{
  const visRuns = getVisibleRuns();
  const traces = visRuns.map(run => {{
    const v = DATA.variance[run];
    if (!v) return null;
    const meta = DATA.runMeta[run];
    return {{
      x: v.generations,
      y: v.variances,
      mode: 'lines+markers',
      name: DATA.runLabels[run],
      line: {{ color: EXPERIMENT_COLORS[meta.experiment], width: 2 }},
      marker: {{ color: EXPERIMENT_COLORS[meta.experiment], size: 5, symbol: MODEL_SHAPES[meta.model] }},
    }};
  }}).filter(Boolean);

  Plotly.react('variance-plot', traces, {{
    paper_bgcolor: '#161b22',
    plot_bgcolor: '#0d1117',
    font: {{ color: '#c9d1d9' }},
    xaxis: {{ title: 'Generation', gridcolor: '#21262d', zerolinecolor: '#30363d' }},
    yaxis: {{ title: 'Total Variance', gridcolor: '#21262d', zerolinecolor: '#30363d' }},
    legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }} }},
    height: 350,
    margin: {{ l: 60, r: 20, t: 20, b: 50 }},
  }});
}}

// ---- Heatmap images ----
function updateHeatmaps() {{
  const container = document.getElementById('heatmap-container');
  container.innerHTML = '';

  // Determine which preset best matches current filter state
  const activeExpArr = [...activeExperiments].sort();
  let matchedPreset = null;

  for (const [name, imgs] of Object.entries(DATA.heatmapImages)) {{
    // Check if this preset's experiments match the active filter
    matchedPreset = name;  // Default to last; we'll refine below
  }}

  // Try to find exact match
  const presetDefs = {{
    'All': null,
    'Path Dependence': ['Baseline', 'Path Dep'],
    'Seed Sensitivity': ['Baseline', 'No Top Seed'],
    'Generic Prompt': ['Baseline', 'Prompt Generic'],
    'Meaning Prompt': ['Baseline', 'Prompt Meaning'],
    'Space Prompt': ['Baseline', 'Prompt Space'],
  }};

  matchedPreset = 'All';
  for (const [name, exps] of Object.entries(presetDefs)) {{
    if (exps === null) continue;
    const sorted = [...exps].sort();
    if (JSON.stringify(sorted) === JSON.stringify(activeExpArr)) {{
      matchedPreset = name;
      break;
    }}
  }}

  const imgs = DATA.heatmapImages[matchedPreset];
  if (!imgs) {{
    // Fall back to "All"
    const allImgs = DATA.heatmapImages['All'];
    if (!allImgs) return;
    renderHeatmapCard(container, matchedPreset, allImgs);
    return;
  }}
  renderHeatmapCard(container, matchedPreset, imgs);
}}

function renderHeatmapCard(container, presetName, imgs) {{
  const card = document.createElement('div');
  card.className = 'heatmap-card';

  const titleBar = document.createElement('div');
  titleBar.className = 'chart-title';
  const titleText = document.createElement('span');
  titleText.textContent = presetName + ' — Cosine Similarity';
  titleBar.appendChild(titleText);

  if (imgs.gif) {{
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'toggle-btn';
    toggleBtn.textContent = 'Show Evolution';
    toggleBtn.onclick = () => {{
      if (img.src.endsWith('.gif')) {{
        img.src = imgs.png;
        toggleBtn.textContent = 'Show Evolution';
        toggleBtn.classList.remove('active');
      }} else {{
        img.src = imgs.gif;
        toggleBtn.textContent = 'Show Final';
        toggleBtn.classList.add('active');
      }}
    }};
    titleBar.appendChild(toggleBtn);
  }}

  card.appendChild(titleBar);

  const img = document.createElement('img');
  img.src = imgs.png;
  img.alt = presetName + ' cosine similarity heatmap';
  card.appendChild(img);

  container.appendChild(card);
}}

// ---- Filter change handler ----
function onFilterChange() {{
  // Update sidebar run visibility
  DATA.runs.forEach(run => {{
    if (runNavBtns[run]) {{
      runNavBtns[run].style.display = isRunVisible(run) ? '' : 'none';
    }}
  }});

  updateTSNE();
  updateVariancePlot();
  updateHeatmaps();
}}

// ---- Initialize ----
buildFilters();
buildPresets();
updateTSNE();
updateVariancePlot();
updateHeatmaps();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_dirs_arg(dirs_list: list[str] | None) -> dict[str, str]:
    """Parse --dirs 'Label:path' arguments into a dict."""
    if not dirs_list:
        return None  # use defaults
    result = {}
    for item in dirs_list:
        if ':' not in item:
            raise ValueError(f"Invalid --dirs format '{item}', expected 'Label:path'")
        label, path = item.split(':', 1)
        result[label.strip()] = path.strip()
    return result


async def main():
    parser = argparse.ArgumentParser(description="Generate explorer.html for utopia evolution runs")
    parser.add_argument("--dirs", nargs="*", help="Experiment dirs as 'Label:path' pairs (default: auto-discover)")
    parser.add_argument("--output", default="explorer.html", help="Output file path (default: explorer.html)")
    args = parser.parse_args()

    experiment_dirs = parse_dirs_arg(args.dirs)

    print("Loading documents...")
    docs = load_documents(experiment_dirs)
    print(f"  {len(docs)} documents from {len(set(d['run'] for d in docs))} runs")

    if not docs:
        print("No documents found! Check experiment directories.")
        return

    print("Computing summaries and embeddings (cached)...")
    await compute_summaries_and_embeddings(docs)

    # Sort runs by experiment group order, then by model name
    EXPERIMENT_ORDER = ["Baseline", "Path Dep", "No Top Seed", "Prompt Generic", "Prompt Meaning", "Prompt Space"]
    exp_rank = {e: i for i, e in enumerate(EXPERIMENT_ORDER)}
    run_info = {}
    for d in docs:
        if d["run"] not in run_info:
            run_info[d["run"]] = (d["experiment"], d["short_model"])
    runs = sorted(set(d["run"] for d in docs),
                  key=lambda r: (exp_rank.get(run_info[r][0], 99), run_info[r][1]))
    generations = sorted(set(d["generation"] for d in docs))
    run_labels_map = compute_run_labels(docs, runs)

    # Generate lineage.html for each run
    from lineage import generate_lineage_html
    for run in runs:
        rdocs = [d for d in docs if d["run"] == run]
        if rdocs:
            run_dir = os.path.join(BASE_DIR, rdocs[0]["run_dir_rel"])
            lineage_path = os.path.join(run_dir, "lineage.json")
            if os.path.exists(lineage_path):
                print(f"  Generating lineage.html for {run}...")
                generate_lineage_html(run_dir)

    print("Computing t-SNE...")
    tsne_coords = compute_tsne(docs)

    print("Computing analytics...")
    variance_data = compute_variance_per_gen(docs, runs)
    _, cos_matrices = compute_heatmaps(docs, runs, generations)

    heatmap_dir = os.path.join(BASE_DIR, "analysis_plots", "explorer")
    print("Generating heatmap images...")
    generate_heatmap_images(docs, runs, run_labels_map, generations, cos_matrices, heatmap_dir)

    print("Generating explorer.html...")
    html = build_explorer_html(
        docs, tsne_coords, runs, run_labels_map, generations,
        variance_data, heatmap_dir,
    )

    out_path = os.path.join(BASE_DIR, args.output)
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Done! Wrote {out_path}")
    print(f"Serve with: python -m http.server 2943")
    print(f"Open: http://localhost:2943/{args.output}")


if __name__ == "__main__":
    asyncio.run(main())
