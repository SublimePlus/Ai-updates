#!/usr/bin/env python3
"""Daily AI news pipeline.

1. Fetch candidate stories from blogs (RSS), YouTube (RSS), Reddit (JSON),
   Hacker News (Algolia API) and arXiv (Atom) — all free, keyless endpoints.
2. Score by recency + engagement + source weight, dedupe, pick a diverse top 10.
3. Summarize with the free GitHub Models API (falls back to feed excerpts).
4. Write site/data/news.json for the dashboard.

Stdlib only — no pip installs needed in CI.
"""
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import github_models

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "site", "data", "news.json")

USER_AGENT = "SublimeAISignal/1.0 (daily AI news digest; github.com/sublimeplus/ai-updates)"
MAX_AGE_HOURS = 72
TOP_N = 10

# (name, url, category, weight)
RSS_FEEDS = [
    ("OpenAI Blog", "https://openai.com/news/rss.xml", "blog", 1.30),
    ("Anthropic News", "https://www.anthropic.com/news/rss.xml", "blog", 1.30),
    ("Google AI Blog", "https://blog.google/technology/ai/rss/", "blog", 1.25),
    ("DeepMind Blog", "https://deepmind.google/blog/rss.xml", "blog", 1.25),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "blog", 1.20),
    ("MIT Tech Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "news", 1.15),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "news", 1.10),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "news", 1.00),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "news", 1.05),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", "blog", 1.15),
]

# YouTube channel RSS needs no API key: /feeds/videos.xml?channel_id=...
YOUTUBE_CHANNELS = [
    ("Two Minute Papers", "UCbfYPyITQ-7l4upoX8nvctg"),
    ("AI Explained", "UCNJ1Ymd5yFuUPtn21xtRbbw"),
    ("Matt Wolfe", "UChpleBmo18P08aKCIgti38g"),
    ("Fireship", "UCsBjURrPoezykLs9EqgamOA"),
]

SUBREDDITS = ["artificial", "MachineLearning", "LocalLLaMA", "OpenAI", "singularity"]

AI_PATTERN = re.compile(
    r"\b(ai|a\.i\.|llm|llms|gpt[-\s]?[45o]?|claude|gemini|openai|anthropic|deepmind|"
    r"mistral|llama|qwen|deepseek|grok|copilot|hugging\s?face|transformer|neural|"
    r"machine[- ]learning|deep[- ]learning|agentic|ai agent|rag|fine[- ]?tun\w*|"
    r"diffusion|multimodal|chatbot|genai|open[- ]?weight|foundation model|"
    r"text[- ]to[- ](image|video|speech)|inference|reasoning model)\b",
    re.IGNORECASE,
)

BIG_NEWS_PATTERN = re.compile(
    r"\b(releas\w+|launch\w+|announc\w+|unveil\w+|open[- ]sourc\w+|breakthrough|"
    r"record|first|beats?|outperform\w+|partners?\w*|acqui\w+|funding|raises)\b",
    re.IGNORECASE,
)


def log(msg):
    print(msg, flush=True)


def http_get(url, timeout=25, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:
            if attempt == retries:
                log(f"  ! skipping {url}: {e}")
                return None
            time.sleep(2 * (attempt + 1))


def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def localname(tag):
    return tag.rsplit("}", 1)[-1]


def parse_feed_xml(xml_text):
    """Yield dicts from either RSS <item> or Atom <entry> elements."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log(f"  ! feed parse error: {e}")
        return
    for el in root.iter():
        if localname(el.tag) not in ("item", "entry"):
            continue
        entry = {"title": None, "link": None, "desc": "", "date": None}
        for child in el:
            name = localname(child.tag)
            text = (child.text or "").strip()
            if name == "title":
                entry["title"] = strip_tags(text)
            elif name == "link":
                entry["link"] = child.get("href") or text or entry["link"]
            elif name in ("description", "summary", "content"):
                if not entry["desc"]:
                    entry["desc"] = strip_tags(text)[:500]
            elif name in ("pubDate", "published", "updated", "date"):
                entry["date"] = entry["date"] or parse_date(text)
        if entry["title"] and entry["link"]:
            yield entry


def make_item(title, url, source, category, published, engagement_n, engagement_label, desc, weight):
    return {
        "title": title.strip(),
        "url": url,
        "source": source,
        "category": category,
        "published": published,
        "engagementN": engagement_n,
        "engagement": engagement_label,
        "desc": (desc or "").strip()[:500],
        "weight": weight,
    }


def fetch_rss_sources(now):
    items = []
    for name, url, category, weight in RSS_FEEDS:
        body = http_get(url)
        if not body:
            continue
        count = 0
        for e in parse_feed_xml(body):
            if not e["date"] or (now - e["date"]) > timedelta(hours=MAX_AGE_HOURS):
                continue
            text = f"{e['title']} {e['desc']}"
            # curated AI feeds pass automatically; general feeds must match
            if category == "news" and not AI_PATTERN.search(text):
                continue
            items.append(
                make_item(e["title"], e["link"], name, category, e["date"], None, "", e["desc"], weight)
            )
            count += 1
        log(f"  {name}: {count} fresh items")
    return items


def fetch_youtube(now):
    items = []
    for name, channel_id in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        body = http_get(url)
        if not body:
            continue
        count = 0
        for e in parse_feed_xml(body):
            if not e["date"] or (now - e["date"]) > timedelta(hours=MAX_AGE_HOURS):
                continue
            if not AI_PATTERN.search(f"{e['title']} {e['desc']}"):
                continue
            items.append(
                make_item(e["title"], e["link"], f"YouTube · {name}", "video", e["date"], None, "", e["desc"], 1.10)
            )
            count += 1
        log(f"  YouTube {name}: {count} fresh items")
    return items


def fetch_reddit(now):
    items = []
    for sub in SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=15&raw_json=1"
        body = http_get(url)
        if not body:
            continue
        try:
            posts = json.loads(body)["data"]["children"]
        except (KeyError, ValueError):
            continue
        count = 0
        for post in posts:
            d = post.get("data", {})
            if d.get("stickied") or d.get("over_18"):
                continue
            created = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
            if (now - created) > timedelta(hours=MAX_AGE_HOURS):
                continue
            score = int(d.get("score", 0))
            if score < 100:
                continue
            title = d.get("title", "")
            if not AI_PATTERN.search(f"{title} {d.get('selftext', '')[:300]}"):
                continue
            items.append(
                make_item(
                    title,
                    "https://www.reddit.com" + d.get("permalink", ""),
                    f"r/{sub}",
                    "social",
                    created,
                    score,
                    f"{score:,} upvotes on r/{sub}",
                    d.get("selftext", "")[:400],
                    0.95,
                )
            )
            count += 1
        log(f"  r/{sub}: {count} fresh items")
    return items


def fetch_hackernews(now):
    items = []
    cutoff = int((now - timedelta(hours=36)).timestamp())
    urls = [
        "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=60",
        f"https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=60&numericFilters=points%3E80,created_at_i%3E{cutoff}",
    ]
    seen = set()
    for url in urls:
        body = http_get(url)
        if not body:
            continue
        try:
            hits = json.loads(body).get("hits", [])
        except ValueError:
            continue
        for h in hits:
            oid = h.get("objectID")
            title = h.get("title") or ""
            if not oid or oid in seen or not AI_PATTERN.search(title):
                continue
            created = parse_date(h.get("created_at"))
            if not created or (now - created) > timedelta(hours=MAX_AGE_HOURS):
                continue
            seen.add(oid)
            points = int(h.get("points") or 0)
            items.append(
                make_item(
                    title,
                    h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                    "Hacker News",
                    "social",
                    created,
                    points,
                    f"{points:,} points on Hacker News",
                    "",
                    1.15,
                )
            )
    log(f"  Hacker News: {len(items)} fresh items")
    return items


def fetch_arxiv(now):
    query = urllib.parse.urlencode(
        {
            "search_query": "cat:cs.AI OR cat:cs.LG OR cat:cs.CL",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": "20",
        }
    )
    body = http_get(f"https://export.arxiv.org/api/query?{query}")
    items = []
    if body:
        for e in parse_feed_xml(body):
            if not e["date"] or (now - e["date"]) > timedelta(hours=MAX_AGE_HOURS):
                continue
            items.append(
                make_item(e["title"], e["link"], "arXiv", "research", e["date"], None, "", e["desc"], 0.70)
            )
    log(f"  arXiv: {len(items)} fresh items")
    return items


def title_tokens(title):
    return set(re.findall(r"[a-z0-9]{3,}", title.lower()))


def dedupe(items):
    kept = []
    for item in sorted(items, key=lambda i: i["score"], reverse=True):
        tokens = title_tokens(item["title"])
        duplicate = False
        for other in kept:
            inter = tokens & other["_tokens"]
            union = tokens | other["_tokens"]
            if union and len(inter) / len(union) > 0.55:
                duplicate = True
                break
            if item["url"].rstrip("/") == other["url"].rstrip("/"):
                duplicate = True
                break
        if not duplicate:
            item["_tokens"] = tokens
            kept.append(item)
    for item in kept:
        item.pop("_tokens", None)
    return kept


def score_items(items, now):
    for item in items:
        age_h = max(0.0, (now - item["published"]).total_seconds() / 3600)
        recency = max(0.0, 1.0 - age_h / MAX_AGE_HOURS)
        if item["engagementN"]:
            engagement = min(1.0, math.log10(item["engagementN"] + 1) / 3.0)
        else:
            engagement = 0.45  # curated sources without vote counts
        boost = 0.15 if BIG_NEWS_PATTERN.search(item["title"]) else 0.0
        item["score"] = (0.45 * recency + 0.40 * engagement + boost) * item["weight"]
    return items


def pick_top(items, n=TOP_N):
    """Greedy pick with diversity: max 2 per source, max 4 per category."""
    picked = []
    per_source, per_category = {}, {}
    for item in items:  # items arrive sorted by score desc
        if len(picked) >= n:
            break
        if per_source.get(item["source"], 0) >= 2:
            continue
        if per_category.get(item["category"], 0) >= 4:
            continue
        picked.append(item)
        per_source[item["source"]] = per_source.get(item["source"], 0) + 1
        per_category[item["category"]] = per_category.get(item["category"], 0) + 1
    # backfill if diversity constraints left empty slots
    for item in items:
        if len(picked) >= n:
            break
        if item not in picked:
            picked.append(item)
    return picked


DIGEST_SYSTEM = (
    "You are the editor of a personal daily AI briefing for a builder who is "
    "creating a startup called Sublime. For every news item you receive, write:\n"
    "1. summary: 2 plain-English sentences a busy person understands instantly.\n"
    "2. life_idea: ONE concrete, specific thing they can try TODAY in daily "
    "life or work using only free tools (start with a verb, max 35 words).\n"
    "3. sublime_angle: ONE sentence on how this news could help them build "
    "their company Sublime (product idea, cost saving, or skill to learn).\n"
    "Reply with ONLY a JSON array: "
    '[{"rank": <int>, "summary": "...", "life_idea": "...", "sublime_angle": "..."}]'
)


def summarize(items):
    """Enrich items via GitHub Models in batches of 5. Returns True if AI ran."""
    if not github_models.available():
        log("GITHUB_TOKEN not set — using feed excerpts instead of AI summaries")
        apply_fallback(items)
        return False
    ok = True
    for start in range(0, len(items), 5):
        batch = items[start : start + 5]
        payload = [
            {
                "rank": item["rank"],
                "title": item["title"],
                "source": item["source"],
                "category": item["category"],
                "excerpt": item["desc"][:350],
            }
            for item in batch
        ]
        try:
            reply = github_models.chat(
                [
                    {"role": "system", "content": DIGEST_SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                max_tokens=2500,
            )
            by_rank = {row["rank"]: row for row in github_models.extract_json(reply)}
            for item in batch:
                row = by_rank.get(item["rank"], {})
                item["summary"] = row.get("summary") or fallback_summary(item)
                item["lifeIdea"] = row.get("life_idea") or fallback_idea(item)
                item["sublimeAngle"] = row.get("sublime_angle") or fallback_angle(item)
            log(f"  summarized items {batch[0]['rank']}–{batch[-1]['rank']}")
        except Exception as e:
            log(f"  ! AI summarization failed for batch: {e}")
            apply_fallback(batch)
            ok = False
        time.sleep(5)  # stay well under free-tier rate limits
    return ok


def fallback_summary(item):
    return item["desc"][:280] or f"{item['title']} — via {item['source']}."


def fallback_idea(item):
    by_category = {
        "video": "Watch this video at 1.5x speed over coffee and write down one technique to try this week.",
        "research": "Read just the abstract and ask a free AI chat to explain it like you're twelve.",
        "social": "Skim the top 5 comments in the thread — practitioners often share the real-world catch there.",
    }
    return by_category.get(
        item["category"],
        "Read the article, then explain it out loud in 30 seconds — if you can't, reread the intro.",
    )


def fallback_angle(item):
    return "Track this trend — knowing it before competitors is an edge for Sublime."


def apply_fallback(items):
    for item in items:
        item.setdefault("summary", fallback_summary(item))
        item.setdefault("lifeIdea", fallback_idea(item))
        item.setdefault("sublimeAngle", fallback_angle(item))


def main():
    now = datetime.now(timezone.utc)
    log(f"Fetching sources at {now.isoformat()}")
    items = []
    items += fetch_rss_sources(now)
    items += fetch_youtube(now)
    items += fetch_reddit(now)
    items += fetch_hackernews(now)
    items += fetch_arxiv(now)
    log(f"Total candidates: {len(items)}")

    if len(items) < 3:
        log("Too few items fetched — keeping the existing news.json untouched")
        sys.exit(0 if os.path.exists(OUT_PATH) else 1)

    items = score_items(items, now)
    items = dedupe(items)
    items.sort(key=lambda i: i["score"], reverse=True)
    top = pick_top(items)
    for rank, item in enumerate(top, 1):
        item["rank"] = rank

    ai_ok = summarize(top)

    output = {
        "updatedAt": now.isoformat(timespec="seconds"),
        "generator": "github-actions",
        "model": github_models.MODEL if ai_ok else None,
        "aiGenerated": ai_ok,
        "items": [
            {
                "rank": i["rank"],
                "title": i["title"],
                "url": i["url"],
                "source": i["source"],
                "category": i["category"],
                "publishedAt": i["published"].isoformat(timespec="seconds"),
                "engagement": i["engagement"],
                "summary": i["summary"],
                "lifeIdea": i["lifeIdea"],
                "sublimeAngle": i["sublimeAngle"],
            }
            for i in top
        ],
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log(f"Wrote {OUT_PATH} with {len(top)} items (aiGenerated={ai_ok})")


if __name__ == "__main__":
    main()
