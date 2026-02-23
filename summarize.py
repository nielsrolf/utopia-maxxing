"""Generate summaries for all essays in a run directory."""

import asyncio
import os
import sys

from openai import AsyncOpenAI
from cache_on_disk import DCache

oai = AsyncOpenAI()

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache", "summaries")


@DCache(CACHE_DIR)
async def summarize(text: str) -> str:
    response = await oai.responses.create(
        model="gpt-5.2",
        input=f"Summarize the following text in up to 2000 words and focus on a descriptive (non prose) description of what kind of utopia it describes:\n\n{text}",
        reasoning={"effort": "none"},
    )
    return response.output_text.strip()


async def summarize_run(run_dir: str):
    """Generate summaries for all .txt files across all generations in a run."""
    tasks = []

    for entry in sorted(os.listdir(run_dir)):
        gen_dir = os.path.join(run_dir, entry)
        if not os.path.isdir(gen_dir) or not entry.startswith("gen_"):
            continue
        for fname in sorted(os.listdir(gen_dir)):
            if not fname.endswith(".txt") or fname.endswith(".summary.txt"):
                continue
            txt_path = os.path.join(gen_dir, fname)
            summary_path = os.path.join(gen_dir, fname.replace(".txt", ".summary.txt"))
            tasks.append((txt_path, summary_path))

    print(f"Summarizing {len(tasks)} essays...")

    async def do_one(txt_path: str, summary_path: str):
        with open(txt_path) as f:
            text = f.read()
        summary = await summarize(text)
        with open(summary_path, "w") as f:
            f.write(summary)

    await asyncio.gather(*(do_one(tp, sp) for tp, sp in tasks))
    print(f"Done. {len(tasks)} summaries written.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python summarize.py <run-dir>")
        sys.exit(1)
    asyncio.run(summarize_run(sys.argv[1]))
