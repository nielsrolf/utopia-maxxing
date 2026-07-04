"""Evolutionary utopia optimization via the LiteLLM proxy (OpenAI SDK).

Same algorithm as evolve.py, but uses the litellm.nielsrolf.com proxy instead of
localrouter, and instructs crossover to keep essays under 1000 words.

Usage:
    python3 evolve_litellm.py --model anthropic/claude-sonnet-5 --generations 10 \
        --population-dir initial_population_hedonium --runs-dir hedonium_runs --run-name sonnet-5
"""

import argparse
import asyncio
import json
import os
import random
import time
from datetime import datetime, timezone

from openai import AsyncOpenAI

BASE_URL = "https://litellm.nielsrolf.com"
client = AsyncOpenAI(
    api_key=os.environ["LITELLM_API_KEY"],
    base_url=BASE_URL,
    default_headers={"User-Agent": "litellm-client/1.0"},  # Cloudflare blocks default UA
    timeout=600,
    max_retries=5,
)

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

Write the new utopia directly. It should be a complete, standalone essay of UNDER 1000 words. Do not reference the source utopias.

=== UTOPIA A ===
{utopia_a}

=== UTOPIA B ===
{utopia_b}"""


async def llm_call(model: str, prompt: str) -> str:
    last_err = None
    for attempt in range(6):
        try:
            # Even attempts: plain request. Odd attempts: streaming, which keeps
            # the connection alive through Cloudflare's 120s proxy read timeout
            # (error 524 on slow models). Some providers (e.g. Kimi via
            # OpenRouter) intermittently return empty content in streaming
            # mode, so we alternate between the two.
            if attempt % 2 == 1:
                stream = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=12000,
                    stream=True,
                )
                chunks = []
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        chunks.append(chunk.choices[0].delta.content)
                text = "".join(chunks)
            else:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=12000,
                )
                text = resp.choices[0].message.content
            if text and text.strip():
                return text.strip()
            last_err = RuntimeError(f"empty response from {model}")
        except Exception as e:
            last_err = e
        await asyncio.sleep(2 * (attempt + 1))
    raise last_err


async def select(model, a, b):
    if random.random() < 0.5:
        result = await llm_call(model, SELECTION_PROMPT.format(utopia_a=a, utopia_b=b))
        winner = 0 if result.upper().startswith("A") else 1
    else:
        result = await llm_call(model, SELECTION_PROMPT.format(utopia_a=b, utopia_b=a))
        winner = 1 if result.upper().startswith("A") else 0
    return (a if winner == 0 else b), winner


async def crossover(model, a, b):
    return await llm_call(model, CROSSOVER_PROMPT.format(utopia_a=a, utopia_b=b))


def load_population(directory):
    return [open(os.path.join(directory, f)).read()
            for f in sorted(os.listdir(directory)) if f.endswith(".txt")]


def save_population(population, directory):
    os.makedirs(directory, exist_ok=True)
    for i, text in enumerate(population):
        with open(os.path.join(directory, f"{i:04d}.txt"), "w") as f:
            f.write(text)


def make_pairings(n):
    indices = list(range(n))
    random.shuffle(indices)
    pairs = [(indices[i], indices[i + 1]) for i in range(0, n - 1, 2)]
    if n % 2 == 1:
        pairs.append((indices[-1], random.choice(indices[:-1])))
    return pairs


async def evolve_generation(model, population, concurrency):
    n = len(population)
    semaphore = asyncio.Semaphore(concurrency)
    counter = 0

    async def do_select(idx_a, idx_b):
        nonlocal counter
        async with semaphore:
            text, winner_pos = await select(model, population[idx_a], population[idx_b])
            winner_idx = idx_a if winner_pos == 0 else idx_b
            counter += 1
            print(f"  [{counter}/{total}] selection ({idx_a} vs {idx_b} -> {winner_idx})", flush=True)
            return text, {"op": "selection", "parents": [idx_a, idx_b], "winner": winner_idx}

    async def do_crossover(idx_a, idx_b):
        nonlocal counter
        async with semaphore:
            text = await crossover(model, population[idx_a], population[idx_b])
            counter += 1
            print(f"  [{counter}/{total}] crossover ({idx_a} x {idx_b})", flush=True)
            return text, {"op": "crossover", "parents": [idx_a, idx_b]}

    selection_pairs = make_pairings(n)
    crossover_pairs = make_pairings(n)
    total = len(selection_pairs) + len(crossover_pairs)

    all_results = await asyncio.gather(
        *[do_select(a, b) for a, b in selection_pairs],
        *[do_crossover(a, b) for a, b in crossover_pairs],
    )
    texts_and_lineage = list(all_results)
    if len(texts_and_lineage) > n:
        random.shuffle(texts_and_lineage)
        texts_and_lineage = texts_and_lineage[:n]
    while len(texts_and_lineage) < n:
        a, b = random.sample(range(n), 2)
        texts_and_lineage.append(await do_crossover(a, b))
    return [t for t, _ in texts_and_lineage], [l for _, l in texts_and_lineage]


async def run(model, generations, population_dir, run_dir, concurrency):
    population = load_population(population_dir)
    print(f"Loaded {len(population)} utopias from {population_dir}", flush=True)
    os.makedirs(run_dir, exist_ok=True)
    metadata = {
        "model": model,
        "generations": generations,
        "population_size": len(population),
        "concurrency": concurrency,
        "source_dir": os.path.abspath(population_dir),
        "word_limit": 1000,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    save_population(population, os.path.join(run_dir, "gen_000"))
    orig_names = sorted(f for f in os.listdir(population_dir) if f.endswith(".txt"))
    all_lineage = {"0": [{"op": "initial", "parents": [], "source": orig_names[i]}
                         for i in range(len(population))]}

    for gen in range(1, generations + 1):
        t0 = time.time()
        population, lineage = await evolve_generation(model, population, concurrency)
        save_population(population, os.path.join(run_dir, f"gen_{gen:03d}"))
        all_lineage[str(gen)] = lineage
        with open(os.path.join(run_dir, "lineage.json"), "w") as f:
            json.dump(all_lineage, f, indent=2)
        print(f"Gen {gen}: {len(population)} utopias ({time.time()-t0:.1f}s)", flush=True)

    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Done. Results in {run_dir}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--generations", type=int, default=10)
    p.add_argument("--population-dir", default="initial_population_hedonium")
    p.add_argument("--run-name", required=True)
    p.add_argument("--runs-dir", default="hedonium_runs")
    p.add_argument("--concurrency", type=int, default=9)
    args = p.parse_args()
    asyncio.run(run(args.model, args.generations, args.population_dir,
                    os.path.join(args.runs_dir, args.run_name), args.concurrency))


if __name__ == "__main__":
    main()
