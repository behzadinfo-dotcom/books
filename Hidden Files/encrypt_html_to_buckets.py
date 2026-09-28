#!/usr/bin/env python3
"""رمز AES-GCM (HMK1) روی HTML و ارسال به Appwrite + آروان.

کلید از /home/user/.hamyar-secrets/07-html-media-key.bin خوانده می‌شود.
هرگز کلید را چاپ نکن.

  python3 encrypt_html_to_buckets.py --file a.html --id lab-09-biology.html
  python3 encrypt_html_to_buckets.py --dir ./out --map lab-09-chemistry.html=x.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SECRETS = Path("/home/user/.hamyar-secrets")
MAGIC = b"HMK1"
APPWRITE_ENDPOINT = "https://fra.cloud.appwrite.io/v1"
APPWRITE_PROJECT = "6a9d59e3002751cc3ea8"
APPWRITE_BUCKET = "6aa1eaae00303400117b"
ARVAN_ENDPOINT = "https://s3.ir-thr-at1.arvanstorage.ir"
ARVAN_BUCKET = "hamyar-e-man"
ARVAN_REGION = "ir-thr-at1"


def load_env() -> None:
    for name in ("02-appwrite-hamyar.env", "01-arvan-iran-bucket.env", "arvan-ir-bucket.env"):
        p = SECRETS / name
        if not p.is_file():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))
    aw = SECRETS / "02-appwrite-hamyar.json"
    if aw.is_file() and not os.environ.get("APPWRITE_API_KEY"):
        d = json.loads(aw.read_text())
        os.environ.setdefault("APPWRITE_API_KEY", d.get("api_key", ""))
        os.environ.setdefault("APPWRITE_PROJECT_ID", d.get("project_id", APPWRITE_PROJECT))
        os.environ.setdefault("APPWRITE_BUCKET_ID", d.get("media_bucket_id", APPWRITE_BUCKET))
        os.environ.setdefault("APPWRITE_ENDPOINT", d.get("endpoint", APPWRITE_ENDPOINT))


def media_key() -> bytes:
    p = SECRETS / "07-html-media-key.bin"
    if not p.is_file():
        sys.exit("missing 07-html-media-key.bin")
    raw = p.read_bytes()
    if len(raw) != 32:
        sys.exit("html media key must be 32 bytes")
    return raw


def wrap(plain: bytes, key: bytes) -> bytes:
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, plain, None)
    return MAGIC + iv + ct


def aw_headers() -> dict:
    key = os.environ.get("APPWRITE_API_KEY", "")
    if not key:
        sys.exit("missing APPWRITE_API_KEY")
    return {
        "X-Appwrite-Project": os.environ.get("APPWRITE_PROJECT_ID", APPWRITE_PROJECT),
        "X-Appwrite-Key": key,
    }


def aw_upload(fid: str, data: bytes) -> None:
    ep = os.environ.get("APPWRITE_ENDPOINT", APPWRITE_ENDPOINT).rstrip("/")
    bucket = os.environ.get("APPWRITE_BUCKET_ID") or os.environ.get("APPWRITE_MEDIA_BUCKET_ID") or APPWRITE_BUCKET
    requests.delete(f"{ep}/storage/buckets/{bucket}/files/{fid}", headers=aw_headers(), timeout=60)
    files = {
        "fileId": (None, fid),
        "file": (fid, data, "application/octet-stream"),
        "permissions[]": (None, 'read("any")'),
    }
    r = requests.post(
        f"{ep}/storage/buckets/{bucket}/files",
        headers={"X-Appwrite-Project": os.environ.get("APPWRITE_PROJECT_ID", APPWRITE_PROJECT),
                 "X-Appwrite-Key": os.environ.get("APPWRITE_API_KEY", "")},
        files=files,
        timeout=180,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"appwrite {fid} {r.status_code} {r.text[:180]}")


def arvan_upload(fid: str, data: bytes) -> None:
    import boto3
    from botocore.config import Config

    ak = os.environ.get("ARVAN_ACCESS_KEY") or os.environ.get("ARVAN_ACCESS_KEY_ID")
    sk = os.environ.get("ARVAN_SECRET_KEY") or os.environ.get("ARVAN_SECRET_ACCESS_KEY")
    if not ak or not sk:
        raise RuntimeError("missing ARVAN keys")
    s3 = boto3.client(
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
            retries={"max_attempts": 2},
        ),
    )
    extra = {"ContentType": "application/octet-stream"}
    try:
        s3.put_object(Bucket=os.environ.get("ARVAN_BUCKET", ARVAN_BUCKET), Key=fid, Body=data, ACL="public-read", **extra)
    except Exception:
        s3.put_object(Bucket=os.environ.get("ARVAN_BUCKET", ARVAN_BUCKET), Key=fid, Body=data, **extra)


def put_key_row() -> None:
    """ردیف خصوصی app_state / html_media_key — فقط users."""
    import base64

    ep = os.environ.get("APPWRITE_ENDPOINT", APPWRITE_ENDPOINT).rstrip("/")
    db = os.environ.get("APPWRITE_DATABASE_ID") or "ZahraDB"
    b64 = base64.b64encode(media_key()).decode("ascii")
    payload = json.dumps({"v": 1, "b": b64}, separators=(",", ":"))
    body = {
        "rowId": "html_media_key",
        "data": {
            "userId": "global",
            "key": "html_media_key",
            "payload": payload,
            "updatedAt": int(time.time() * 1000),
        },
        "permissions": ['read("users")'],
    }
    h = {**aw_headers(), "Content-Type": "application/json"}
    url = f"{ep}/tablesdb/{db}/tables/app_state/rows"
    r = requests.post(url, headers=h, json=body, timeout=30)
    if r.status_code in (200, 201):
        print("appwrite row html_media_key created")
        return
    if r.status_code in (409, 400):
        u = f"{ep}/tablesdb/{db}/tables/app_state/rows/html_media_key"
        r2 = requests.patch(
            u,
            headers=h,
            json={
                "data": body["data"],
                "permissions": ['read("users")'],
            },
            timeout=30,
        )
        if r2.status_code in (200, 201):
            print("appwrite row html_media_key updated")
            return
        # document API fallback
        durl = f"{ep}/databases/{db}/collections/app_state/documents/html_media_key"
        r3 = requests.patch(
            durl,
            headers=h,
            json={"data": body["data"], "permissions": ['read("users")']},
            timeout=30,
        )
        print("appwrite row patch", r.status_code, r2.status_code, r3.status_code, r3.text[:160])
        if r3.status_code not in (200, 201):
            raise RuntimeError("could not store html_media_key row")
        return
    print("create row", r.status_code, r.text[:200])
    raise RuntimeError("could not store html_media_key row")


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", default=[], help="path to html")
    ap.add_argument("--id", action="append", default=[], help="bucket file id (same order as --file)")
    ap.add_argument("--skip-arvan", action="store_true")
    ap.add_argument("--key-row-only", action="store_true")
    args = ap.parse_args()

    put_key_row()
    if args.key_row_only:
        return 0
    if len(args.file) != len(args.id) or not args.file:
        if not args.file:
            print("key row done; pass --file and --id to upload")
            return 0
        sys.exit("--file and --id counts must match")

    key = media_key()
    ok = fail = 0
    for path, fid in zip(args.file, args.id):
        plain = Path(path).read_bytes()
        if plain.startswith(MAGIC):
            blob = plain
            print(fid, "already wrapped", len(blob))
        else:
            blob = wrap(plain, key)
            print(fid, "plain", len(plain), "wrapped", len(blob))
        try:
            aw_upload(fid, blob)
            print(fid, "appwrite ok")
        except Exception as e:
            fail += 1
            print(fid, "appwrite FAIL", type(e).__name__, str(e)[:180])
            continue
        if not args.skip_arvan:
            try:
                arvan_upload(fid, blob)
                print(fid, "arvan ok")
            except Exception as e:
                print(fid, "arvan FAIL", type(e).__name__, str(e)[:180])
        ok += 1
    print("done ok", ok, "fail", fail)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
