"""Christine's IoT/AR sheet -> a checked run file for GXC Video (B10, 2026-11-03).

Read-only everywhere: SharePoint and Brightcove are only read; nothing is
uploaded. Writes, into OUT_DIR:

  report.md     what to look at before running, in Chinese
  run.csv       the manifest to upload on the Migration page (GXC rows only)
  rows.csv      every row with its flags, for checking by hand

Rules (BACKLOG B10, Liwei 11/02):
  * Everything goes to GXC Video: a row on a tab without "(GXC Gallery)" would
    go to Demo Video, open to everyone, so it is left out of run.csv and the
    report says STOP.
  * hub_products and products stay empty, so the divested rule does not hide
    the videos from the GXC group; the product names go into Gallery Section,
    which keyword search reads.
  * Operator Advisor / SCPA / BOM Costing rows are uploaded too and flagged,
    for Liwei to archive afterwards.
  * Already in GXC Video (same Brightcove ID): skipped by the run itself.
    Already in Demo Video: flagged (archive the Demo Video copy afterwards).

Usage:  python -P scripts/check_iot_sheet.py <sheet.xlsx> <out dir>
"""
import collections
import csv
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)

from backend.config import settings                                    # noqa: E402
from backend.integrations.graph import migration_writer as w            # noqa: E402
from backend.services import gallery_sheet, migration_jobs as j, taxonomy   # noqa: E402
from backend.services.brightcove_runner import COLUMNS                  # noqa: E402

SHEET, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)

OA_TERMS = {
    "Operator Advisor": re.compile(r"operator[\s_\-]*advisor", re.I),
    "SCPA": re.compile(r"(?<![a-z])scpa(?![a-z])|smart connected product accelerator|scp accelerator", re.I),
    "BOM Costing": re.compile(r"bom[\s_\-]*cost|cost(ing)?[\s_\-]*app", re.I),
}


def text_of(r: dict) -> str:
    return " ".join(str(r.get(k) or "") for k in
                    ("title", "description", "long_description", "gallery_section",
                     "hub_products", "named_customer"))


# ── 1. the sheet, through the Hub's own parser ────────────────────────────
rows, report = gallery_sheet.read(SHEET)
ids = collections.Counter(r["brightcove_id"] for r in rows)
not_gxc = [r for r in rows if r["gallery"] != "GXC Gallery"]
gxc_rows = [r for r in rows if r["gallery"] == "GXC Gallery"]

# ── 2. B10's rules ────────────────────────────────────────────────────────
for r in rows:
    products = [p for p in r["hub_products"].split(";") if p]
    r["_products_from_tags"] = ", ".join(products)
    r["_divested"] = ", ".join(p for p in products if taxonomy.is_excluded([p]))
    seen = text_of(r).lower()
    extra = [p for p in products if p.lower() not in (r["gallery_section"] + " " + r["title"]).lower()]
    if extra:
        r["gallery_section"] = "; ".join(x for x in [r["gallery_section"]] + extra if x)
    r["hub_products"] = r["products"] = ""
    r["_oa"] = ", ".join(t for t, rx in OA_TERMS.items() if rx.search(seen))
    r["_dup_in_sheet"] = "yes" if ids[r["brightcove_id"]] > 1 else ""

run_csv = os.path.join(OUT, "run.csv")
gallery_sheet.write_manifest(gxc_rows, run_csv)

# ── 3. the Hub's own read-only checks: options, what exists ───────────────
# As migration_jobs._prepare, without Brightcove: this machine has no
# Brightcove credentials. The Migration page's preview checks the IDs.
from backend.services import brightcove_runner as run                   # noqa: E402
graph, _ = j.clients()
gxc_lib = w.LibraryTarget.resolve(graph, settings.migration_gxc_library, allow_production=True)
terms = w.TermIndex.load(graph, gxc_lib.site_id, settings.migration_product_term_set)
records = run.load_manifest(run_csv)
run.validate(records, gxc_lib.choices, terms)
status = run.plan(records, w.existing_by_brightcove_id(graph, gxc_lib), w.folder_names(graph, gxc_lib))
problems = {r.brightcove_id: r.problems for r in records}
demo_video = w.LibraryTarget.resolve(graph, settings.migration_brightcove_library,
                                     allow_production=True)
in_demo_video = w.existing_by_brightcove_id(graph, demo_video)
demo_video_names = w.folder_names(graph, demo_video)
by_id = {r.brightcove_id: r for r in records}
for r in gxc_rows:
    rec = by_id.get(r["brightcove_id"])
    r["_status"] = status.get(r["brightcove_id"], "")
    r["_problems"] = "; ".join(problems.get(r["brightcove_id"]) or [])
    r["_in_demo_video"] = (in_demo_video[r["brightcove_id"]].get("name")
                           if r["brightcove_id"] in in_demo_video else "")
    r["_same_title_in_demo_video"] = ("yes" if rec and rec.folder_name.lower() in demo_video_names
                                      and not r["_in_demo_video"] else "")
for r in not_gxc:
    r["_status"] = "left out: not a (GXC Gallery) tab"

# ── 4. rows.csv and report.md ─────────────────────────────────────────────
flags = ["_sheet", "_status", "_problems", "_oa", "_divested", "_products_from_tags",
         "_in_demo_video", "_same_title_in_demo_video", "_dup_in_sheet"]
with open(os.path.join(OUT, "rows.csv"), "w", encoding="utf-8-sig", newline="") as fh:
    out = csv.DictWriter(fh, fieldnames=flags + list(COLUMNS), extrasaction="ignore")
    out.writeheader()
    out.writerows(rows)

count = collections.Counter(r["_status"] for r in gxc_rows)


def bullet(items, fmt):
    return "\n".join("- " + fmt(r) for r in items) or "- 无"


oa = [r for r in gxc_rows if r["_oa"]]
bad = [r for r in gxc_rows if r["_status"] in ("invalid", "conflict")]
dv = [r for r in gxc_rows if r["_in_demo_video"] or r["_same_title_in_demo_video"]]
md = f"""# IoT/AR 表检查

表：`{os.path.basename(SHEET)}`
共 {len(rows)} 行（打了 Delete?/Archive? 的不算）。GXC Gallery tab：{len(gxc_rows)} 行；其他 tab：{len(not_gxc)} 行。

## 结论

{"**停：有不在 \"(GXC Gallery)\" tab 里的行，它们会进 Demo Video、对所有人开放，已从 run.csv 去掉。先问 Christine。**" if not_gxc else "所有行都在 \"(GXC Gallery)\" tab 里，会进 GXC Video。"}

- 可以上传（new）：{count.get("new", 0)}
- GXC Video 里已有，同一个 Brightcove ID（existing，运行时自动跳过）：{count.get("existing", 0)}
- 有问题，运行时会跳过（invalid）：{count.get("invalid", 0)}
- 同名文件夹已存在、ID 不同（conflict，要人来定）：{count.get("conflict", 0)}

## 要先处理的

### 有问题的行
{bullet(bad, lambda r: f'{r["brightcove_id"]} {r["title"]}（{r["_sheet"]}）：{r["_status"]}，{r["_problems"] or "同名文件夹已存在"}')}

### Demo Video 里已有（传完后归档 Demo Video 那份）
{bullet(dv, lambda r: f'{r["brightcove_id"]} {r["title"]}：' + ("同一个 ID，文件夹 " + r["_in_demo_video"] if r["_in_demo_video"] else "标题相同、ID 不同，确认是不是同一个视频"))}

### 表内重复的 Brightcove ID
{bullet([r for r in gxc_rows if r["_dup_in_sheet"]], lambda r: f'{r["brightcove_id"]} {r["title"]}（{r["_sheet"]}）')}

### 不在 GXC Gallery tab 的行
{bullet(not_gxc, lambda r: f'{r["brightcove_id"]} {r["title"]}（tab：{r["_sheet"]}）')}

## 传完以后由 Liwei 归档：Operator Advisor / SCPA / BOM Costing
{bullet(oa, lambda r: f'{r["brightcove_id"]} {r["title"]}（{r["_oa"]}）')}

## 按 B10 做的改动
- `hub_products`、`products` 全部留空。原来 tag 里的产品名补进 Gallery Section（已在 Section 或标题里的不重复加），共 {sum(1 for r in gxc_rows if r["_products_from_tags"])} 行。
- 其中带已出售产品的 {sum(1 for r in gxc_rows if r["_divested"])} 行：留空后不会被隐藏规则去掉，GXC 组能看到。
- Segment 按表里的值；GXC Video 的选项有 IoT、AR。

## 怎么运行
在 staging 的 Migration 页面上传 `run.csv`。这里没有查 Brightcove（本机没有 Brightcove 凭据），预览会查每个 ID 在 Brightcove 里是否存在；先看预览的数字和这里一致，再运行。
"""
open(os.path.join(OUT, "report.md"), "w", encoding="utf-8").write(md)
print(f"rows {len(rows)} | gxc {len(gxc_rows)} | not gxc {len(not_gxc)} | {dict(count)} "
      f"| OA/SCPA {len(oa)} | in Demo Video {len(dv)}")
print("written:", os.path.join(OUT, "report.md"))
