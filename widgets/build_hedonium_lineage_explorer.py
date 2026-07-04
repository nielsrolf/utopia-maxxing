"""Build the lineage-explorer widget for the hedonium experiment.

Regenerates lineage.html for the Claude Sonnet 5 hedonium run using the repo's
existing lineage.py (self-contained output, no external JS/CSS), then copies it
into assets/hedonium_lineage_explorer.html for embedding as a document widget.

Usage:
    python3 widgets/build_hedonium_lineage_explorer.py
"""
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import lineage  # noqa: E402

RUN_DIR = os.path.join(BASE_DIR, "hedonium_runs", "sonnet-5")
OUT_PATH = os.path.join(BASE_DIR, "assets", "hedonium_lineage_explorer.html")


def main():
    lineage.generate_lineage_html(RUN_DIR)
    shutil.copyfile(os.path.join(RUN_DIR, "lineage.html"), OUT_PATH)
    print(f"Wrote {OUT_PATH} ({os.path.getsize(OUT_PATH)} bytes)")


if __name__ == "__main__":
    main()
