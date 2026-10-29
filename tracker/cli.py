"""Command-line interface. ``python3 lct.py --help``"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys

from .analytics import dashboard
from .bank import Bank
from .model import OUTCOMES
from .storage import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bar(x: float, width: int = 20) -> str:
    n = max(0, min(width, round(x * width)))
    return "█" * n + "·" * (width - n)


def _find(bank: Bank, ref: str):
    ref = ref.strip()
    if ref.isdigit():
        return bank.by_id.get(int(ref))
    slug = ref.rstrip("/").split("/")[-1].lower()
    return bank.by_slug.get(slug)


def cmd_serve(args) -> None:
    from .server import serve
    serve(args.host, args.port, open_browser=not args.no_browser, data_dir=args.data)


def cmd_log(args) -> None:
    bank, store = Bank.load(), Store(args.data)
    p = _find(bank, args.problem)
    if p is None:
        sys.exit(f"Unknown problem: {args.problem}")
    rec = store.add_attempt({"problemId": p.id, "outcome": args.outcome,
                             "minutes": args.minutes, "wrong": args.wrong,
                             "notes": args.notes or "", "ts": args.when, "source": "self"})
    d = dashboard(bank, store.attempts(), store.settings())
    row = next((r for r in d["recent"] if r["id"] == rec["id"]), None)
    print(f"Logged #{p.id} {p.title} ({p.difficulty}, rated {p.rating:.0f}): "
          f"{args.outcome} in {args.minutes:g} min")
    if row:
        print(f"  score {row['score']:.2f} vs expected {row['expected']:.2f} -> "
              f"overall {row['overallDelta']:+.1f} (now {row['overallAfter']:.0f})")
        for g, v in sorted(row["groupDeltas"].items(), key=lambda kv: -abs(kv[1])):
            print(f"    {g:28s} {v:+.1f}")


def cmd_report(args) -> None:
    bank, store = Bank.load(), Store(args.data)
    d = dashboard(bank, store.attempts(), store.settings())
    o = d["overall"]
    print(f"\nOVERALL  {o['r']:.0f} ±{o['rd']:.0f}   [{o['tier']}]   "
          f"target {o['target']}   7-day {o['weekChange']:+.0f}")
    for diff in ("Easy", "Medium", "Hard"):
        x = o["readiness"][diff]
        print(f"  {diff:6s} readiness {_bar(x)} {x * 100:4.0f}%")
    t = d["totals"]
    print(f"\n{t['attempts']} attempts, {t['unique']} problems, {t['clean']} clean timed solves, "
          f"streak {t['streak']}d, {t['reviewPending']} in review queue\n")
    print(f"{'TOPIC':28s} {'RATING':>7s} {'±':>4s}  {'N':>3s}")
    for grp in sorted(d["groups"], key=lambda x: (-x["rated"], x["r"])):
        if not grp["rated"] and not args.all:
            continue
        mark = "" if grp["rated"] else "  (unrated)"
        print(f"{grp['group']:28s} {grp['r']:7.0f} {grp['rd']:4.0f}  {grp['attempts']:3d}{mark}")
    print()


def cmd_suggest(args) -> None:
    bank, store = Bank.load(), Store(args.data)
    d = dashboard(bank, store.attempts(), store.settings(), shuffle=args.shuffle)
    s = d["suggestions"]
    items = s["review"][:2] + s["focus"] + ([s["mock"]] if s["mock"] else [])
    for it in items:
        p = it["problem"]
        print(f"[{it['kind'].upper():6s}] #{p['id']} {p['title']} ({p['difficulty']}, "
              f"{p['rating']}) - {it['timeLimit']:.0f} min, expected {it['expected']:.2f}")
        print(f"         {p['url']}")
        print(f"         {it['reason']}")


def cmd_sync(args) -> None:
    script = os.path.join(ROOT, "scripts", "sync_problems.py")
    raise SystemExit(subprocess.call([sys.executable, script, *args.rest]))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="lct", description="LeetCode Strength Tracker")
    ap.add_argument("--data", help="directory for your log (default data/user)")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="run the web dashboard (default)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("log", help="log an attempt")
    s.add_argument("problem", help="problem number, slug, or URL")
    s.add_argument("outcome", choices=OUTCOMES)
    s.add_argument("minutes", type=float)
    s.add_argument("--wrong", type=int, default=0, help="wrong submissions")
    s.add_argument("--notes")
    s.add_argument("--when", help="ISO timestamp (default now)")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("report", help="print your ratings")
    s.add_argument("--all", action="store_true", help="include unrated topics")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("suggest", help="what to practise next")
    s.add_argument("--shuffle", type=int, default=0)
    s.set_defaults(fn=cmd_suggest)

    s = sub.add_parser("sync", help="refresh the problem bank from LeetCode")
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_sync)

    args = ap.parse_args(argv)
    if args.cmd is None:
        args = ap.parse_args([*(["--data", args.data] if args.data else []), "serve"])
    args.fn(args)


if __name__ == "__main__":
    main()
