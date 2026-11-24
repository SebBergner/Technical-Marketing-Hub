"""Build an AMP-style Value Roadmap index for one demo video (trial, 2026-11-24).

    video  ->  Azure Content Understanding (prebuilt-videoSearch: transcript,
               segments with visual descriptions)
           ->  Azure OpenAI chat model + AMP's taxonomy (JSON schema output)
           ->  <video>.index.json in AMP's shape, checked with
               backend.services.value_index.parse

Reads AZURE_CU_ENDPOINT, AZURE_CU_KEY, AZURE_CU_API_VERSION and
AZURE_OPENAI_ENDPOINT from .env (never printed). The taxonomy is Seb's data
and stays out of git: pass it with --taxonomy (default:
data/runtime/value_index_work/amp_taxonomy.txt, one process per line,
"process-id|Process Name::cap-id|Cap Name;cap-id|Cap Name;...").

Writes only to the local output folder; nothing goes to SharePoint.

    python scripts/index_video.py "C:/path/Creo 13 Teaser_Other.mp4"
    python scripts/index_video.py video.mp4 --skip-cu     # reuse saved CU result
    python scripts/index_video.py video.mp4 --runs 3      # LLM step 3 times
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.services import value_index  # noqa: E402

WORK = ROOT / "data" / "runtime" / "value_index_work"
ANALYZER = "prebuilt-videoSearch"
OPENAI_API_VERSION = "2025-04-01-preview"
VALUE_DRIVERS = ["Customer EX", "Efficiency", "Innovation", "Quality & Regulatory",
                 "Supply Chain", "Workforce"]


# ------------------------------------------------------------------ setup
def load_env() -> dict[str, str]:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m and not line.lstrip().startswith("#"):
            env[m[1]] = m[2].strip('"').strip("'")
    missing = [k for k in ("AZURE_CU_ENDPOINT", "AZURE_CU_KEY", "AZURE_CU_API_VERSION",
                           "AZURE_OPENAI_ENDPOINT") if not env.get(k)]
    if missing:
        sys.exit(f".env lacks {', '.join(missing)}")
    return env


def load_taxonomy(path: Path) -> tuple[str, dict[str, str]]:
    """The prompt text and {tag id: name} for every valid process and
    capability id (capability ids as AMP writes them: process--capability)."""
    text = path.read_text(encoding="utf-8").strip()
    valid: dict[str, str] = {}
    for line in text.splitlines():
        head, _, caps = line.partition("::")
        pid, _, pname = head.partition("|")
        valid[pid.strip()] = pname.strip()
        for cap in filter(None, caps.split(";")):
            cid, _, cname = cap.partition("|")
            valid[f"{pid.strip()}--{cid.strip()}"] = cname.strip()
    return text, valid


def http(method: str, url: str, headers: dict, body: bytes | None = None,
         timeout: int = 300) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, dict(r.headers), (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {url.split('?')[0]} -> {exc.code}: {exc.read()[:800]!r}")


# ------------------------------------------------- Content Understanding
def analyze_video(env: dict, video: Path) -> dict:
    ep = env["AZURE_CU_ENDPOINT"].rstrip("/")
    ver = env["AZURE_CU_API_VERSION"]
    key = {"Ocp-Apim-Subscription-Key": env["AZURE_CU_KEY"]}
    url = f"{ep}/contentunderstanding/analyzers/{ANALYZER}:analyzeBinary?api-version={ver}"
    size_mb = video.stat().st_size / 1e6
    print(f"CU: uploading {video.name} ({size_mb:.1f} MB) to {ANALYZER}")
    t0 = time.time()
    _, headers, _ = http("POST", url, {**key, "Content-Type": "application/octet-stream"},
                         video.read_bytes(), timeout=900)
    op = headers.get("Operation-Location") or headers.get("operation-location")
    if not op:
        sys.exit(f"CU: no Operation-Location header in {list(headers)}")
    while True:
        time.sleep(5)
        _, _, body = http("GET", op, key)
        status = body.get("status")
        if status in ("Succeeded", "Failed", "Canceled"):
            break
        print(f"  {status} after {time.time() - t0:.0f} s")
    if status != "Succeeded":
        sys.exit(f"CU: {status}: {json.dumps(body.get('error'))[:800]}")
    body["_trial"] = {"seconds": round(time.time() - t0, 1), "size_mb": round(size_mb, 1)}
    print(f"CU: done in {body['_trial']['seconds']} s")
    return body


def _ms(value) -> float | None:
    return round(value / 1000, 2) if isinstance(value, (int, float)) else None


def summarise_cu(result: dict) -> tuple[str, dict]:
    """The CU result as compact text for the LLM, plus a few facts about it."""
    contents = (result.get("result") or {}).get("contents") or []
    lines, segments, transcript_chars = [], 0, 0
    for c in contents:
        start, end = _ms(c.get("startTimeMs")), _ms(c.get("endTimeMs"))
        fields = c.get("fields") or {}
        summary = None
        for name in ("Summary", "summary", "Description", "description"):
            f = fields.get(name)
            if isinstance(f, dict):
                summary = f.get("valueString") or f.get("value")
            if summary:
                break
        md = c.get("markdown") or ""
        # Keep the transcript lines; drop keyframe image links.
        md = "\n".join(l for l in md.splitlines() if not l.strip().startswith("!["))
        transcript_chars += sum(len(p.get("text", "")) for p in (c.get("transcriptPhrases") or []))
        segments += 1
        lines.append(f"## Segment {segments}: {start}s - {end}s")
        if summary:
            lines.append(f"Visual/audio description: {summary}")
        if md.strip():
            lines.append(md.strip())
        lines.append("")
    facts = {"segments": segments, "transcript_chars": transcript_chars,
             "duration_s": max((_ms(c.get("endTimeMs")) or 0) for c in contents) if contents else None}
    return "\n".join(lines), facts


# -------------------------------------------------------------- LLM step
def _tag_schema() -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": ["type", "id", "name"],
            "properties": {"type": {"type": "string", "enum": ["process", "capability"]},
                           "id": {"type": "string"}, "name": {"type": "string"}}}


def _term_schema() -> dict:
    return {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["term", "evidence"],
        "properties": {"term": {"type": "string"}, "evidence": {"type": "string"}}}}


def output_schema() -> dict:
    tag = _tag_schema()
    return {"type": "object", "additionalProperties": False,
            "required": ["analysis", "value_roadmap"],
            "properties": {
                "analysis": {
                    "type": "object", "additionalProperties": False,
                    "required": ["description", "products", "primary_area", "confidence",
                                 "tags", "scenes"],
                    "properties": {
                        "description": {"type": "string"},
                        "products": {"type": "array", "items": {"type": "string"}},
                        "primary_area": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
                        "tags": {"type": "array", "items": tag},
                        "scenes": {"type": "array", "items": {
                            "type": "object", "additionalProperties": False,
                            "required": ["start_s", "end_s", "description", "tags"],
                            "properties": {"start_s": {"type": "number"},
                                           "end_s": {"type": "number"},
                                           "description": {"type": "string"},
                                           "tags": {"type": "array", "items": tag}}}}}},
                "value_roadmap": {
                    "type": "object", "additionalProperties": False,
                    "required": ["summary", "value_drivers", "initiatives", "challenges",
                                 "metrics"],
                    "properties": {
                        "summary": {"type": "string"},
                        "value_drivers": {"type": "array", "items": {
                            "type": "string", "enum": VALUE_DRIVERS}},
                        "initiatives": _term_schema(),
                        "challenges": _term_schema(),
                        "metrics": _term_schema()}}}}


PROMPT = """You index PTC demo videos against PTC's Digital Transformation Value Roadmap (2027).
Below is the machine analysis of one video: time-coded segments, each with a description of what is on screen and the spoken transcript (if any). Some videos have music only and no speech; then rely on the visual descriptions.

Rules:
- Tags: use ONLY ids and names from the taxonomy. A process tag uses the process id. A capability tag id is "<process-id>--<capability-id>" (two hyphens) and its process must also be tagged. Never invent ids. Tag only what the video actually shows or says.
- analysis.tags: every process and capability that applies to the video as a whole.
- Scenes: follow the segments' time codes (seconds); merge neighbours that cover the same topic; each scene has 1-3 tags from analysis.tags.
- products: PTC product names as shown or said (e.g. Creo, Windchill, Codebeamer, ServiceMax).
- value_drivers: only from the allowed list.
- initiatives, challenges and metrics: short business terms, each with one sentence of evidence quoted or described from the video. List a metric only when the video states or shows it (a number, a KPI, a claimed improvement); never add one without evidence. Use [] when the video gives none.
- confidence: how well the material supports the tags (Low when there is little speech or on-screen text).

Taxonomy (one process per line: process-id|Process Name::capability-id|Capability Name;...):
{taxonomy}

Video file: {name}
Machine analysis:
{analysis}
"""


def run_llm(env: dict, deployment: str, prompt: str) -> tuple[dict, dict, float]:
    ep = env["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    url = f"{ep}/openai/deployments/{deployment}/chat/completions?api-version={OPENAI_API_VERSION}"
    body = {"messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "value_roadmap_index", "strict": True, "schema": output_schema()}}}
    # gpt-5 family accepts only the default temperature; set it for others.
    if not deployment.startswith(("gpt-5", "o")):
        body["temperature"] = 0
    t0 = time.time()
    _, _, resp = http("POST", url, {"api-key": env["AZURE_CU_KEY"],
                                    "Content-Type": "application/json"},
                      json.dumps(body).encode(), timeout=600)
    elapsed = time.time() - t0
    content = resp["choices"][0]["message"]["content"]
    return json.loads(content), resp.get("usage") or {}, elapsed


def clean_tags(data: dict, valid: dict[str, str]) -> list[str]:
    """Drop tag ids not in the taxonomy; use the taxonomy's names. Returns the
    dropped ids so the trial can report them."""
    dropped = []

    def fix(tags):
        out = []
        for t in tags:
            tid = t.get("id")
            if tid in valid:
                kind = "capability" if "--" in tid else "process"
                out.append({"type": kind, "id": tid, "name": valid[tid]})
            else:
                dropped.append(tid)
        return out

    a = data["analysis"]
    a["tags"] = fix(a["tags"])
    for s in a["scenes"]:
        s["tags"] = fix(s["tags"])
    # A tagged capability's process is tagged too.
    have = {t["id"] for t in a["tags"]}
    for t in list(a["tags"]):
        pid = t["id"].split("--", 1)[0]
        if t["type"] == "capability" and pid not in have:
            a["tags"].insert(0, {"type": "process", "id": pid, "name": valid[pid]})
            have.add(pid)
    return dropped


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("--taxonomy", type=Path, default=WORK / "amp_taxonomy.txt")
    ap.add_argument("--out", type=Path, default=WORK)
    ap.add_argument("--deployment", default=None,
                    help="chat deployment for the taxonomy step (default: CU's gpt-5)")
    ap.add_argument("--skip-cu", action="store_true", help="reuse the saved CU result")
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()

    env = load_env()
    tax_text, valid = load_taxonomy(args.taxonomy)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.video.stem
    cu_path = args.out / f"{stem}.cu.json"

    if args.skip_cu:
        cu = json.loads(cu_path.read_text(encoding="utf-8"))
    else:
        cu = analyze_video(env, args.video)
        cu_path.write_text(json.dumps(cu, indent=1), encoding="utf-8")
        print(f"CU result saved: {cu_path}")
    analysis_text, facts = summarise_cu(cu)
    print(f"CU: {facts['segments']} segments, {facts['transcript_chars']} transcript chars, "
          f"{facts['duration_s']} s; prompt material {len(analysis_text)} chars")

    deployment = args.deployment
    if not deployment:
        ep = env["AZURE_CU_ENDPOINT"].rstrip("/")
        _, _, d = http("GET", f"{ep}/contentunderstanding/defaults?api-version="
                       f"{env['AZURE_CU_API_VERSION']}", {"Ocp-Apim-Subscription-Key": env["AZURE_CU_KEY"]})
        deployment = d["modelDeployments"]["gpt-5"]
    prompt = PROMPT.format(taxonomy=tax_text, name=args.video.name, analysis=analysis_text)

    for run in range(1, args.runs + 1):
        data, usage, secs = run_llm(env, deployment, prompt)
        dropped = clean_tags(data, valid)
        data["analysis"]["used_audio"] = facts["transcript_chars"] > 0
        data["analysis"]["used_visuals"] = True  # CU segment descriptions come from frames
        data["source"] = "azure-content-understanding"
        data["model"] = f"{ANALYZER} + {deployment}"
        data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data["trial"] = {"cu_seconds": (cu.get("_trial") or {}).get("seconds"),
                         "llm_seconds": round(secs, 1), "usage": usage,
                         "dropped_tag_ids": dropped}
        parsed = value_index.parse(data)  # raises NotAnIndex if the Hub can't read it
        suffix = "" if args.runs == 1 else f".run{run}"
        out = args.out / f"{stem}{suffix}.index.json"
        out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"run {run}: {len(parsed['processes'])} processes, "
              f"{len(parsed['capabilities'])} capabilities, {len(parsed['scenes'])} scenes, "
              f"drivers {parsed['value_drivers']}, dropped {len(dropped)} invalid ids, "
              f"{secs:.0f} s, tokens {usage.get('prompt_tokens')}/{usage.get('completion_tokens')}"
              f" -> {out}")


if __name__ == "__main__":
    main()
