"""Analyze influence of initial essays across all runs and generate plots."""

import json
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

BASE_DIR = os.path.dirname(__file__)
RUNS_DIR = os.path.join(BASE_DIR, "runs")

# Map run dirs to friendly model names
RUN_CONFIGS = [
    ("gpt-5_20260222_164038", "GPT-5"),
    ("claude-sonnet-4-6_20260222_221551", "Claude Sonnet 4.6"),
    ("moonshotai/kimi-k2-0905_20260222_180638", "Kimi K2"),
    ("google/gemini-3.1-pro-preview_20260222_221814", "Gemini 3.1 Pro"),
    ("qwen/qwen3.5-397b-a17b_20260222_225006", "Qwen 3.5"),
]

def load_lineage(run_dir):
    with open(os.path.join(run_dir, "lineage.json")) as f:
        return json.load(f)

def get_initial_essay_names(lineage):
    """Get ordered list of initial essay source names."""
    return [
        entry.get("source", f"essay_{i}").replace(".txt", "")
        for i, entry in enumerate(lineage["0"])
    ]

def compute_influence_forward(lineage, source_gen, source_idx, target_gen):
    """Compute influence of a single node on all nodes in target_gen.

    Selection winner = 1.0 pass-through from winning parent.
    Crossover = 0.5 from each parent.
    Influence is summed over all paths.
    """
    num_gens = max(int(k) for k in lineage) + 1

    # influence[gen][idx] = float
    influence = defaultdict(lambda: defaultdict(float))
    influence[source_gen][source_idx] = 1.0

    for gen in range(source_gen + 1, num_gens):
        gen_str = str(gen)
        if gen_str not in lineage:
            break
        for idx, entry in enumerate(lineage[gen_str]):
            op = entry["op"]
            parents = entry.get("parents", [])
            if op == "selection":
                winner = entry["winner"]
                # Only the winning parent passes influence
                parent_inf = influence[gen - 1][winner]
                if parent_inf > 0:
                    influence[gen][idx] += parent_inf
            elif op == "crossover":
                for p in parents:
                    parent_inf = influence[gen - 1][p]
                    if parent_inf > 0:
                        influence[gen][idx] += parent_inf * 0.5

    return influence

def compute_initial_influence_on_final(lineage):
    """For each initial essay, compute total influence on the final generation.

    Returns dict: {essay_index: total_influence_on_final_gen}
    """
    num_gens = max(int(k) for k in lineage)  # last gen number
    n_initial = len(lineage["0"])
    n_final = len(lineage[str(num_gens)])

    influences = {}
    for i in range(n_initial):
        inf = compute_influence_forward(lineage, 0, i, num_gens)
        # Sum influence on all final-gen essays
        total = sum(inf[num_gens][j] for j in range(n_final))
        influences[i] = total

    return influences

def compute_influence_over_generations(lineage):
    """For each initial essay, compute total influence at each generation.

    Returns dict: {essay_index: [influence_at_gen_0, influence_at_gen_1, ...]}
    """
    num_gens = max(int(k) for k in lineage)
    n_initial = len(lineage["0"])

    result = {}
    for i in range(n_initial):
        inf = compute_influence_forward(lineage, 0, i, num_gens)
        gen_totals = []
        for gen in range(num_gens + 1):
            n_gen = len(lineage[str(gen)])
            total = sum(inf[gen][j] for j in range(n_gen))
            gen_totals.append(total)
        result[i] = gen_totals

    return result

def shorten_name(name, max_len=25):
    """Shorten essay name for display."""
    name = name.replace("-", " ").replace("_", " ")
    if len(name) > max_len:
        return name[:max_len-2] + ".."
    return name

def main():
    out_dir = os.path.join(BASE_DIR, "analysis_plots")
    os.makedirs(out_dir, exist_ok=True)

    # Collect data across all runs
    all_influences = {}  # model_name -> {essay_idx: influence}
    essay_names = None

    for run_subdir, model_name in RUN_CONFIGS:
        run_dir = os.path.join(RUNS_DIR, run_subdir)
        if not os.path.exists(run_dir):
            print(f"Skipping {model_name}: {run_dir} not found")
            continue

        lineage = load_lineage(run_dir)
        if essay_names is None:
            essay_names = get_initial_essay_names(lineage)

        influences = compute_initial_influence_on_final(lineage)
        all_influences[model_name] = influences
        print(f"\n{model_name}:")
        for idx in sorted(influences, key=lambda x: -influences[x]):
            print(f"  {essay_names[idx][:50]:50s} {influences[idx]:.3f}")

    n_essays = len(essay_names)
    n_models = len(all_influences)

    # =========================================================================
    # PLOT 1: Heatmap of initial essay influence across models
    # =========================================================================
    fig, ax = plt.subplots(figsize=(14, 8))

    model_names = list(all_influences.keys())

    # Build matrix: rows=essays, cols=models
    matrix = np.zeros((n_essays, n_models))
    for j, model in enumerate(model_names):
        infs = all_influences[model]
        for i in range(n_essays):
            matrix[i, j] = infs.get(i, 0)

    # Normalize each column to show relative influence within each model
    col_sums = matrix.sum(axis=0, keepdims=True)
    col_sums[col_sums == 0] = 1
    matrix_norm = matrix / col_sums

    # Sort essays by average influence across models
    avg_influence = matrix_norm.mean(axis=1)
    sort_idx = np.argsort(-avg_influence)
    matrix_norm_sorted = matrix_norm[sort_idx]
    sorted_names = [shorten_name(essay_names[i]) for i in sort_idx]

    im = ax.imshow(matrix_norm_sorted, aspect='auto', cmap='YlOrRd', interpolation='nearest')
    ax.set_xticks(range(n_models))
    ax.set_xticklabels(model_names, fontsize=11, rotation=15, ha='right')
    ax.set_yticks(range(n_essays))
    ax.set_yticklabels(sorted_names, fontsize=9)
    ax.set_title("Initial Essay Influence on Final Generation\n(normalized within each model)", fontsize=14, fontweight='bold')

    # Add text annotations
    for i in range(n_essays):
        for j in range(n_models):
            val = matrix_norm_sorted[i, j]
            color = 'white' if val > 0.12 else 'black'
            ax.text(j, i, f'{val:.0%}', ha='center', va='center', fontsize=8, color=color)

    plt.colorbar(im, ax=ax, label='Relative Influence', shrink=0.8)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "influence_heatmap.png"), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nSaved influence_heatmap.png")

    # =========================================================================
    # PLOT 2: Top essays bar chart per model
    # =========================================================================
    fig, axes = plt.subplots(1, n_models, figsize=(4 * n_models, 8), sharey=True)
    if n_models == 1:
        axes = [axes]

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']

    for j, (model, ax) in enumerate(zip(model_names, axes)):
        infs = all_influences[model]
        # Sort by influence
        sorted_essays = sorted(range(n_essays), key=lambda x: -infs.get(x, 0))
        vals = [infs.get(i, 0) for i in sorted_essays]
        # Normalize
        total = sum(vals) if sum(vals) > 0 else 1
        vals_norm = [v / total for v in vals]
        names = [shorten_name(essay_names[i], 30) for i in sorted_essays]

        ax.barh(range(n_essays), vals_norm, color=colors[j % len(colors)], alpha=0.8)
        ax.set_yticks(range(n_essays))
        if j == 0:
            ax.set_yticklabels(names, fontsize=8)
        ax.set_title(model, fontsize=11, fontweight='bold')
        ax.set_xlabel('Relative Influence')
        ax.invert_yaxis()

    plt.suptitle("Which Seed Essays Survived? (Influence on Gen 20)", fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "influence_per_model.png"), dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved influence_per_model.png")

    # =========================================================================
    # PLOT 3: Influence decay/growth over generations for top essays (one per model)
    # =========================================================================
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    axes = axes.flatten()

    for j, (run_subdir, model_name) in enumerate(RUN_CONFIGS):
        if j >= 5:
            break
        ax = axes[j]
        run_dir = os.path.join(RUNS_DIR, run_subdir)
        lineage = load_lineage(run_dir)
        gen_influences = compute_influence_over_generations(lineage)

        # Normalize per generation
        num_gens = max(int(k) for k in lineage)
        n_initial = len(lineage["0"])

        for gen in range(num_gens + 1):
            total = sum(gen_influences[i][gen] for i in range(n_initial))
            if total > 0:
                for i in range(n_initial):
                    gen_influences[i][gen] /= total

        # Plot top 5 by final influence
        final_infs = {i: gen_influences[i][-1] for i in range(n_initial)}
        top5 = sorted(final_infs, key=lambda x: -final_infs[x])[:5]

        for i in top5:
            label = shorten_name(essay_names[i], 30)
            ax.plot(range(num_gens + 1), gen_influences[i], label=label, linewidth=2, alpha=0.8)

        ax.set_title(model_name, fontsize=12, fontweight='bold')
        ax.set_xlabel('Generation')
        ax.set_ylabel('Relative Influence')
        ax.legend(fontsize=7, loc='upper left')
        ax.set_xlim(0, num_gens)
        ax.set_ylim(0, None)
        ax.grid(alpha=0.3)

    # Hide the 6th subplot
    axes[5].set_visible(False)

    plt.suptitle("Influence Trajectories: Top 5 Seed Essays Over 20 Generations", fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "influence_trajectories.png"), dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved influence_trajectories.png")

    # =========================================================================
    # PLOT 4: Diversity/convergence metric over generations
    # =========================================================================
    fig, ax = plt.subplots(figsize=(10, 6))

    for j, (run_subdir, model_name) in enumerate(RUN_CONFIGS):
        run_dir = os.path.join(RUNS_DIR, run_subdir)
        lineage = load_lineage(run_dir)
        gen_influences = compute_influence_over_generations(lineage)
        num_gens = max(int(k) for k in lineage)
        n_initial = len(lineage["0"])

        # Compute entropy at each generation (measure of diversity)
        entropies = []
        for gen in range(num_gens + 1):
            total = sum(gen_influences[i][gen] for i in range(n_initial))
            if total > 0:
                probs = [gen_influences[i][gen] / total for i in range(n_initial)]
                probs = [p for p in probs if p > 0]
                entropy = -sum(p * np.log2(p) for p in probs)
            else:
                entropy = 0
            entropies.append(entropy)

        ax.plot(range(num_gens + 1), entropies, label=model_name, linewidth=2, alpha=0.8)

    max_entropy = np.log2(n_essays)
    ax.axhline(y=max_entropy, color='gray', linestyle='--', alpha=0.5, label=f'Max entropy ({max_entropy:.1f} bits)')
    ax.set_xlabel('Generation', fontsize=12)
    ax.set_ylabel('Shannon Entropy (bits)', fontsize=12)
    ax.set_title('Genetic Diversity Over Generations\n(Higher = more diverse influence from seed essays)', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)
    ax.set_xlim(0, 20)

    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "diversity_entropy.png"), dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved diversity_entropy.png")

    # =========================================================================
    # PLOT 5: Cross-model agreement on essay fitness
    # =========================================================================
    fig, ax = plt.subplots(figsize=(10, 8))

    # Correlation matrix between models
    model_vectors = []
    for model in model_names:
        infs = all_influences[model]
        total = sum(infs.values()) if sum(infs.values()) > 0 else 1
        vec = np.array([infs.get(i, 0) / total for i in range(n_essays)])
        model_vectors.append(vec)

    corr_matrix = np.corrcoef(model_vectors)

    im = ax.imshow(corr_matrix, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(n_models))
    ax.set_xticklabels(model_names, fontsize=11, rotation=15, ha='right')
    ax.set_yticks(range(n_models))
    ax.set_yticklabels(model_names, fontsize=11)
    ax.set_title("Cross-Model Agreement on Essay Fitness\n(Pearson correlation of influence vectors)", fontsize=14, fontweight='bold')

    for i in range(n_models):
        for j in range(n_models):
            ax.text(j, i, f'{corr_matrix[i,j]:.2f}', ha='center', va='center', fontsize=12,
                   color='white' if abs(corr_matrix[i,j]) > 0.5 else 'black')

    plt.colorbar(im, ax=ax, label='Correlation', shrink=0.8)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "model_agreement.png"), dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved model_agreement.png")

    print(f"\nAll plots saved to {out_dir}/")

if __name__ == "__main__":
    main()
