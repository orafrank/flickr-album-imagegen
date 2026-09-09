#!/usr/bin/env python3
"""Download an ordered slice of public photos from a Flickr album page."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

TOKEN_RE = re.compile(r'"(?:title|id)":"[^"]*"')
STATIC_RE = re.compile(r'https://live\.staticflickr\.com/[^" ]+_b\.jpg')


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def decode_value(token: str) -> str:
    return json.loads(token.split(":", 1)[1])


def ordered_photos(page_html: str, album_id: str) -> list[tuple[str, str]]:
    current_title = "photo"
    seen: set[str] = set()
    photos: list[tuple[str, str]] = []
    for match in TOKEN_RE.finditer(page_html):
        token = match.group(0)
        if token.startswith('"title"'):
            current_title = decode_value(token)
            continue
        photo_id = decode_value(token)
        if not photo_id.isdigit() or photo_id == album_id or photo_id in seen:
            continue
        seen.add(photo_id)
        photos.append((photo_id, current_title))
    return photos


def safe_title(value: str) -> str:
    value = html.unescape(value).strip() or "photo"
    value = re.sub(r"[\/:*?\"<>|\x00-\x1f]", "_", value)
    return re.sub(r"\s+", "_", value)[:100]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.start < 1 or args.count < 1:
        parser.error("--start and --count must be positive")

    album_match = re.search(r"/albums/(\d+)", args.url)
    owner_match = re.search(r"/photos/([^/]+)/albums/", args.url)
    if not album_match or not owner_match:
        parser.error("URL does not contain a Flickr owner and album ID")
    album_id = album_match.group(1)
    owner = owner_match.group(1)
    photos = ordered_photos(fetch_text(args.url), album_id)
    selected = photos[args.start - 1 : args.start - 1 + args.count]
    if not selected:
        print("No photos found in requested range", file=sys.stderr)
        return 2

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = []
    width = max(2, len(str(args.start + len(selected) - 1)))
    for offset, (photo_id, title) in enumerate(selected):
        sequence = args.start + offset
        photo_page = f"https://www.flickr.com/photos/{owner}/{photo_id}/"
        image_match = STATIC_RE.search(fetch_text(photo_page))
        if not image_match:
            raise RuntimeError(f"No downloadable image found for Flickr photo {photo_id}")
        image_url = image_match.group(0)
        filename = f"{sequence:0{width}d}_{safe_title(title)}.jpg"
        local_path = args.output / filename
        request = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            local_path.write_bytes(response.read())
        manifest.append({"sequence": sequence, "photo_id": photo_id, "title": title,
                         "photo_page": photo_page, "source_url": image_url,
                         "local_path": str(local_path.resolve())})

    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps({"album_url": args.url, "album_id": album_id,
        "requested_start": args.start, "requested_count": args.count,
        "actual_count": len(manifest), "photos": manifest},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
