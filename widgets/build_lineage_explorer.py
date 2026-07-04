"""Build the interactive lineage-explorer widget embedded in the paper.

Regenerates lineage.html for the featured baseline run (GPT-5's 20-generation
run -- the run with the most extreme within-generation monoculture) using the
repo's existing lineage.py, then copies the self-contained output into
assets/lineage_explorer.html so it can be embedded as a document widget.

lineage.py reads only local files (lineage.json, metadata.json, per-generation
.txt/.summary.txt) -- no network calls, no external JS/CSS -- so the output is
fully self-contained and safe to serve under a strict CSP.

Usage:
    python widgets/build_lineage_explorer.py
"""
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import lineage  # noqa: E402

RUN_DIR = os.path.join(BASE_DIR, "runs", "gpt-5_20260222_164038")
OUT_PATH = os.path.join(BASE_DIR, "assets", "lineage_explorer.html")


def main():
    lineage.generate_lineage_html(RUN_DIR)
    src = os.path.join(RUN_DIR, "lineage.html")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    shutil.copyfile(src, OUT_PATH)
    print(f"Wrote {OUT_PATH} ({os.path.getsize(OUT_PATH)} bytes)")


if __name__ == "__main__":
    main()
