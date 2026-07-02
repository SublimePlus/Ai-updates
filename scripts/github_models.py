"""Minimal client for the free GitHub Models inference API.

Uses the GITHUB_TOKEN that GitHub Actions injects automatically (the
workflow just needs `permissions: models: read`). No extra account,
no API key, no billing.

Docs: https://docs.github.com/en/github-models
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

ENDPOINT = os.environ.get(
    "GH_MODELS_ENDPOINT", "https://models.github.ai/inference/chat/completions"
)
MODEL = os.environ.get("GH_MODELS_MODEL", "openai/gpt-4o-mini")


def token():
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def available():
    return bool(token())


def chat(messages, max_tokens=3000, temperature=0.6, retries=4):
    """Send a chat completion request. Returns the assistant text.

    Raises RuntimeError if no token is configured or all retries fail.
    """
    if not available():
        raise RuntimeError("GITHUB_TOKEN is not set; cannot call GitHub Models")

    body = json.dumps(
        {
            "model": MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    ).encode("utf-8")

    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token()}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last_err = e
            # 429 = rate limited on the free tier; honor Retry-After if present
            if e.code in (429, 500, 502, 503):
                wait = e.headers.get("Retry-After")
                delay = int(wait) if wait and wait.isdigit() else 15 * (attempt + 1)
                print(f"  github-models: HTTP {e.code}, retrying in {delay}s")
                time.sleep(delay)
                continue
            detail = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"GitHub Models HTTP {e.code}: {detail}") from e
        except Exception as e:  # network hiccups
            last_err = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"GitHub Models failed after {retries} attempts: {last_err}")


def extract_json(text):
    """Pull the first JSON array/object out of a model reply.

    Models sometimes wrap JSON in ``` fences or add prose around it.
    """
    text = re.sub(r"```(?:json)?", "", text)
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
        break
    raise ValueError("no JSON found in model reply")
