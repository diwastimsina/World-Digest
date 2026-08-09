"""
World Digest — a zero-cost news agent.

Runs on a schedule (GitHub Actions cron), pulls free RSS feeds + Hacker News,
dedupes against seen.json, ranks by keyword score, optionally summarizes with
Gemini's free tier if GEMINI_API_KEY is set, and sends a digest via Telegram.

Required env vars (set as GitHub repo secrets):
  TELEGRAM_BOT_TOKEN   from @BotFather on Telegram (free)
  TELEGRAM_CHAT_ID     your chat id (message the bot, then hit getUpdates)
Optional:
  GEMINI_API_KEY       free key from https://aistudio.google.com (upgrades
                       headlines into short "why it matters" summaries)
  GEMINI_MODEL         model to summarize with (default: gemini-3.5-flash)
"""

import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
import yaml

ROOT = Path(__file__).parent
SEEN_FILE = ROOT / "seen.json"
MAX_SEEN = 3000  # cap file growth


# ---------- state ----------

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_seen(seen: set) -> None:
    trimmed = list(seen)[-MAX_SEEN:]
    SEEN_FILE.write_text(json.dumps(trimmed, indent=0))


def item_id(title: str, link: str) -> str:
    # Hash on normalized title so the same story from two feeds dedupes.
    norm = re.sub(r"\W+", "", (title or "").lower())[:120]
    return hashlib.sha1((norm or link).encode()).hexdigest()[:16]


# ---------- fetching ----------

def fetch_feed(url: str) -> list:
    try:
        parsed = feedparser.parse(url, request_headers={"User-Agent": "world-digest/1.0"})
        out = []
        for e in parsed.entries[:25]:
            out.append({
                "title": (e.get("title") or "").strip(),
                "link": e.get("link", ""),
                "summary": re.sub(r"<[^>]+>", "", e.get("summary", ""))[:400],
                "source": parsed.feed.get("title", url.split("/")[2]),
            })
        return out
    except Exception as exc:
        print(f"  feed failed: {url} ({exc})", file=sys.stderr)
        return []


def fetch_hn(keywords: list) -> list:
    """Free Hacker News Algolia API, front-page-quality stories only."""
    try:
        q = " OR ".join(keywords[:6]) if keywords else "ai"
        r = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": q, "tags": "story", "numericFilters": "points>80"},
            timeout=15,
        )
        hits = r.json().get("hits", [])[:10]
        return [{
            "title": h.get("title", ""),
            "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "summary": f"{h.get('points', 0)} points on Hacker News",
            "source": "Hacker News",
        } for h in hits]
    except Exception as exc:
        print(f"  HN failed ({exc})", file=sys.stderr)
        return []


# ---------- ranking ----------

def score_item(item: dict, kw: dict) -> int:
    text = f"{item['title']} {item['summary']}".lower()
    score = 0
    for k in kw.get("high", []):
        if k.lower() in text:
            score += 3
    for k in kw.get("topic", []):
        if k.lower() in text:
            score += 1
    return score


# ---------- optional free-tier LLM summarization ----------

def gemini_summarize(section_name: str, items: list) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    listing = "\n".join(f"- {i['title']} ({i['source']}): {i['summary']}" for i in items)
    prompt = (
        f"You are writing one section of a personal news digest: {section_name}. "
        f"Given these items, write a 2-3 sentence synthesis of the most important "
        f"developments and why they matter. Plain text, no markdown, no preamble.\n\n{listing}"
    )
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as exc:
        print(f"  gemini skipped ({exc})", file=sys.stderr)
        return None


# ---------- delivery ----------

def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("No Telegram secrets set; printing digest instead.\n")
        print(text)
        return
    # Telegram caps messages at 4096 chars; split if needed.
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
    for chunk in chunks:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
        time.sleep(1)


# ---------- rendering ----------

def format_telegram(sections: list, now: str) -> str:
    blocks = []
    for s in sections:
        lines = [f"<b>{s['emoji']} {s['name']}</b>"]
        if s["synthesis"]:
            lines.append(f"<i>{s['synthesis']}</i>")
        for it in s["items"]:
            lines.append(f"• <a href=\"{it['link']}\">{it['title']}</a> — {it['source']}")
        blocks.append("\n".join(lines))
    return f"<b>📰 World Digest</b> · {now}\n\n" + "\n\n".join(blocks)


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>World Digest</title>
<style>
  :root {{
    --bg: #faf8f3; --ink: #1c1b18; --muted: #6f6a5d;
    --rule: #d9d3c5; --link: #1c1b18;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #16140f; --ink: #e9e5da; --muted: #a09884;
      --rule: #3b362b; --link: #e9e5da;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--ink);
    font-family: Georgia, 'Times New Roman', serif;
    max-width: 42rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem;
    line-height: 1.55;
  }}
  header {{ text-align: center; margin-bottom: 2.25rem; }}
  header h1 {{
    font-size: 2.5rem; font-weight: 700; letter-spacing: .01em;
    margin: 0 0 .35rem; border-top: 3px double var(--ink);
    border-bottom: 3px double var(--ink); padding: .5rem 0;
  }}
  header .dateline {{
    font-size: .78rem; text-transform: uppercase; letter-spacing: .18em;
    color: var(--muted);
  }}
  section {{ margin-top: 2.25rem; }}
  section h2 {{
    font-size: .85rem; text-transform: uppercase; letter-spacing: .16em;
    border-bottom: 1px solid var(--rule); padding-bottom: .4rem;
    margin: 0 0 .9rem;
  }}
  .synthesis {{
    font-style: italic; font-size: 1.02rem; color: var(--muted);
    margin: 0 0 1.1rem; padding-left: .9rem;
    border-left: 2px solid var(--rule);
  }}
  ul {{ list-style: none; margin: 0; padding: 0; }}
  li {{ margin: 0 0 .8rem; }}
  li a {{
    color: var(--link); font-weight: 700; text-decoration: none;
    border-bottom: 1px solid var(--rule);
  }}
  li a:hover {{ border-bottom-color: var(--ink); }}
  .source {{
    display: block; font-size: .75rem; text-transform: uppercase;
    letter-spacing: .12em; color: var(--muted); margin-top: .15rem;
  }}
  footer {{
    margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--rule);
    text-align: center; font-size: .75rem; color: var(--muted);
    text-transform: uppercase; letter-spacing: .14em;
  }}
</style>
</head>
<body>
<header>
  <h1>World Digest</h1>
  <div class="dateline">{now}</div>
</header>
{sections}
<footer>End of digest</footer>
</body>
</html>
"""


def render_html(sections: list, now: str) -> str:
    parts = []
    for s in sections:
        block = [f"<section>\n<h2>{html.escape(s['emoji'])} {html.escape(s['name'])}</h2>"]
        if s["synthesis"]:
            block.append(f"<p class=\"synthesis\">{html.escape(s['synthesis'])}</p>")
        block.append("<ul>")
        for it in s["items"]:
            block.append(
                f"<li><a href=\"{html.escape(it['link'], quote=True)}\">{html.escape(it['title'])}</a>"
                f"<span class=\"source\">{html.escape(it['source'])}</span></li>"
            )
        block.append("</ul>\n</section>")
        parts.append("\n".join(block))
    return HTML_PAGE.format(now=html.escape(now), sections="\n".join(parts))


def save_html(sections: list, now: str) -> None:
    try:
        (ROOT / "digest.html").write_text(render_html(sections, now))
        print("Saved digest.html")
    except Exception as exc:
        print(f"  html skipped ({exc})", file=sys.stderr)


# ---------- main ----------

def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    settings = cfg.get("settings", {})
    default_max = settings.get("max_items_per_section", 5)
    min_score = settings.get("min_score_to_include", 2)

    seen = load_seen()
    new_seen = set(seen)
    now = datetime.now(timezone.utc).strftime("%a %b %d, %H:%M UTC")
    sections_out = []

    for section in cfg["sections"]:
        name, kw = section["name"], section.get("keywords", {})
        max_items = section.get("max_items", default_max)
        print(f"Section: {name}")

        items = []
        for url in section.get("feeds", []):
            items += fetch_feed(url)
        if section.get("hn_query"):
            items += fetch_hn(kw.get("topic", []))

        fresh = []
        for it in items:
            iid = item_id(it["title"], it["link"])
            if iid in seen or not it["title"]:
                continue
            it["score"] = score_item(it, kw)
            it["id"] = iid
            fresh.append(it)

        fresh.sort(key=lambda x: x["score"], reverse=True)
        picked = [i for i in fresh if i["score"] >= min_score][:max_items]
        # World section keywords are broad; fall back to newest if scoring is thin.
        if not picked and fresh and not kw.get("topic"):
            picked = fresh[:max_items]

        for it in picked:
            new_seen.add(it["id"])

        if not picked:
            continue

        sections_out.append({
            "name": name,
            "emoji": section.get("emoji", ""),
            "synthesis": gemini_summarize(name, picked),
            "items": picked,
        })

    if not sections_out:
        print("Quiet cycle: nothing above threshold, no message sent.")
        save_seen(new_seen)
        return

    send_telegram(format_telegram(sections_out, now))
    save_html(sections_out, now)
    save_seen(new_seen)
    print("Digest sent.")


if __name__ == "__main__":
    main()
