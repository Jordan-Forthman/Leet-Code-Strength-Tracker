#!/usr/bin/env python3
"""Build / refresh the problem bank at data/problems.json.

Sources, in order of preference:
  1. LeetCode's public GraphQL API (number, title, slug, difficulty, tags,
     acceptance rate, premium flag).
  2. A GitHub mirror of the full problem set (used automatically if LeetCode
     is unreachable or changes its API; also supplies like counts).
  3. zerotrac/leetcode_problem_rating -- Elo-style difficulty ratings computed
     from real contest results, for ~2,600 contest problems.

Problems without a contest rating get an *estimated* rating from a per-difficulty
regression on logit(acceptance rate), fitted against the contest-rated problems.

Usage:
    python3 scripts/sync_problems.py              # try LeetCode, fall back to mirror
    python3 scripts/sync_problems.py --source mirror
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "problems.json")

LEETCODE_GRAPHQL = "https://leetcode.com/graphql"
MIRROR_URL = ("https://raw.githubusercontent.com/noworneverev/leetcode-api/"
              "main/data/leetcode_questions.json")
ZEROTRAC_URL = ("https://raw.githubusercontent.com/zerotrac/leetcode_problem_rating/"
                "main/data.json")

UA = "Mozilla/5.0 (leetcode-strength-tracker sync)"

Q_V1 = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int,
                             $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(categorySlug: $categorySlug, limit: $limit,
                                       skip: $skip, filters: $filters) {
    total: totalNum
    questions: data {
      acRate difficulty frontendQuestionId: questionFrontendId
      paidOnly: isPaidOnly title titleSlug topicTags { name slug }
    }
  }
}"""

Q_V2 = """
query problemsetQuestionListV2($filters: QuestionFilterInput, $limit: Int,
                               $skip: Int, $categorySlug: String) {
  problemsetQuestionListV2(filters: $filters, limit: $limit, skip: $skip,
                           categorySlug: $categorySlug) {
    questions {
      questionFrontendId title titleSlug difficulty acRate paidOnly
      topicTags { name slug }
    }
    totalLength
    hasMore
  }
}"""


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _graphql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(LEETCODE_GRAPHQL, data=body, headers={
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com/problemset/",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    if data.get("errors"):
        raise RuntimeError(data["errors"][0].get("message", "GraphQL error"))
    return data["data"]


def _norm_difficulty(d: str) -> str:
    return {"EASY": "Easy", "MEDIUM": "Medium", "HARD": "Hard"}.get(d.upper(), d.title())


def _norm_ac(ac) -> float | None:
    if ac is None:
        return None
    if isinstance(ac, str):
        ac = ac.rstrip("%")
    ac = float(ac)
    return round(ac * 100 if ac <= 1.0 else ac, 2)


def fetch_leetcode() -> list[dict]:
    page = 500
    for name, query, extract in (
        ("v1", Q_V1, lambda d: (d["problemsetQuestionList"]["questions"],
                               d["problemsetQuestionList"]["total"])),
        ("v2", Q_V2, lambda d: (d["problemsetQuestionListV2"]["questions"],
                               d["problemsetQuestionListV2"]["totalLength"])),
    ):
        try:
            out: list[dict] = []
            skip = 0
            while True:
                data = _graphql(query, {"categorySlug": "algorithms", "limit": page,
                                        "skip": skip, "filters": {}})
                qs, total = extract(data)
                out.extend(qs)
                skip += page
                print(f"  leetcode[{name}]: {len(out)}/{total}", file=sys.stderr)
                if not qs or skip >= total:
                    break
                time.sleep(0.5)
            problems = []
            for q in out:
                fid = str(q["frontendQuestionId"])
                if not fid.isdigit():
                    continue
                problems.append({
                    "id": int(fid),
                    "title": q["title"],
                    "slug": q["titleSlug"],
                    "difficulty": _norm_difficulty(q["difficulty"]),
                    "acRate": _norm_ac(q.get("acRate")),
                    "paid": bool(q.get("paidOnly")),
                    "tags": [t["name"] for t in q.get("topicTags") or []],
                })
            if problems:
                return problems
        except Exception as e:  # noqa: BLE001 - fall through to next strategy
            print(f"  leetcode[{name}] failed: {e}", file=sys.stderr)
    raise RuntimeError("LeetCode API unavailable")


def fetch_mirror() -> list[dict]:
    print("  downloading mirror (~40 MB)...", file=sys.stderr)
    raw = json.loads(_get(MIRROR_URL, timeout=300))
    problems = []
    for item in raw:
        q = item["data"]["question"]
        if q.get("categoryTitle") != "Algorithms":
            continue
        fid = str(q["questionFrontendId"])
        if not fid.isdigit():
            continue
        stats = json.loads(q.get("stats") or "{}")
        problems.append({
            "id": int(fid),
            "title": q["title"],
            "slug": q["url"].rstrip("/").split("/")[-1],
            "difficulty": _norm_difficulty(q["difficulty"]),
            "acRate": _norm_ac(stats.get("acRate")),
            "paid": bool(q.get("isPaidOnly")),
            "tags": [t["name"] for t in q.get("topicTags") or []],
            "likes": q.get("likes"),
        })
    return problems


def fetch_zerotrac() -> dict[str, float]:
    raw = json.loads(_get(ZEROTRAC_URL))
    return {r["TitleSlug"]: float(r["Rating"]) for r in raw}


def _logit(p: float) -> float:
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def fit_rating_model(problems: list[dict], ratings: dict[str, float]) -> dict:
    """Per difficulty: rating ~ a + b * logit(acRate), fitted on contest-rated problems."""
    model = {}
    for diff in ("Easy", "Medium", "Hard"):
        pts = [(_logit(p["acRate"] / 100), ratings[p["slug"]]) for p in problems
               if p["difficulty"] == diff and p["slug"] in ratings and p["acRate"]]
        if len(pts) < 20:
            model[diff] = {"a": {"Easy": 1250, "Medium": 1650, "Hard": 2250}[diff],
                           "b": 0.0, "residual_sd": 250.0, "n": len(pts)}
            continue
        mx = statistics.mean(x for x, _ in pts)
        my = statistics.mean(y for _, y in pts)
        b = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
        a = my - b * mx
        resid = statistics.pstdev([y - (a + b * x) for x, y in pts])
        model[diff] = {"a": round(a, 1), "b": round(b, 1),
                       "residual_sd": round(resid, 1), "n": len(pts)}
    return model


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["auto", "leetcode", "mirror"], default="auto")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    source = None
    problems: list[dict] = []
    if args.source in ("auto", "leetcode"):
        print("Fetching from LeetCode GraphQL...", file=sys.stderr)
        try:
            problems = fetch_leetcode()
            source = "leetcode"
        except Exception as e:  # noqa: BLE001
            if args.source == "leetcode":
                sys.exit(f"LeetCode fetch failed: {e}")
            print(f"  -> {e}; falling back to mirror", file=sys.stderr)
    if not problems:
        print("Fetching from GitHub mirror...", file=sys.stderr)
        problems = fetch_mirror()
        source = "mirror"

    # Keep like counts from the previous bank when the source lacks them.
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                old = {p["slug"]: p for p in json.load(f)["problems"]}
            for p in problems:
                if p.get("likes") is None and p["slug"] in old:
                    p["likes"] = old[p["slug"]].get("likes")
        except (OSError, ValueError, KeyError):
            pass

    print("Fetching zerotrac contest ratings...", file=sys.stderr)
    try:
        ratings = fetch_zerotrac()
    except Exception as e:  # noqa: BLE001
        print(f"  zerotrac unavailable ({e}); all ratings will be estimated", file=sys.stderr)
        ratings = {}

    model = fit_rating_model(problems, ratings)
    for p in problems:
        if p["slug"] in ratings:
            p["rating"] = round(ratings[p["slug"]], 1)
            p["ratingSource"] = "contest"
        else:
            m = model[p["difficulty"]]
            x = _logit(p["acRate"] / 100) if p["acRate"] else 0.0
            p["rating"] = round(m["a"] + m["b"] * x, 1)
            p["ratingSource"] = "estimated"

    problems.sort(key=lambda p: p["id"])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    payload = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "ratingModel": model,
        "problems": problems,
    }
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write('{\n')
        f.write(f'"generated": {json.dumps(payload["generated"])},\n')
        f.write(f'"source": {json.dumps(source)},\n')
        f.write(f'"ratingModel": {json.dumps(model)},\n')
        f.write('"problems": [\n')
        f.write(",\n".join(json.dumps(p, ensure_ascii=False, separators=(",", ":"))
                           for p in problems))
        f.write("\n]\n}\n")
    os.replace(tmp, args.out)
    rated = sum(p["ratingSource"] == "contest" for p in problems)
    print(f"Wrote {len(problems)} problems ({rated} contest-rated) from {source} -> {args.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
