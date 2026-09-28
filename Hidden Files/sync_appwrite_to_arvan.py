#!/usr/bin/env python3
"""Appwrite media bucket → Arvan S3 (hamyar-e-man). Incremental by size.

Local: reads /home/user/.hamyar-secrets/arvan-ir-bucket.env + appwrite/credentials.json
CI:    env APPWRITE_* and ARVAN_*
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path

import requests

APPWRITE_ENDPOINT = os.environ.get("APPWRITE_ENDPOINT", "https://fra.cloud.appwrite.io/v1").rstrip("/")
APPWRITE_PROJECT = os.environ.get("APPWRITE_PROJECT_ID", "6a9d59e3002751cc3ea8")
APPWRITE_BUCKET = os.environ.get("APPWRITE_BUCKET_ID", "6aa1eaae00303400117b")
ARVAN_ENDPOINT = os.environ.get("ARVAN_ENDPOINT", "https://s3.ir-thr-at1.arvanstorage.ir")
ARVAN_REGION = os.environ.get("ARVAN_REGION", "ir-thr-at1")
ARVAN_BUCKET = os.environ.get("ARVAN_BUCKET", "hamyar-e-man")


def load_local_env() -> None:
    envp = Path("/home/user/.hamyar-secrets/arvan-ir-bucket.env")
    if envp.is_file():
        for line in envp.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)
            if k == "ARVAN_ACCESS_KEY":
                os.environ.setdefault("ARVAN_ACCESS_KEY", v)
            if k == "ARVAN_SECRET_KEY":
                os.environ.setdefault("ARVAN_SECRET_KEY", v)
    aw = Path("/home/user/appwrite/credentials.json")
    if aw.is_file() and not os.environ.get("APPWRITE_API_KEY"):
        d = json.loads(aw.read_text())
        os.environ.setdefault("APPWRITE_API_KEY", d.get("api_key", ""))
        os.environ.setdefault("APPWRITE_PROJECT_ID", d.get("project_id", APPWRITE_PROJECT))
        os.environ.setdefault("APPWRITE_BUCKET_ID", d.get("media_bucket_id", APPWRITE_BUCKET))
        os.environ.setdefault("APPWRITE_ENDPOINT", d.get("endpoint", APPWRITE_ENDPOINT))


def aw_headers() -> dict:
    key = os.environ.get("APPWRITE_API_KEY", "")
    if not key:
        sys.exit("missing APPWRITE_API_KEY")
    return {"X-Appwrite-Project": os.environ.get("APPWRITE_PROJECT_ID", APPWRITE_PROJECT), "X-Appwrite-Key": key}


def aw_get(path: str, params=None):
    url = f"{os.environ.get('APPWRITE_ENDPOINT', APPWRITE_ENDPOINT).rstrip('/')}{path}"
    r = requests.get(url, headers=aw_headers(), params=params or {}, timeout=60)
    r.raise_for_status()
    return r.json()


def paginate_list(search: str | None = None) -> list[dict]:
    files: list[dict] = []
    offset = 0
    bucket = os.environ.get("APPWRITE_BUCKET_ID", APPWRITE_BUCKET)
    while True:
        params = {"limit": 25, "offset": offset}
        if search:
            params["search"] = search
        j = aw_get(f"/storage/buckets/{bucket}/files", params)
        chunk = j.get("files") or []
        files.extend(chunk)
        total = j.get("total") or 0
        if not chunk or len(files) >= total:
            break
        offset += len(chunk)
        if offset > 5000:
            break
    return files


def file_meta(fid: str) -> dict | None:
    bucket = os.environ.get("APPWRITE_BUCKET_ID", APPWRITE_BUCKET)
    url = (
        f"{os.environ.get('APPWRITE_ENDPOINT', APPWRITE_ENDPOINT).rstrip('/')}"
        f"/storage/buckets/{bucket}/files/{fid}"
    )
    r = requests.get(url, headers=aw_headers(), timeout=30)
    if r.status_code != 200:
        return None
    return r.json()


def collect_all() -> dict[str, dict]:
    found: dict[str, dict] = {}

    def add(f: dict) -> None:
        fid = f.get("$id") or f.get("id")
        if not fid:
            return
        found[fid] = {
            "id": fid,
            "name": f.get("name") or fid,
            "mime": f.get("mimeType") or "",
            "size": int(f.get("sizeOriginal") or 0),
        }

    for f in paginate_list(None):
        add(f)
    for q in (
        "html", "jpg", "jpeg", "png", "mp3", "mp4", "webp", "wav", "json",
        "Amzshghh", "Background", "tool-", "lab-", "yg-", "br-", "ex-",
    ):
        for f in paginate_list(q):
            add(f)

    extra = ["Background-music.html"]
    extra += [f"Amzshghh-{i:02d}-speed-reading.html" for i in range(1, 35)]
    extra += [f"yg-{i:02d}.html" for i in range(1, 16)]
    extra += [f"yg-{i:02d}.jpg" for i in range(1, 16)]
    extra += [f"br-{i:02d}.html" for i in range(1, 9)]
    extra += [f"ex-{i:02d}.html" for i in range(1, 16)]
    extra += [f"ex-{i:02d}.jpg" for i in range(1, 16)]
    extra += [
        "tool-dj120d.html", "tool-casio991.html", "tool-ti-nspire.html",
        "tool-calendar.html", "tool-converter.html",
        "lab-09-chemistry.html", "lab-09-physics.html", "lab-09-biology.html",
    ]
    for fid in extra:
        if fid in found:
            continue
        m = file_meta(fid)
        if m:
            add(m)
    return found


def is_pdf(item: dict) -> bool:
    fid = item["id"].lower()
    name = item["name"].lower()
    mime = (item.get("mime") or "").lower()
    return fid.endswith(".pdf") or name.endswith(".pdf") or "pdf" in mime


def download_bytes(fid: str) -> bytes:
    bucket = os.environ.get("APPWRITE_BUCKET_ID", APPWRITE_BUCKET)
    proj = os.environ.get("APPWRITE_PROJECT_ID", APPWRITE_PROJECT)
    ep = os.environ.get("APPWRITE_ENDPOINT", APPWRITE_ENDPOINT).rstrip("/")
    url = f"{ep}/storage/buckets/{bucket}/files/{fid}/view?project={proj}"
    r = requests.get(url, headers=aw_headers(), timeout=180)
    r.raise_for_status()
    return r.content


def s3_client():
    import boto3
    from botocore.config import Config

    ak = os.environ.get("ARVAN_ACCESS_KEY") or os.environ.get("ARVAN_ACCESS_KEY_ID")
    sk = os.environ.get("ARVAN_SECRET_KEY") or os.environ.get("ARVAN_SECRET_ACCESS_KEY")
    if not ak or not sk:
        sys.exit("missing ARVAN_ACCESS_KEY / ARVAN_SECRET_KEY")
    return boto3.client(
        "s3",
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        endpoint_url=os.environ.get("ARVAN_ENDPOINT", ARVAN_ENDPOINT),
        region_name=os.environ.get("ARVAN_REGION", ARVAN_REGION),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=20,
            read_timeout=180,
            retries={"max_attempts": 3},
        ),
    )


def s3_size(s3, key: str) -> int | None:
    try:
        r = s3.head_object(Bucket=os.environ.get("ARVAN_BUCKET", ARVAN_BUCKET), Key=key)
        return int(r.get("ContentLength") or 0)
    except Exception:
        return None


def put(s3, key: str, data: bytes, mime: str) -> None:
    extra = {}
    if mime:
        extra["ContentType"] = mime
    try:
        s3.put_object(
            Bucket=os.environ.get("ARVAN_BUCKET", ARVAN_BUCKET),
            Key=key,
            Body=data,
            ACL="public-read",
            **extra,
        )
    except Exception:
        s3.put_object(
            Bucket=os.environ.get("ARVAN_BUCKET", ARVAN_BUCKET),
            Key=key,
            Body=data,
            **extra,
        )


def main() -> int:
    load_local_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-pdf", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--local-dir", default="", help="هم‌زمان روی دیسک هم ذخیره کن")
    args = ap.parse_args()

    print("listing Appwrite …")
    all_files = collect_all()
    items = list(all_files.values())
    if args.skip_pdf:
        items = [i for i in items if not is_pdf(i)]
    print("files", len(items), "bytes", sum(i["size"] for i in items))

    local = Path(args.local_dir) if args.local_dir else None
    if local:
        local.mkdir(parents=True, exist_ok=True)

    s3 = None
    if not args.dry_run:
        s3 = s3_client()

    ok = skip = fail = 0
    for i, item in enumerate(sorted(items, key=lambda x: x["id"]), 1):
        fid = item["id"]
        mime = item.get("mime") or mimetypes.guess_type(fid)[0] or "application/octet-stream"
        try:
            if s3 is not None and not args.force:
                remote = s3_size(s3, fid)
                if remote is not None and item["size"] and remote == item["size"]:
                    skip += 1
                    print(f"[{i}/{len(items)}] SKIP {fid}")
                    continue
            data = download_bytes(fid)
            if local is not None:
                dest = local / fid
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            if args.dry_run:
                print(f"[{i}/{len(items)}] DRY {fid} {len(data)}")
                ok += 1
                continue
            put(s3, fid, data, mime)
            ok += 1
            print(f"[{i}/{len(items)}] OK {fid} {len(data)}")
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(items)}] FAIL {fid} {type(e).__name__}: {str(e)[:180]}")
    print("done ok", ok, "skip", skip, "fail", fail)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
