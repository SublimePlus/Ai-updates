#!/usr/bin/env python3
"""Minimal client for the Kie.ai jobs API (createTask + recordInfo polling).

Reads the API key from the KIE_API_KEY environment variable — never
hard-code it. Stdlib only.

Usage:
  python3 scripts/kie.py "a red fox in snow" [--aspect 1:1] [--res 1K] \
      [--background auto] [--model gpt-image-2-5-flare-text-to-image] [--out DIR]
  python3 scripts/kie.py --status TASK_ID

Docs: https://docs.kie.ai
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("KIE_API_BASE", "https://api.kie.ai/api/v1/jobs")
DEFAULT_MODEL = "gpt-image-2-5-flare-text-to-image"


def _request(method, url, body=None):
    key = os.environ.get("KIE_API_KEY")
    if not key:
        sys.exit("KIE_API_KEY is not set")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    if payload.get("code") != 200:
        sys.exit(f"Kie.ai error {payload.get('code')}: {payload.get('msg')}")
    return payload["data"]


def create_task(model, inp, callback_url=None):
    body = {"model": model, "input": inp}
    if callback_url:
        body["callBackUrl"] = callback_url
    return _request("POST", f"{BASE}/createTask", body)["taskId"]


def task_status(task_id):
    return _request("GET", f"{BASE}/recordInfo?taskId={task_id}")


def wait(task_id, interval=5, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = task_status(task_id)
        if info["state"] == "success":
            return json.loads(info["resultJson"] or "{}")
        if info["state"] == "fail":
            sys.exit(f"Task failed ({info.get('failCode')}): {info.get('failMsg')}")
        time.sleep(interval)
    sys.exit(f"Timed out waiting for task {task_id}")


def download(urls, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for url in urls:
        path = os.path.join(out_dir, url.rsplit("/", 1)[-1].split("?")[0])
        urllib.request.urlretrieve(url, path)
        paths.append(path)
    return paths


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("prompt", nargs="?")
    p.add_argument("--status", metavar="TASK_ID")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--aspect", default="auto")
    p.add_argument("--res", default="1K", choices=["1K", "2K", "4K"])
    p.add_argument("--background", default="auto",
                   choices=["auto", "transparent", "opaque"])
    p.add_argument("--out", help="download results into this directory")
    a = p.parse_args()

    if a.status:
        print(json.dumps(task_status(a.status), indent=2))
        return
    if not a.prompt:
        p.error("prompt is required")

    task_id = create_task(a.model, {
        "prompt": a.prompt,
        "aspect_ratio": a.aspect,
        "resolution": a.res,
        "background": a.background,
    })
    print(f"taskId: {task_id}", file=sys.stderr)
    result = wait(task_id)
    urls = result.get("resultUrls", [])
    for url in urls:
        print(url)
    if a.out and urls:
        for path in download(urls, a.out):
            print(f"saved: {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
