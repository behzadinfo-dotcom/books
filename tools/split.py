#!/usr/bin/env python3
"""Stage B: split grade-9 textbooks into per-section PDFs.

Source site ONLY: http://chap.sch.ir (official textbook portal).
- If the book's page on chap.sch.ir offers official per-section PDFs, those are
  used as-is (most faithful).
- Otherwise the full book PDF is sliced per tools/split_plan.json anchors.

Outputs (committed by the workflow):
  <CODE-folder>/*.pdf            - one PDF per stavish/poodman/jalase/dars/fasl
  tools/recon/split_manifest.json - page ranges + match diagnostics
"""
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import BASE, BOOKS, SRC_DIR, download  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECON_DIR = os.path.join(ROOT, "tools", "recon")
PLAN_PATH = os.path.join(ROOT, "tools", "split_plan.json")

# chap.sch.ir book-node ids for 1405-1406
BOOK_NODES = {
    "C901": 14236, "C902": 14237, "C903": 14238, "C904": 14239,
    "C905": 14240, "C906": 14241, "C907": 14242, "C908": 14243,
    "C909": 14244, "C910": 14245, "C911": 14246, "C917": 14247,
    "C941": 14967,
}

FOLDERS = {
    "C901": "901-آموزش-قرآن-نهم",
    "C902": "902-پیام-های-آسمان-نهم",
    "C903": "903-فارسی-نهم",
    "C904": "904-نگارش-نهم",
    "C905": "905-ریاضی-نهم",
    "C906": "906-علوم-تجربی-نهم",
    "C907": "907-مطالعات-اجتماعی-نهم",
    "C908": "908-فرهنگ-و-هنر-نهم",
    "C909": "909-عربی-نهم",
    "C910": "910-زبان-انگلیسی-نهم",
    "C911": "911-کتاب-کار-زبان-انگلیسی-نهم",
    "C917": "917-کار-و-فناوری-نهم",
    "C941": "941-از-من-تا-خدا-تربیت-دینی-نهم",
}

AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
DIACRITICS = re.compile(r"[ً-ٰٟـ‌‍\u200b-\u200f\u202a-\u202e]")
PUNCT = "«»()[]{}.,،؟?!:؛-–—…·•\"'\\/‹›_|+=\r\n\t "


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    table = str.maketrans({
        "ك": "ک", "ي": "ی", "ى": "ی", "ة": "ه", "ۀ": "ه",
        "ؤ": "و", "ئ": "ی", "أ": "ا", "إ": "ا", "آ": "ا",
    } | {a: f for a, f in zip(AR_DIGITS, FA_DIGITS)})
    s = s.translate(table)
    s = DIACRITICS.sub("", s)
    for ch in PUNCT:
        s = s.replace(ch, "")
    return s


def safe_name(s: str) -> str:
    for ch in '«»()[]{}"\'\\/‹›|:*?<>|':
        s = s.replace(ch, "")
    s = re.sub(r"\s+", "-", s.strip(" .،؟!:-–—"))
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def page_texts(doc):
    """Return (full_norm_texts, bigfont_norm_texts) per page."""
    full, big = [], []
    for page in doc:
        d = page.get_text("dict")
        spans_all, spans_big = [], []
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "")
                    spans_all.append(t)
                    if span.get("size", 0) >= 13.0:
                        spans_big.append(t)
        full.append(normalize(" ".join(spans_all)))
        big.append(normalize(" ".join(spans_big)))
    return full, big


def find_anchor(full, big, anchors, cursor):
    """Tiered sequential search. Returns (page_idx, tier, n_candidates, tried)."""
    tried = []
    for tier, corpus in (("bigfont", big), ("fulltext", full)):
        for a in anchors:
            na = normalize(a)
            if len(na) < 4:
                tried.append(f"{a!r}:too-short")
                continue
            cands = [i for i in range(cursor, len(corpus)) if na in corpus[i]]
            tried.append(f"{a!r}:{len(cands)}@{tier}")
            if cands:
                return cands[0], tier, len(cands), tried
    return None, None, 0, tried


def split_by_plan(code, pdf_path):
    import fitz  # noqa: F401  (imported for availability check)
    from pypdf import PdfReader, PdfWriter

    with open(PLAN_PATH, encoding="utf-8") as f:
        plan = json.load(f)
    entry = (plan.get("books") or {}).get(code)
    if not entry or not entry.get("sections"):
        return {"status": "no-plan", "outputs": []}

    import fitz
    doc = fitz.open(pdf_path)
    full, big = page_texts(doc)
    n = doc.page_count
    doc.close()

    folder = os.path.join(ROOT, entry.get("folder") or FOLDERS[code])
    os.makedirs(folder, exist_ok=True)

    sections = entry["sections"]
    starts, diag = [], []
    cursor = 0
    for idx, sec in enumerate(sections, 1):
        if sec.get("from_start"):
            starts.append(0)
            diag.append({"file": sec["file"], "start": 1,
                         "note": "from_start"})
            continue
        anchors = sec.get("anchors") or []
        if not anchors:
            return {"status": f"section-{idx}-has-no-anchors",
                    "outputs": [], "diag": diag}
        p, tier, ncand, tried = find_anchor(full, big, anchors, cursor)
        if p is None:
            return {"status": f"anchor-not-found: section {idx} {sec['file']}",
                    "outputs": [], "diag": diag, "tried": tried}
        starts.append(p)
        cursor = p + 1
        diag.append({"file": sec["file"], "start": p + 1, "tier": tier,
                     "candidates": ncand, "tried": tried})

    reader = PdfReader(pdf_path)
    assert len(reader.pages) == n
    outputs = []
    for idx, sec in enumerate(sections, 1):
        s = starts[idx - 1]
        e = (starts[idx] - 1) if idx < len(sections) and starts[idx] > s else (
            starts[idx] if idx < len(sections) else n - 1)
        e = max(e, s)
        w = PdfWriter()
        for p in range(s, e + 1):
            w.add_page(reader.pages[p])
        fname = f"{idx:02d}-{safe_name(sec['file'])}.pdf"
        out = os.path.join(folder, fname)
        with open(out, "wb") as f:
            w.write(f)
        outputs.append({"file": fname, "pages": [s + 1, e + 1],
                        "n_pages": e - s + 1})
        diag[idx - 1]["pages"] = [s + 1, e + 1]
    return {"status": "ok", "outputs": outputs, "diag": diag}


def official_sections(code):
    """Check the chap.sch.ir book page for official per-section PDF files."""
    import requests
    node = BOOK_NODES[code]
    url = f"http://www.chap.sch.ir/books/{node}"
    r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    html = r.text
    links = re.findall(
        r'<a[^>]*href="([^"]*?/lbooks/1405-1406/556/([^"]+?\.pdf))"[^>]*>(.*?)</a>',
        html, re.S)
    seen, items = set(), []
    for href, fname, text in links:
        text = re.sub(r"<[^>]+>", "", text).strip()
        if fname in seen:
            continue
        seen.add(fname)
        items.append({"file": fname, "title": text or fname, "url": href
                      if href.startswith("http") else "http://www.chap.sch.ir" + href})
    full = [i for i in items if i["file"].lower() == f"{code.lower()}.pdf"]
    parts = [i for i in items if i["file"].lower() != f"{code.lower()}.pdf"]
    return full, parts


def main():
    os.makedirs(RECON_DIR, exist_ok=True)
    with open(PLAN_PATH, encoding="utf-8") as f:
        plan = json.load(f)
    manifest = {"books": {}}
    for code in BOOKS:
        print(f"===== {code} =====", flush=True)
        m = {"folder": FOLDERS[code]}
        pdf_path = os.path.join(SRC_DIR, f"{code}.pdf")
        if not (os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100_000):
            ok, info = download(code, pdf_path)
            if not ok:
                m["status"] = f"download-failed: {info}"
                manifest["books"][code] = m
                continue
        try:
            full, parts = official_sections(code)
            m["official_full"] = [i["file"] for i in full]
            m["official_parts"] = [i["file"] for i in parts]
            print(f"[{code}] official: full={len(full)} parts={len(parts)}", flush=True)
        except Exception as e:  # noqa: BLE001
            m["official_check"] = f"FAILED: {type(e).__name__}: {e}"
            parts = []
            print(f"[{code}] official check failed: {e}", flush=True)
        if len(parts) >= 2:
            folder = os.path.join(ROOT, FOLDERS[code])
            os.makedirs(folder, exist_ok=True)
            outs = []
            for idx, p in enumerate(parts, 1):
                dest = os.path.join(folder, f"{idx:02d}-{safe_name(p['title'])}.pdf")
                if not os.path.exists(dest):
                    # download via absolute URL:
                    import requests
                    try:
                        print(f"[{code}] dl part {p['file']} ...", flush=True)
                        with requests.get(p["url"], timeout=120, stream=True,
                                          headers={"User-Agent": "Mozilla/5.0"}) as r:
                            r.raise_for_status()
                            with open(dest + ".part", "wb") as f:
                                for ch in r.iter_content(chunk_size=1 << 18):
                                    if ch:
                                        f.write(ch)
                        os.replace(dest + ".part", dest)
                        outs.append({"file": os.path.basename(dest),
                                     "title": p["title"]})
                    except Exception as e:  # noqa: BLE001
                        m.setdefault("part_errors", []).append(f"{p['file']}: {e}")
                else:
                    outs.append({"file": os.path.basename(dest),
                                 "title": p["title"]})
            m["status"] = "official-parts"
            m["outputs"] = outs
            manifest["books"][code] = m
            continue
        try:
            r = split_by_plan(code, pdf_path)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            r = {"status": f"split-error: {type(e).__name__}: {e}", "outputs": []}
        m.update(r)
        print(f"[{code}] {r.get('status')} outputs={len(r.get('outputs', []))}", flush=True)
        manifest["books"][code] = m

    with open(os.path.join(RECON_DIR, "split_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("SPLIT finished", flush=True)


if __name__ == "__main__":
    main()
