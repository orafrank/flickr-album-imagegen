#!/usr/bin/env python3
"""Prepare and execute confirmed Flickr or Google Photos batch uploads."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


IMAGE_TYPES = {".avif", ".bmp", ".gif", ".heic", ".ico", ".jpeg", ".jpg",
               ".png", ".tif", ".tiff", ".webp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_plan(plan: dict) -> bytes:
    clean = {key: value for key, value in plan.items() if key != "plan_id"}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode()


def plan_id(plan: dict) -> str:
    return hashlib.sha256(canonical_plan(plan)).hexdigest()[:16]


def image_files(directory: Path) -> list[Path]:
    return sorted(path.resolve() for path in directory.iterdir()
                  if path.is_file() and path.suffix.lower() in IMAGE_TYPES)


def build_plan(args: argparse.Namespace) -> dict:
    files = image_files(args.input)
    if not files:
        raise SystemExit(f"No supported images found in {args.input}")
    target = {"album_id": args.album_id, "album_title": args.album_title}
    if args.provider == "flickr":
        privacy = {
            "public": bool(args.public),
            "friends": bool(args.friends),
            "family": bool(args.family),
            "search_visibility": "hidden" if args.hidden else "visible",
        }
    else:
        if not args.google_album_created_by_app:
            raise SystemExit(
                "Google Photos only permits API uploads to albums created by "
                "this app. Pass --google-album-created-by-app after verifying."
            )
        privacy = {
            "library": "Google Photos account library",
            "album_scope": "app-created album",
            "sharing": "not controlled by the API; manage in Google Photos",
        }
        target["created_by_app"] = True
    plan = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "account": args.account,
        "target": target,
        "privacy": privacy,
        "files": [
            {
                "path": str(path),
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "mime_type": mimetypes.guess_type(path.name)[0]
                or "application/octet-stream",
            }
            for path in files
        ],
    }
    plan["plan_id"] = plan_id(plan)
    return plan


def show_plan(plan: dict) -> None:
    target = plan["target"]
    print("UPLOAD PLAN — no files have been uploaded")
    print(f"Confirmation code : {plan['plan_id']}")
    print(f"Provider          : {plan['provider']}")
    print(f"Account           : {plan['account']}")
    print(f"Target album      : {target['album_title']} ({target['album_id']})")
    print(f"Privacy / sharing : {json.dumps(plan['privacy'], ensure_ascii=False)}")
    print(f"Files             : {len(plan['files'])}")
    for index, item in enumerate(plan["files"], 1):
        print(f"  {index:02d}. {item['filename']}  {item['bytes']} bytes")
    print()
    print("To upload this exact batch, run:")
    print(f"  publish_batch.py upload --plan <plan.json> --confirm {plan['plan_id']}")


def oauth_quote(value: object) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


def flickr_auth(method: str, url: str, params: dict[str, object],
                key: str, secret: str, token: str, token_secret: str) -> str:
    oauth = {
        "oauth_consumer_key": key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    pairs = [(oauth_quote(k), oauth_quote(v))
             for k, v in {**params, **oauth}.items()]
    normalized = "&".join(f"{k}={v}" for k, v in sorted(pairs))
    base = "&".join(map(oauth_quote, [method.upper(), url, normalized]))
    signing_key = f"{oauth_quote(secret)}&{oauth_quote(token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    return "OAuth " + ", ".join(
        f'{oauth_quote(k)}="{oauth_quote(v)}"' for k, v in sorted(oauth.items())
    )


def multipart(fields: dict[str, object], file_item: dict) -> tuple[bytes, str]:
    boundary = "----codex-" + secrets.token_hex(16)
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            str(value).encode(), b"\r\n",
        ])
    path = Path(file_item["path"])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {file_item['mime_type']}\r\n\r\n".encode(),
        path.read_bytes(), b"\r\n", f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), boundary


def request(req: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(req, timeout=180) as response:
        return response.read()


def upload_flickr(plan: dict) -> None:
    key = os.environ.get("FLICKR_API_KEY")
    secret = os.environ.get("FLICKR_API_SECRET")
    token = os.environ.get("FLICKR_OAUTH_TOKEN")
    token_secret = os.environ.get("FLICKR_OAUTH_TOKEN_SECRET")
    if not all([key, secret, token, token_secret]):
        raise SystemExit("Missing Flickr API/OAuth environment variables")
    upload_url = "https://up.flickr.com/services/upload/"
    rest_url = "https://api.flickr.com/services/rest"
    privacy = plan["privacy"]
    for item in plan["files"]:
        fields = {
            "title": Path(item["filename"]).stem,
            "is_public": int(privacy["public"]),
            "is_friend": int(privacy["friends"]),
            "is_family": int(privacy["family"]),
            "hidden": 2 if privacy["search_visibility"] == "hidden" else 1,
            "content_type": 1,
            "safety_level": 1,
        }
        body, boundary = multipart(fields, item)
        auth = flickr_auth("POST", upload_url, fields, key, secret,
                           token, token_secret)
        result = request(urllib.request.Request(
            upload_url, data=body, method="POST",
            headers={"Authorization": auth,
                     "Content-Type": f"multipart/form-data; boundary={boundary}"}
        )).decode()
        marker_a, marker_b = "<photoid>", "</photoid>"
        if marker_a not in result:
            raise RuntimeError(f"Flickr upload failed for {item['filename']}: {result}")
        photo_id = result.split(marker_a, 1)[1].split(marker_b, 1)[0]
        params = {
            "method": "flickr.photosets.addPhoto",
            "api_key": key,
            "format": "json",
            "nojsoncallback": 1,
            "photoset_id": plan["target"]["album_id"],
            "photo_id": photo_id,
        }
        encoded = urllib.parse.urlencode(params).encode()
        auth = flickr_auth("POST", rest_url, params, key, secret,
                           token, token_secret)
        added = json.loads(request(urllib.request.Request(
            rest_url, data=encoded, method="POST",
            headers={"Authorization": auth,
                     "Content-Type": "application/x-www-form-urlencoded"}
        )))
        if added.get("stat") != "ok":
            raise RuntimeError(
                f"Uploaded {photo_id}, but album insertion failed: {added}"
            )
        print(f"Uploaded {item['filename']} -> Flickr photo {photo_id}")


def upload_google(plan: dict) -> None:
    token = os.environ.get("GOOGLE_PHOTOS_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Missing GOOGLE_PHOTOS_ACCESS_TOKEN")
    upload_tokens = []
    for item in plan["files"]:
        data = Path(item["path"]).read_bytes()
        req = urllib.request.Request(
            "https://photoslibrary.googleapis.com/v1/uploads",
            data=data, method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "X-Goog-Upload-Content-Type": item["mime_type"],
                "X-Goog-Upload-Protocol": "raw",
            })
        upload_token = request(req).decode()
        upload_tokens.append({
            "description": "",
            "simpleMediaItem": {
                "fileName": item["filename"],
                "uploadToken": upload_token,
            },
        })
    for offset in range(0, len(upload_tokens), 50):
        payload = json.dumps({
            "albumId": plan["target"]["album_id"],
            "newMediaItems": upload_tokens[offset:offset + 50],
        }).encode()
        response = json.loads(request(urllib.request.Request(
            "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate",
            data=payload, method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"}
        )))
        failures = [item for item in response.get("newMediaItemResults", [])
                    if item.get("status", {}).get("code")]
        if failures:
            raise RuntimeError(f"Google Photos batchCreate failures: {failures}")
    print(f"Uploaded {len(plan['files'])} files to Google Photos")


def verify_plan(plan: dict, confirmation: str) -> None:
    expected = plan_id(plan)
    if plan.get("plan_id") != expected or confirmation != expected:
        raise SystemExit("Confirmation code does not match this upload plan")
    for item in plan["files"]:
        path = Path(item["path"])
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise SystemExit(f"File changed or is missing: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--provider", choices=["flickr", "google"], required=True)
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--account", required=True)
    prepare.add_argument("--album-id", required=True)
    prepare.add_argument("--album-title", required=True)
    prepare.add_argument("--plan", type=Path, required=True)
    prepare.add_argument("--public", type=int, choices=[0, 1], default=0)
    prepare.add_argument("--friends", type=int, choices=[0, 1], default=0)
    prepare.add_argument("--family", type=int, choices=[0, 1], default=0)
    prepare.add_argument("--hidden", action="store_true")
    prepare.add_argument("--google-album-created-by-app", action="store_true")
    upload = sub.add_parser("upload")
    upload.add_argument("--plan", type=Path, required=True)
    upload.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        plan = build_plan(args)
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        args.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        show_plan(plan)
        return 0
    plan = json.loads(args.plan.read_text())
    verify_plan(plan, args.confirm)
    show_plan(plan)
    if plan["provider"] == "flickr":
        upload_flickr(plan)
    elif plan["provider"] == "google":
        upload_google(plan)
    else:
        raise SystemExit("Unsupported provider in plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
