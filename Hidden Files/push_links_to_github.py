import base64
import getpass
import re
from pathlib import Path

import requests

API = "https://api.github.com"


def parse_repo_url(url: str):
    url = url.strip().rstrip("/")
    m = re.match(
        r"(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+))?$",
        url,
    )
    if not m:
        raise ValueError("آدرس ریپو معتبر نیست.")
    return m.group(1), m.group(2), m.group(3) or "main"


def api(method, url, token, **kwargs):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "push-links-script",
    }
    kwargs.setdefault("timeout", 60)
    r = requests.request(method, url, headers=headers, **kwargs)
    if r.status_code >= 400:
        print(f"خطای API [{r.status_code}]: {r.text}")
        r.raise_for_status()
    return r.json() if r.text else {}


def get_branch_sha(owner, repo, branch, token):
    return api("GET", f"{API}/repos/{owner}/{repo}/git/ref/heads/{branch}", token)["object"]["sha"]


def get_commit_tree(owner, repo, sha, token):
    return api("GET", f"{API}/repos/{owner}/{repo}/git/commits/{sha}", token)["tree"]["sha"]


def create_blob_text(owner, repo, text, token):
    b64 = base64.b64encode(text.encode("utf-8")).decode()
    return api("POST", f"{API}/repos/{owner}/{repo}/git/blobs", token,
               json={"content": b64, "encoding": "base64"})["sha"]


def create_tree(owner, repo, base_tree_sha, items, token):
    return api("POST", f"{API}/repos/{owner}/{repo}/git/trees", token,
               json={"base_tree": base_tree_sha, "tree": items})["sha"]


def create_commit(owner, repo, tree_sha, parent_sha, message, token):
    return api("POST", f"{API}/repos/{owner}/{repo}/git/commits", token,
               json={"message": message, "tree": tree_sha, "parents": [parent_sha]})["sha"]


def update_ref(owner, repo, branch, commit_sha, token):
    api("PATCH", f"{API}/repos/{owner}/{repo}/git/refs/heads/{branch}", token,
        json={"sha": commit_sha, "force": False})


def make_html(links, title="فهرست کتاب‌ها"):
    rows = "\n".join(
        f'<li><a href="{u}" target="_blank">{u.rstrip("/").split("/")[-1]}</a></li>'
        for u in links
    )
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: Tahoma, sans-serif; padding: 20px; }}
ul {{ line-height: 1.9; }}
a {{ text-decoration: none; color: #0366d6; }}
a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p>تعداد: {len(links)}</p>
<ul>
{rows}
</ul>
</body>
</html>
"""


def main():
    # 1) آدرس ریپو
    repo_url = input("آدرس ریپو GitHub: ").strip()
    try:
        owner, repo, branch = parse_repo_url(repo_url)
    except ValueError as e:
        print(e)
        return
    print(f"  owner={owner}  repo={repo}  branch={branch}")

    # 2) فایل لینک‌ها
    links_file = Path(input("مسیر فایل لینک‌ها: ").strip().strip('"')).expanduser()
    if not links_file.is_file():
        print("فایل لینک پیدا نشد.")
        return

    # 3) پوشه مقصد در ریپو
    dest_folder = input("نام پوشه مقصد در ریپو (مثلاً Books-Full): ").strip().strip("/")
    if not dest_folder:
        print("نام پوشه خالی است.")
        return

    # 4) توکن
    token = getpass.getpass("GitHub Token (نمایش داده نمی‌شود): ").strip()
    if not token:
        return
    try:
        token.encode("ascii")
    except UnicodeEncodeError:
        print("توکن حاوی کاراکتر غیرلاتین است.")
        return
    if not (token.startswith("ghp_") or token.startswith("github_pat_")):
        print("توکن باید با ghp_ یا github_pat_ شروع شود.")
        return

    # خواندن لینک‌ها
    links = [ln.strip() for ln in links_file.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.strip().startswith("#")]

    if not links:
        print("هیچ لینکی در فایل پیدا نشد.")
        return

    print(f"\nتعداد لینک: {len(links)}")
    print(f"مقصد: {owner}/{repo}/{dest_folder}/")

    # محتوای فایل‌ها
    txt_content = "\n".join(links) + "\n"
    html_content = make_html(links, title=f"فهرست کتاب‌ها - {dest_folder}")
    md_content = "\n".join(f"- [{u.rstrip('/').split('/')[-1]}]({u})" for u in links)

    print("\nچه فایل‌هایی ساخته شود؟")
    print("  1) links.txt")
    print("  2) links.md")
    print("  3) index.html")
    print("  4) همه موارد بالا")
    choice = input("انتخاب (1/2/3/4، پیش‌فرض 4): ").strip() or "4"

    files_to_push = {}
    if choice in ("1", "4"):
        files_to_push[f"{dest_folder}/links.txt"] = txt_content
    if choice in ("2", "4"):
        files_to_push[f"{dest_folder}/links.md"] = md_content
    if choice in ("3", "4"):
        files_to_push[f"{dest_folder}/index.html"] = html_content

    if not files_to_push:
        print("هیچ فایلی انتخاب نشد.")
        return

    print("\nفایل‌های زیر ساخته می‌شوند:")
    for p in files_to_push:
        print(f"  {p}")

    if input("ادامه؟ (y/n): ").strip().lower() != "y":
        print("لغو شد.")
        return

    # گرفتن وضعیت فعلی
    print("\nگرفتن وضعیت فعلی ریپو...")
    parent_sha = get_branch_sha(owner, repo, branch, token)
    base_tree = get_commit_tree(owner, repo, parent_sha, token)

    tree_items = []
    for path, content in files_to_push.items():
        print(f"  ساخت blob برای {path} ...")
        blob_sha = create_blob_text(owner, repo, content, token)
        tree_items.append({
            "path": path, "mode": "100644", "type": "blob", "sha": blob_sha,
        })

    print("ساخت tree...")
    new_tree = create_tree(owner, repo, base_tree, tree_items, token)

    print("ساخت commit...")
    new_commit = create_commit(owner, repo, new_tree, parent_sha,
                               f"add {dest_folder} link files ({len(links)} links)", token)

    print("به‌روزرسانی branch...")
    update_ref(owner, repo, branch, new_commit, token)

    print(f"\nتمام شد.")
    for p in files_to_push:
        print(f"  https://github.com/{owner}/{repo}/blob/{branch}/{p}")


if __name__ == "__main__":
    main()