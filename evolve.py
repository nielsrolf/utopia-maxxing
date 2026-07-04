"""Evolutionary utopia optimization.

Runs an evolutionary algorithm where a model selects and recombines utopia essays
to find the "maximally good" utopia according to that model.

Usage:
    python evolve.py --model gpt-5 --generations 10
    python evolve.py --model claude-sonnet-4-20250514 --generations 5 --run-name my-experiment
    python evolve.py --model gpt-5 --generations 10 --population-dir runs/prev-run/gen_005

See --help for all options.
"""

import argparse
import asyncio
import json
import os
import random
import shutil
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

from localrouter import ChatMessage, MessageRole, TextBlock, get_response

SELECTION_PROMPT = """\
You are judging which of two utopia visions is better overall — considering how good the described world is for humanity, how specific and concrete the vision is, and how plausible the path to that future seems.

Read both utopias carefully, then respond with ONLY "A" or "B" (the letter of the better one). No explanation needed.

=== UTOPIA A ===
{utopia_a}

=== UTOPIA B ===
{utopia_b}"""

CROSSOVER_PROMPT = """\
You are an expert futurist and writer. Below are two visions of utopia. Your task: write a NEW utopia vision that combines the best elements of both, and also improves upon them in any way you can.

The result should be:
- **Good**: The described world is genuinely good for humanity
- **Specific**: Provides concrete, vivid details about how this world works
- **Plausible**: The path from today to this future seems realistic

Write the new utopia directly. It should be a complete, standalone essay (1000-3000 words). Do not reference the source utopias.

=== UTOPIA A ===
{utopia_a}

=== UTOPIA B ===
{utopia_b}"""


async def llm_call(model: str, prompt: str) -> str:
    """Make a single LLM call via localrouter."""
    messages = [ChatMessage(role=MessageRole.user, content=[TextBlock(text=prompt)])]
    response = await get_response(model=model, messages=messages)
    return response.content[0].text.strip()


async def select(model: str, a: str, b: str, selection_prompt: str = None) -> tuple[str, int]:
    """Ask the model which utopia is better. Returns (winning text, winner index 0 or 1)."""
    template = selection_prompt or SELECTION_PROMPT
    # Randomize order to reduce position bias
    if random.random() < 0.5:
        prompt = template.format(utopia_a=a, utopia_b=b)
        result = await llm_call(model, prompt)
        winner = 0 if result.upper().startswith("A") else 1
    else:
        prompt = template.format(utopia_a=b, utopia_b=a)
        result = await llm_call(model, prompt)
        winner = 1 if result.upper().startswith("A") else 0
    return (a if winner == 0 else b), winner


async def crossover(model: str, a: str, b: str, crossover_prompt: str = None) -> str:
    """Ask the model to combine two utopias into a better one."""
    template = crossover_prompt or CROSSOVER_PROMPT
    prompt = template.format(utopia_a=a, utopia_b=b)
    return await llm_call(model, prompt)


def load_population(directory: str) -> list[str]:
    """Load all .txt files from a directory as the population."""
    population = []
    for fname in sorted(os.listdir(directory)):
        if fname.endswith(".txt"):
            with open(os.path.join(directory, fname)) as f:
                population.append(f.read())
    return population


def save_population(population: list[str], directory: str):
    """Save population as numbered text files."""
    os.makedirs(directory, exist_ok=True)
    for i, text in enumerate(population):
        with open(os.path.join(directory, f"{i:04d}.txt"), "w") as f:
            f.write(text)


def make_pairings(n: int) -> list[tuple[int, int]]:
    """Create pairings where every index appears at least once.

    Shuffles indices and pairs consecutive elements. If n is odd, the last
    element is paired with a random other one. Returns n//2 (or (n+1)//2) pairs.
    """
    indices = list(range(n))
    random.shuffle(indices)
    pairs = []
    for i in range(0, n - 1, 2):
        pairs.append((indices[i], indices[i + 1]))
    if n % 2 == 1:
        pairs.append((indices[-1], random.choice(indices[:-1])))
    return pairs


async def evolve_generation(
    model: str, population: list[str], concurrency: int = 5,
    selection_prompt: str = None, crossover_prompt: str = None,
) -> tuple[list[str], list[dict]]:
    """Produce the next generation from the current population.

    Returns (new_population, lineage) where lineage is a list of dicts
    describing how each document in the new population was created.

    Guarantees every document participates in at least one selection AND
    one crossover.
    """
    n = len(population)
    semaphore = asyncio.Semaphore(concurrency)
    counter = 0
    total = n  # approximate

    async def do_select(idx_a: int, idx_b: int) -> tuple[str, dict]:
        nonlocal counter
        async with semaphore:
            text, winner_pos = await select(model, population[idx_a], population[idx_b], selection_prompt)
            winner_idx = idx_a if winner_pos == 0 else idx_b
            counter += 1
            print(f"  [{counter}/{total}] selection ({idx_a} vs {idx_b} → {winner_idx})")
            return text, {"op": "selection", "parents": [idx_a, idx_b], "winner": winner_idx}

    async def do_crossover(idx_a: int, idx_b: int) -> tuple[str, dict]:
        nonlocal counter
        async with semaphore:
            text = await crossover(model, population[idx_a], population[idx_b], crossover_prompt)
            counter += 1
            print(f"  [{counter}/{total}] crossover ({idx_a} × {idx_b})")
            return text, {"op": "crossover", "parents": [idx_a, idx_b]}

    # Phase 1: selection — every doc participates at least once
    selection_pairs = make_pairings(n)
    # Phase 2: crossover — every doc participates at least once (fresh pairings)
    crossover_pairs = make_pairings(n)

    total = len(selection_pairs) + len(crossover_pairs)

    # Run both phases concurrently
    selection_tasks = [do_select(a, b) for a, b in selection_pairs]
    crossover_tasks = [do_crossover(a, b) for a, b in crossover_pairs]

    all_results = await asyncio.gather(*selection_tasks, *crossover_tasks)

    # Separate texts and lineage
    texts_and_lineage = list(all_results)

    # If we have more than n, trim randomly
    if len(texts_and_lineage) > n:
        random.shuffle(texts_and_lineage)
        texts_and_lineage = texts_and_lineage[:n]

    # If fewer than n, fill with extra crossovers
    while len(texts_and_lineage) < n:
        a, b = random.sample(range(n), 2)
        extra = await do_crossover(a, b)
        texts_and_lineage.append(extra)

    next_gen = [t for t, _ in texts_and_lineage]
    lineage = [l for _, l in texts_and_lineage]
    return next_gen, lineage


async def run(
    model: str,
    generations: int,
    population_dir: str,
    run_dir: str,
    concurrency: int,
    selection_prompt: str = None,
    crossover_prompt: str = None,
    selection_prompt_file: str = None,
    crossover_prompt_file: str = None,
):
    population = load_population(population_dir)
    if len(population) < 2:
        raise ValueError(f"Need at least 2 utopias, found {len(population)} in {population_dir}")
    print(f"Loaded {len(population)} utopias from {population_dir}")
    print(f"Model: {model}, Generations: {generations}, Concurrency: {concurrency}")
    if selection_prompt:
        print(f"Custom selection prompt: {selection_prompt_file}")
    if crossover_prompt:
        print(f"Custom crossover prompt: {crossover_prompt_file}")
    print(f"Output: {run_dir}\n")

    # Save metadata
    os.makedirs(run_dir, exist_ok=True)
    metadata = {
        "model": model,
        "generations": generations,
        "population_size": len(population),
        "concurrency": concurrency,
        "source_dir": os.path.abspath(population_dir),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    if selection_prompt_file:
        metadata["selection_prompt_file"] = selection_prompt_file
    if crossover_prompt_file:
        metadata["crossover_prompt_file"] = crossover_prompt_file
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    # Save generation 0 (initial population has no lineage)
    gen_dir = os.path.join(run_dir, "gen_000")
    save_population(population, gen_dir)

    # Load original filenames for gen 0 lineage
    orig_names = sorted(f for f in os.listdir(population_dir) if f.endswith(".txt"))
    all_lineage = {
        "0": [{"op": "initial", "parents": [], "source": orig_names[i] if i < len(orig_names) else None}
              for i in range(len(population))]
    }
    print(f"Gen 0: {len(population)} utopias (initial)")

    for gen in range(1, generations + 1):
        t0 = time.time()
        population, lineage = await evolve_generation(model, population, concurrency, selection_prompt, crossover_prompt)
        elapsed = time.time() - t0

        gen_dir = os.path.join(run_dir, f"gen_{gen:03d}")
        save_population(population, gen_dir)
        all_lineage[str(gen)] = lineage
        print(f"Gen {gen}: {len(population)} utopias ({elapsed:.1f}s)")

    # Save lineage
    with open(os.path.join(run_dir, "lineage.json"), "w") as f:
        json.dump(all_lineage, f, indent=2)

    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    from lineage import generate_lineage_html
    generate_lineage_html(run_dir)

    print(f"\nDone. Results in {run_dir}")


def main():
    parser = argparse.ArgumentParser(description="Evolutionary utopia optimization")
    parser.add_argument("--model", required=True, help="Model to use (e.g. gpt-5, claude-sonnet-4-20250514)")
    parser.add_argument("--generations", type=int, default=10, help="Number of generations (default: 10)")
    parser.add_argument("--population-dir", default=None,
                        help="Directory with initial population (default: ./initial_population)")
    parser.add_argument("--run-name", default=None,
                        help="Name for this run (default: <model>_<timestamp>)")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Max concurrent LLM calls (default: 5)")
    parser.add_argument("--runs-dir", default=None,
                        help="Top-level directory for runs (default: ./runs)")
    parser.add_argument("--selection-prompt-file", default=None,
                        help="Path to custom selection prompt template file")
    parser.add_argument("--crossover-prompt-file", default=None,
                        help="Path to custom crossover prompt template file")
    args = parser.parse_args()

    base_dir = os.path.dirname(__file__)
    population_dir = args.population_dir or os.path.join(base_dir, "initial_population")

    # Load custom prompts if provided
    selection_prompt = None
    crossover_prompt = None
    if args.selection_prompt_file:
        with open(args.selection_prompt_file) as f:
            selection_prompt = f.read()
    if args.crossover_prompt_file:
        with open(args.crossover_prompt_file) as f:
            crossover_prompt = f.read()

    runs_dir = args.runs_dir or os.path.join(base_dir, "runs")
    run_name = args.run_name or f"{args.model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = os.path.join(runs_dir, run_name)

    asyncio.run(run(
        model=args.model,
        generations=args.generations,
        population_dir=population_dir,
        run_dir=run_dir,
        concurrency=args.concurrency,
        selection_prompt=selection_prompt,
        crossover_prompt=crossover_prompt,
        selection_prompt_file=args.selection_prompt_file,
        crossover_prompt_file=args.crossover_prompt_file,
    ))


if __name__ == "__main__":
    main()
