#!/usr/bin/env python3
"""Generate an image with Kie.ai's GPT Image 2.5 Flare (text-to-image).

Usage:
    KIE_API_KEY=... python scripts/kie_image.py "a prompt" [--aspect 16:9] \
        [--resolution 2K] [--background auto] [--out image.png]

Creates a task, polls until it finishes, then downloads the first result.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.kie.ai/api/v1/jobs"
MODEL = "gpt-image-2-5-flare-text-to-image"
ASPECTS = ["auto", "1:1", "3:2", "2:3", "16:9", "9:16", "4:3", "3:4", "21:9",
           "27:16", "16:27", "9:8", "8:9"]
ONE_K_ONLY = {"27:16", "16:27", "9:8", "8:9"}


def call(path, key, body=None):
    req = urllib.request.Request(
        f"{BASE}/{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Kie.ai HTTP {e.code}: {detail}") from e
    if data.get("code") != 200:
        raise RuntimeError(f"Kie.ai error {data.get('code')}: {data.get('msg')}")
    return data["data"]


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("prompt")
    p.add_argument("--aspect", default="auto", choices=ASPECTS)
    p.add_argument("--resolution", default="1K", choices=["1K", "2K", "4K"])
    p.add_argument("--background", default="auto", choices=["auto", "opaque", "transparent"])
    p.add_argument("--out", default="kie-image.png")
    p.add_argument("--timeout", type=int, default=300, help="seconds to wait")
    args = p.parse_args()

    key = os.environ.get("KIE_API_KEY")
    if not key:
        sys.exit("KIE_API_KEY is not set")
    if args.aspect in ONE_K_ONLY and args.resolution != "1K":
        sys.exit(f"{args.aspect} supports 1K only")

    task = call("createTask", key, {
        "model": MODEL,
        "input": {
            "prompt": args.prompt,
            "aspect_ratio": args.aspect,
            "resolution": args.resolution,
            "background": args.background,
        },
    })
    task_id = task["taskId"]
    print(f"task {task_id} created, waiting…", flush=True)

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(4)
        info = call(f"recordInfo?taskId={task_id}", key)
        if info["state"] == "success":
            urls = json.loads(info["resultJson"])["resultUrls"]
            urllib.request.urlretrieve(urls[0], args.out)
            print(f"saved {args.out}  ({urls[0]})")
            return
        if info["state"] == "fail":
            sys.exit(f"generation failed: {info.get('failCode')} {info.get('failMsg')}")
    sys.exit(f"timed out; check later with taskId {task_id}")


if __name__ == "__main__":
    main()
