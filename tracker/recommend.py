"""What to practise next.

Three sources of suggestions, in priority order:

1. **Review** -- problems you failed / needed help on / solved too slowly come
   back on a spaced-repetition schedule (2 or 4 days, then x2.5 after each
   clean re-solve, graduating after a ~3-week interval).
2. **Focus** -- the topic groups with the highest *need*, where need weighs how
   common the topic is in assessments, how far its rating is below the
   assessment-ready target, and how uncertain the rating still is. For each,
   pick an unseen problem pitched where you're expected to score ~60%:
   hard enough to stretch, easy enough to finish.
3. **Mock** -- one timed Medium at typical assessment difficulty, with tags
   hidden in the UI so you have to identify the pattern yourself, like the real
   thing.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import random

from .bank import Bank, Problem
from .model import (ModelState, Rating, TOPIC_PRIOR_RD, expected_score, parse_ts,
                    target_rating, time_limit_for)
from .topics import GROUP_IMPORTANCE

CLEAN_SCORE = 0.78          # at/above this an attempt counts as a clean, timed solve
REVIEW_FAIL_DAYS = 2.0      # failed / needed solution
REVIEW_SHAKY_DAYS = 4.0     # hint, over time, or sloppy
REVIEW_GROWTH = 2.5
REVIEW_GRADUATE_DAYS = 21.0
STRETCH_EXPECTATION = 0.60  # aim focus problems where you'd expect to score this


def review_states(state: ModelState) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for sa in state.scored:
        pid = sa.problem.id
        ts = parse_ts(sa.attempt["ts"])
        st = out.get(pid)
        if sa.score >= CLEAN_SCORE:
            if st and st["active"]:
                st["interval"] *= REVIEW_GROWTH
                st["due"] = ts + dt.timedelta(days=st["interval"])
                st["lastScore"] = sa.score
                if st["interval"] > REVIEW_GRADUATE_DAYS:
                    st["active"] = False
                    st["graduated"] = True
        else:
            interval = REVIEW_FAIL_DAYS if sa.score < 0.2 else REVIEW_SHAKY_DAYS
            out[pid] = {
                "active": True,
                "interval": interval,
                "due": ts + dt.timedelta(days=interval),
                "lapses": (st["lapses"] if st else 0) + 1,
                "lastScore": sa.score,
                "graduated": False,
            }
    return out


def predicted_skill(problem: Problem, state: ModelState, now: dt.datetime) -> tuple[float, float]:
    """Precision-weighted blend of overall + topic ratings relevant to a problem."""
    parts = [(state.overall, 1.0)]
    for grp, w in problem.group_weights.items():
        if grp in state.groups:
            parts.append((state.groups[grp], w))
    num = den = 0.0
    for rating, w in parts:
        rd = rating.snapshot(now)["rd"]
        prec = w / (rd * rd)
        num += prec * rating.r
        den += prec
    return num / den, math.sqrt(1.0 / den)


def expected_for(problem: Problem, state: ModelState, now: dt.datetime) -> float:
    skill, _ = predicted_skill(problem, state, now)
    return expected_score(skill, problem.rating, problem.rating_rd)


def group_needs(bank: Bank, state: ModelState, now: dt.datetime) -> list[dict]:
    target = target_rating(bank)
    recent_cut = now - dt.timedelta(days=3)
    recent: dict[str, float] = {}
    for sa in state.scored:
        if parse_ts(sa.attempt["ts"]) >= recent_cut:
            for grp, w in sa.problem.group_weights.items():
                if w >= 0.5:
                    recent[grp] = recent.get(grp, 0.0) + 1
    out = []
    for grp in bank.groups():
        imp = GROUP_IMPORTANCE.get(grp, 0.2)
        rating = state.groups.get(grp) or Rating(state.overall.r, TOPIC_PRIOR_RD)
        snap = rating.snapshot(now)
        gap = max(0.0, target - rating.r) / 200.0
        explore = snap["rd"] / 350.0
        need = imp * (gap + 0.6 * explore + 0.15) - 0.25 * recent.get(grp, 0.0)
        out.append({"group": grp, "need": round(need, 3), "r": round(rating.r, 1),
                    "rd": snap["rd"], "importance": imp, "gap": round(gap * 200),
                    "recent": recent.get(grp, 0.0)})
    out.sort(key=lambda x: -x["need"])
    return out


def _popularity(p: Problem) -> float:
    return min(math.log10((p.likes or 0) + 1) / 5.0, 1.0)


def _rng(now: dt.datetime, salt: str) -> random.Random:
    h = hashlib.sha256(f"{now.date().isoformat()}|{salt}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _eligible(p: Problem, settings: dict, last_seen: dict[int, dt.datetime],
              now: dt.datetime) -> bool:
    if p.paid and not settings.get("includePremium"):
        return False
    return p.id not in last_seen


def suggest(bank: Bank, state: ModelState, settings: dict, now: dt.datetime,
            n_focus: int = 3, shuffle: int = 0) -> dict:
    last_seen: dict[int, dt.datetime] = {}
    for sa in state.scored:
        last_seen[sa.problem.id] = parse_ts(sa.attempt["ts"])
    attempts_today = sum(1 for sa in state.scored
                         if parse_ts(sa.attempt["ts"]).date() == now.date())
    salt = f"{attempts_today}|{shuffle}"

    def item(kind: str, p: Problem, reason: str, **extra) -> dict:
        return {"kind": kind, "problem": p.to_json(), "reason": reason,
                "expected": round(expected_for(p, state, now), 3),
                "timeLimit": time_limit_for(p, settings), **extra}

    # 1. Spaced-repetition reviews
    reviews = []
    for pid, st in review_states(state).items():
        if st["active"] and st["due"] <= now + dt.timedelta(hours=6):
            p = bank.by_id[pid]
            overdue = (now - st["due"]).total_seconds() / 86400.0
            when = "due today" if overdue < 1 else f"{int(overdue)}d overdue"
            reviews.append((overdue, item(
                "review", p,
                f"Review ({when}). Last score {st['lastScore']:.2f}; "
                f"re-solve cleanly within the limit to push it out "
                f"{st['interval'] * REVIEW_GROWTH:.0f} days.",
                lapses=st["lapses"])))
    reviews.sort(key=lambda x: -x[0])
    review_items = [r for _, r in reviews]

    # 2. Focus problems from the neediest groups
    needs = group_needs(bank, state, now)
    focus_groups = [n for n in needs if n["importance"] >= 0.5][:n_focus]
    rng = _rng(now, salt)
    chosen: set[int] = set()
    focus_items = []
    for ng in focus_groups:
        grp = ng["group"]
        skill = ng["r"]
        desired = skill + 400.0 * math.log10(1.0 / STRETCH_EXPECTATION - 1.0)
        best: tuple[float, Problem] | None = None
        for p in bank.problems:
            w = p.group_weights.get(grp, 0.0)
            if w < 0.7 or p.id in chosen or not _eligible(p, settings, last_seen, now):
                continue
            if p.difficulty == "Hard" and skill < bank.typical_rating["Hard"] - 200:
                continue
            if p.difficulty == "Easy" and skill > bank.typical_rating["Medium"]:
                continue
            if abs(p.rating - desired) > 450:
                continue
            score = (-((p.rating - desired) / 150.0) ** 2
                     + 0.9 * ("neetcode150" in p.lists)
                     + 0.3 * ("blind75" in p.lists)
                     + 0.4 * _popularity(p)
                     + 0.6 * w
                     + 0.3 * (p.difficulty == "Medium")
                     + rng.random() * 0.35)
            if best is None or score > best[0]:
                best = (score, p)
        if best:
            p = best[1]
            chosen.add(p.id)
            why = (f"{grp} is a priority: rated {skill:.0f} ±{ng['rd']:.0f}"
                   + (f", {ng['gap']} below target" if ng["gap"] > 0 else "")
                   + (" (still uncertain, needs data)" if ng["rd"] > 180 else "") + ".")
            focus_items.append(item("focus", p, why, group=grp))

    # 3. Mock assessment: blind, typical-difficulty Medium
    mock = None
    typical = bank.typical_rating["Medium"]
    rng = _rng(now, salt + "|mock")
    pool = [p for p in bank.problems
            if p.difficulty == "Medium" and p.id not in chosen
            and _eligible(p, settings, last_seen, now)
            and abs(p.rating - typical) <= 125 and (p.likes or 0) >= 1500
            and any(GROUP_IMPORTANCE.get(gname, 0) >= 0.85 and w >= 0.8
                    for gname, w in p.group_weights.items())]
    if pool:
        p = rng.choice(pool)
        mock = item("mock", p,
                    f"Assessment simulation: a typical-difficulty Medium "
                    f"(~{typical:.0f}) with topic tags hidden. "
                    f"Identify the pattern yourself, like on test day.",
                    blind=True)

    return {
        "review": review_items,
        "focus": focus_items,
        "mock": mock,
        "needs": needs,
        "attemptsToday": attempts_today,
    }
