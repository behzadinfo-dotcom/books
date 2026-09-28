#!/usr/bin/env python3
"""Copy Appwrite media (except PDF) to Arvan bucket hamyar-e-man. Reads keys from sibling env file."""
from __future__ import annotations

import json
import mimetypes
import sys
from pathlib import Path

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import ClientError

ENV = Path(__file__).with_name("arvan-ir-bucket.env")
AW = Path("/home/user/appwrite/credentials.json")
LIST = Path("/tmp/aw-nonpdf.json")


def load_env() -> dict[str, str]:
    out = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k] = v
    return out


def main() -> int:
    env = load_env()
    aw = json.loads(AW.read_text())
    files = json.loads(LIST.read_text())
    files = [f for f in files if not f.get("pdf") and not str(f.get("id", "")).lower().endswith(".pdf")]
    s3 = boto3.client(
        "s3",
        aws_access_key_id=env["ARVAN_ACCESS_KEY"],
        aws_secret_access_key=env["ARVAN_SECRET_KEY"],
        endpoint_url=env["ARVAN_ENDPOINT"],
        region_name=env["ARVAN_REGION"],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=15,
            read_timeout=120,
            retries={"max_attempts": 2},
        ),
    )
    h = {"X-Appwrite-Project": aw["project_id"], "X-Appwrite-Key": aw["api_key"]}
    ep = aw["endpoint"].rstrip("/")
    bid = aw["media_bucket_id"]
    ok = fail = skip = 0
    for f in files:
        fid = f["id"]
        mime = f.get("mime") or mimetypes.guess_type(fid)[0] or "application/octet-stream"
        url = f"{ep}/storage/buckets/{bid}/files/{fid}/view?project={aw['project_id']}"
        try:
            r = requests.get(url, headers=h, timeout=180)
            if r.status_code != 200:
                print("GET_FAIL", fid, r.status_code)
                fail += 1
                continue
            s3.put_object(
                Bucket=env["ARVAN_BUCKET"],
                Key=fid,
                Body=r.content,
                ContentType=mime,
                ACL="public-read",
            )
            ok += 1
            print("OK", fid, len(r.content))
        except Exception as e:
            fail += 1
            print("FAIL", fid, type(e).__name__, str(e)[:180])
    print("done ok", ok, "fail", fail, "skip", skip)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
