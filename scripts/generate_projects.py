#!/usr/bin/env python3
"""Generate 3-5 hands-on mini-projects from the current top-10 AI news,
each with a Coursera-style walkthrough (modules -> lessons -> checkpoints).

Runs in the manual "Generate Projects" GitHub Actions workflow using the
free GitHub Models API. If generation fails, the existing projects.json is
left untouched so the site never breaks.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import github_models

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_PATH = os.path.join(ROOT, "site", "data", "news.json")
OUT_PATH = os.path.join(ROOT, "site", "data", "projects.json")

IDEAS_SYSTEM = (
    "You design tiny hands-on learning projects for a busy startup founder "
    "(building a company called Sublime) who wants to keep up with AI by "
    "building, not just reading.\n"
    "From the news items provided, propose EXACTLY 4 mini-projects. Rules:\n"
    "- Each takes 1-4 hours total, beginner-to-intermediate friendly.\n"
    "- Must be buildable with FREE tools only and WITHOUT creating accounts "
    "on new platforms (GitHub, a laptop, Python/JS, local open-source tools, "
    "and free keyless APIs are fine).\n"
    "- Each must teach a skill connected to one of the news items.\n"
    "- Prefer projects that could later feed into building a startup.\n"
    "Reply with ONLY a JSON array of 4 objects:\n"
    '[{"id": "kebab-case-slug", "title": "...", "tagline": "one line", '
    '"inspiredBy": "<title of the news item>", "difficulty": "Beginner|Intermediate", '
    '"timeEstimate": "~2 hours", "skills": ["..","..",".."], '
    '"outcome": "what exists at the end", "stretchGoals": ["..",".."]}]'
)

WALKTHROUGH_SYSTEM = (
    "You write warm, clear, Coursera-style course content. Given a mini-project "
    "spec, produce its full walkthrough as JSON with EXACTLY this shape:\n"
    '{"modules": [{"title": "Module 1: ...", "lessons": [{"title": "...", '
    '"duration": "10 min", "content": "markdown text", "code": "optional code or empty string", '
    '"checkpoint": "one concrete way the learner verifies this lesson worked"}]}]}\n'
    "Rules:\n"
    "- Exactly 3 modules; 2-3 lessons each; total fits the project's time estimate.\n"
    "- content: 120-220 words of markdown. Explain WHY before HOW. Assume "
    "beginner-to-intermediate. No fluff, no marketing tone.\n"
    "- code: complete runnable snippets (with language noted in content), or \"\".\n"
    "- Use only free tools, no new platform accounts.\n"
    "- Module 1 always starts from zero (setup included). Module 3 ends with "
    "the finished artifact plus one lesson connecting the skill back to the "
    "news item and to building a startup.\n"
    "Reply with ONLY the JSON object."
)


def log(msg):
    print(msg, flush=True)


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "project"


def main():
    if not github_models.available():
        log("GITHUB_TOKEN is required to generate projects")
        sys.exit(1)
    with open(NEWS_PATH, encoding="utf-8") as f:
        news = json.load(f)

    headlines = [
        {"title": i["title"], "summary": i.get("summary", "")[:200], "category": i["category"]}
        for i in news["items"]
    ]
    log(f"Designing projects from {len(headlines)} news items…")
    reply = github_models.chat(
        [
            {"role": "system", "content": IDEAS_SYSTEM},
            {"role": "user", "content": json.dumps(headlines, ensure_ascii=False)},
        ],
        max_tokens=2000,
        temperature=0.8,
    )
    specs = github_models.extract_json(reply)
    if not isinstance(specs, list) or not 3 <= len(specs) <= 5:
        log(f"Unexpected project spec shape ({type(specs)}, {len(specs) if isinstance(specs, list) else '-'}) — aborting")
        sys.exit(1)

    projects = []
    for spec in specs:
        spec["id"] = slugify(spec.get("id") or spec.get("title", "project"))
        log(f"Writing walkthrough: {spec.get('title')}")
        time.sleep(8)  # respect free-tier rate limits
        try:
            reply = github_models.chat(
                [
                    {"role": "system", "content": WALKTHROUGH_SYSTEM},
                    {"role": "user", "content": json.dumps(spec, ensure_ascii=False)},
                ],
                max_tokens=4000,
                temperature=0.7,
            )
            walkthrough = github_models.extract_json(reply)
            modules = walkthrough.get("modules")
            if not modules:
                raise ValueError("walkthrough has no modules")
            spec["modules"] = modules
            projects.append(spec)
        except Exception as e:
            log(f"  ! walkthrough failed for {spec['id']}: {e}")

    if len(projects) < 3:
        log("Fewer than 3 projects generated successfully — keeping existing projects.json")
        sys.exit(1)

    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "github-actions",
        "model": github_models.MODEL,
        "basedOnNewsFrom": news.get("updatedAt"),
        "projects": projects,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log(f"Wrote {OUT_PATH} with {len(projects)} projects")


if __name__ == "__main__":
    main()
