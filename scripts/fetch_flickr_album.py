#!/usr/bin/env python3
"""Download an ordered slice of public photos from a Flickr album page."""

from __future__ import annotations

import argparse
import http.cookiejar
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

TOKEN_RE = re.compile(r'"(?:title|id)":"[^"]*"')
STATIC_RE = re.compile(r'https://live\.staticflickr\.com/[^" ]+?\.jpg')


def fetch_text(opener: urllib.request.OpenerDirector, url: str) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace"), response.geturl()


def best_image_url(page_html: str, photo_id: str) -> str | None:
    candidates = [url for url in STATIC_RE.findall(page_html) if f"/{photo_id}_" in url]
    if not candidates:
        return None
    rank = {"o": 6, "k": 5, "h": 4, "b": 3, "c": 2}

    def score(url: str) -> int:
        match = re.search(r"_([okhbc])\.jpg$", url)
        return rank.get(match.group(1), 1) if match else 1

    return max(dict.fromkeys(candidates), key=score)


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

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    album_html, resolved_url = fetch_text(opener, args.url)
    album_match = re.search(r"/(?:albums|sets)/(\d+)", resolved_url)
    owner_match = re.search(r"/photos/([^/]+)/(?:albums|sets)/", resolved_url)
    if not album_match or not owner_match:
        parser.error("URL did not resolve to a Flickr album or Guest Pass album")
    album_id = album_match.group(1)
    owner = owner_match.group(1)
    photos = ordered_photos(album_html, album_id)
    selected = photos[args.start - 1 : args.start - 1 + args.count]
    if not selected:
        print("No photos found in requested range", file=sys.stderr)
        return 2

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = []
    width = max(2, len(str(args.start + len(selected) - 1)))
    for offset, (photo_id, title) in enumerate(selected):
        sequence = args.start + offset
        photo_page = f"https://www.flickr.com/photos/{owner}/{photo_id}/in/album-{album_id}"
        photo_html, _ = fetch_text(opener, photo_page)
        image_url = best_image_url(photo_html, photo_id)
        if not image_url:
            raise RuntimeError(f"No downloadable image found for Flickr photo {photo_id}")
        filename = f"{sequence:0{width}d}_{safe_title(title)}.jpg"
        local_path = args.output / filename
        request = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(request, timeout=60) as response:
            local_path.write_bytes(response.read())
        manifest.append({"sequence": sequence, "photo_id": photo_id, "title": title,
                         "photo_page": photo_page, "source_url": image_url,
                         "local_path": str(local_path.resolve())})

    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps({"album_url": resolved_url, "source_url": args.url,
        "guest_pass": "/gp/" in args.url, "album_id": album_id,
        "requested_start": args.start, "requested_count": args.count,
        "actual_count": len(manifest), "photos": manifest},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
