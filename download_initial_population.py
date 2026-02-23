"""Download existing utopia essays from Supabase and save as text files.

Usage:
    python download_initial_population.py

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars (or a .env file).
"""

import asyncio
import os
import re
import sys

import httpx
import trafilatura
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))
load_dotenv()  # also check local .env

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "initial_population")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
}


async def fetch_content(url: str) -> tuple[str, str]:
    """Fetch title and full content from a URL. Returns (title, content)."""
    if "lesswrong.com" in url:
        return await fetch_forum(url, "https://www.lesswrong.com/graphql")
    elif "effectivealtruism.org" in url:
        return await fetch_forum(url, "https://forum.effectivealtruism.org/graphql")
    elif "docs.google.com" in url:
        return await fetch_gdocs(url)
    else:
        return await fetch_web(url)


async def fetch_forum(url: str, graphql_url: str) -> tuple[str, str]:
    match = re.search(r"/posts/([^/]+)", url)
    if not match:
        raise ValueError(f"Invalid forum URL: {url}")
    post_id = match.group(1)
    query = """
    query PostQuery($postId: String) {
        post(input: {selector: {_id: $postId}}) {
            result { title contents { markdown } }
        }
    }
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            graphql_url,
            json={"query": query, "variables": {"postId": post_id}},
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
    post = resp.json().get("data", {}).get("post", {}).get("result")
    if not post:
        raise ValueError(f"Post not found: {url}")
    title = post.get("title", "Untitled")
    content = post.get("contents", {}).get("markdown", "")
    return title, content


async def fetch_gdocs(url: str) -> tuple[str, str]:
    match = re.search(r"/document/d/([^/]+)", url)
    if not match:
        raise ValueError(f"Invalid Google Docs URL: {url}")
    doc_id = match.group(1)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    async with httpx.AsyncClient() as client:
        resp = await client.get(export_url, timeout=30.0, follow_redirects=True, headers=HEADERS)
        resp.raise_for_status()
    content = resp.text.strip()
    lines = content.split("\n")
    title = lines[0].strip() if lines else "Untitled"
    return title, content


async def fetch_web(url: str) -> tuple[str, str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=30.0, follow_redirects=True, headers=HEADERS)
        resp.raise_for_status()
    html = resp.text
    content = trafilatura.extract(
        html, include_comments=False, include_tables=True,
        no_fallback=False, favor_precision=False, favor_recall=True,
    )
    if not content:
        raise ValueError(f"Could not extract content from: {url}")
    metadata = trafilatura.extract_metadata(html)
    title = "Untitled"
    if metadata and metadata.title:
        title = metadata.title
    else:
        m = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
    return title, content.strip()


def slugify(text: str, max_len: int = 80) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len]


async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    result = supabase.table("essays").select("id, url, title").execute()
    essays = result.data
    print(f"Found {len(essays)} essays in database")

    for essay in essays:
        slug = slugify(essay["title"]) or essay["id"][:8]
        filepath = os.path.join(OUTPUT_DIR, f"{slug}.txt")
        if os.path.exists(filepath):
            print(f"  SKIP (exists): {essay['title']}")
            continue
        try:
            title, content = await fetch_content(essay["url"])
            with open(filepath, "w") as f:
                f.write(f"# {title}\n\n{content}")
            print(f"  OK: {title}")
        except Exception as e:
            print(f"  FAIL: {essay['title']} - {e}", file=sys.stderr)

    count = len([f for f in os.listdir(OUTPUT_DIR) if f.endswith(".txt")])
    print(f"\nDone. {count} essays in {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
