#!/usr/bin/env python
"""One-off: split the single-file mockup into a real document + static assets.

Behaviour-neutral by design. Extracts, it does not rewrite:
  index.html  ->  index.html (document shell + inline SVG sprite)
                  static/css/orion.css
                  static/js/app.js
                  static/img/thumbs/*.jpg   (19 inline base64 JPEGs)

The JS stays a single classic script on purpose. The markup is full of inline
`onclick="pillToggle(this)"` handlers that need those functions on `window`;
ES modules would break every one of them. Modularising belongs with the switch
to API-driven rendering, when the inline handlers go away too.

Run from the repo root:  python scripts/split_mockup.py
"""
import base64
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "index.html")
BACKUP = os.path.join(ROOT, "index.mockup.original.html")

CSS_DIR = os.path.join(ROOT, "static", "css")
JS_DIR = os.path.join(ROOT, "static", "js")
IMG_DIR = os.path.join(ROOT, "static", "img", "thumbs")


def slugify(text, fallback):
    s = re.sub(r"<[^>]+>", "", text).strip().lower()
    s = s.replace("&amp;", "and").replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:60].rstrip("-") or fallback)


def main():
    html = open(SRC, encoding="utf-8").read()
    original_size = len(html.encode("utf-8"))

    if not os.path.exists(BACKUP):
        shutil.copy2(SRC, BACKUP)
        print(f"backup      -> {os.path.relpath(BACKUP, ROOT)}")

    for d in (CSS_DIR, JS_DIR, IMG_DIR):
        os.makedirs(d, exist_ok=True)

    # ---------------------------------------------------------------- CSS
    m = re.search(r"<style>\n?(.*?)\n?</style>", html, re.S)
    if not m:
        sys.exit("could not locate the <style> block")
    css = m.group(1)
    open(os.path.join(CSS_DIR, "orion.css"), "w", encoding="utf-8", newline="\n").write(css + "\n")
    html = html[: m.start()] + "@@CSS@@" + html[m.end():]
    print(f"css         -> static/css/orion.css  ({len(css) // 1024} KB)")

    # ---------------------------------------------------------------- JS
    m = re.search(r"<script>\n?(.*?)\n?</script>", html, re.S)
    if not m:
        sys.exit("could not locate the <script> block")
    js = m.group(1)
    open(os.path.join(JS_DIR, "app.js"), "w", encoding="utf-8", newline="\n").write(js + "\n")
    html = html[: m.start()] + "@@JS@@" + html[m.end():]
    print(f"js          -> static/js/app.js  ({len(js) // 1024} KB)")

    # ------------------------------------------------------- base64 images
    # Name each by the nearest card title so the files stay identifiable.
    pattern = re.compile(r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)")
    used, saved = {}, []

    def replace(match):
        idx = len(saved)
        blob = match.group(1)
        tail = html[match.end(): match.end() + 2500]
        title = re.search(r'class="dvg-card__title"[^>]*>(.*?)</', tail, re.S)
        base = "hero" if idx == 0 else slugify(title.group(1) if title else "", f"thumb-{idx:02d}")
        name = base
        n = 2
        while name in used:
            name, n = f"{base}-{n}", n + 1
        used[name] = True

        data = base64.b64decode(blob)
        with open(os.path.join(IMG_DIR, f"{name}.jpg"), "wb") as fh:
            fh.write(data)
        saved.append((name, len(data)))
        return f"/static/img/thumbs/{name}.jpg"

    html = pattern.sub(replace, html)
    total = sum(s for _, s in saved)
    print(f"images      -> static/img/thumbs/  ({len(saved)} files, {total // 1024} KB)")

    # ------------------------------------------------------ document shell
    body = html.replace("@@CSS@@", "").replace("@@JS@@", "")
    body = re.sub(r"<title>.*?</title>\s*", "", body, count=1, flags=re.S).strip()

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Technical Marketing Hub</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/static/css/orion.css">
</head>
<body>
{body}
<script src="/static/js/app.js"></script>
</body>
</html>
"""
    open(SRC, "w", encoding="utf-8", newline="\n").write(doc)

    new_size = len(doc.encode("utf-8"))
    print(f"\nindex.html  {original_size / 1024 / 1024:.2f} MB -> {new_size / 1024:.0f} KB "
          f"({100 - new_size * 100 // original_size}% smaller)")
    print("\nextracted images:")
    for name, size in saved:
        print(f"  {size // 1024:>4} KB  {name}.jpg")


if __name__ == "__main__":
    main()
