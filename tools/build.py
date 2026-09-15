#!/usr/bin/env python3
"""Stage A: download grade-9 textbooks from chap.sch.ir and dump recon text.

Source site ONLY: http://chap.sch.ir (official textbook portal).
Outputs (committed to repo by the workflow):
  tools/recon/report.json      - per-book pages/size/sha256/status
  tools/recon/<CODE>_full.txt  - full extracted text with === PAGE n === markers
"""
import hashlib
import json
import os
import sys
import time

import requests

BASE = "http://chap.sch.ir/sites/default/files/lbooks/1405-1406/556"
BASE_HTTPS = "https://chap.sch.ir/sites/default/files/lbooks/1405-1406/556"

BOOKS = {
    "C901": "آموزش قرآن (نهم)",
    "C902": "پیام‌های آسمان (نهم)",
    "C903": "فارسی (نهم)",
    "C904": "نگارش (نهم)",
    "C905": "ریاضی (نهم)",
    "C906": "علوم تجربی (نهم)",
    "C907": "مطالعات اجتماعی (نهم)",
    "C908": "فرهنگ و هنر (نهم)",
    "C909": "عربی (نهم)",
    "C910": "انگلیسی (3)",
    "C911": "کتاب کار انگلیسی (3)",
    "C917": "کار و فناوری (نهم)",
    "C941": "از من تا خدا (تربیت دینی) نهم",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "_source")
RECON_DIR = os.path.join(ROOT, "tools", "recon")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
    "Accept-Language": "fa,en;q=0.9",
}


def download(code, dest):
    urls = [f"{BASE}/{code}.pdf", f"{BASE_HTTPS}/{code}.pdf"]
    last_err = ""
    for url in urls:
        for attempt in range(3):
            try:
                print(f"[dl] {code} try {url} (attempt {attempt+1})", flush=True)
                with requests.get(url, headers=HEADERS, timeout=120, stream=True) as r:
                    r.raise_for_status()
                    ctype = r.headers.get("Content-Type", "")
                    total = int(r.headers.get("Content-Length", 0) or 0)
                    print(f"[dl] {code}: status={r.status_code} type={ctype} len={total}", flush=True)
                    tmp = dest + ".part"
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                f.write(chunk)
                with open(tmp, "rb") as f:
                    magic = f.read(5)
                if magic != b"%PDF-":
                    last_err = f"bad magic: {magic!r}"
                    print(f"[dl] {code}: {last_err}", flush=True)
                    os.remove(tmp)
                    continue
                os.replace(tmp, dest)
                print(f"[dl] {code}: OK {os.path.getsize(dest)} bytes", flush=True)
                return True, url
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
                print(f"[dl] {code}: {last_err}", flush=True)
                time.sleep(3)
    return False, last_err


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def recon(code, path):
    import fitz  # pymupdf

    doc = fitz.open(path)
    pages = doc.page_count
    out_path = os.path.join(RECON_DIR, f"{code}_full.txt")
    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"BOOK {code} pages={pages}\n")
        for i, page in enumerate(doc):
            text = page.get_text("text") or ""
            out.write(f"\n\n===== PAGE {i+1}/{pages} =====\n")
            out.write(text)
            if not text.endswith("\n"):
                out.write("\n")
    doc.close()
    return pages


def main():
    os.makedirs(SRC_DIR, exist_ok=True)
    os.makedirs(RECON_DIR, exist_ok=True)
    report = {}
    ok_all = True
    for code, name in BOOKS.items():
        dest = os.path.join(SRC_DIR, f"{code}.pdf")
        entry = {"name": name, "url": f"{BASE}/{code}.pdf"}
        if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
            print(f"[dl] {code}: already present ({os.path.getsize(dest)} bytes)", flush=True)
            entry["download"] = "cached"
        else:
            ok, info = download(code, dest)
            if not ok:
                entry["download"] = f"FAILED: {info}"
                report[code] = entry
                ok_all = False
                continue
            entry["download"] = f"OK via {info}"
        try:
            entry["size"] = os.path.getsize(dest)
            entry["sha256"] = sha256_of(dest)
            entry["pages"] = recon(code, dest)
            print(f"[recon] {code}: {entry['pages']} pages", flush=True)
        except Exception as e:  # noqa: BLE001
            entry["recon"] = f"FAILED: {type(e).__name__}: {e}"
            print(f"[recon] {code} FAILED: {e}", flush=True)
            ok_all = False
        report[code] = entry

    with open(os.path.join(RECON_DIR, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("==== REPORT ====", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2)[:4000], flush=True)
    if not ok_all:
        print("STAGE-A finished WITH FAILURES", flush=True)
        sys.exit(2)
    print("STAGE-A finished OK", flush=True)


if __name__ == "__main__":
    main()
