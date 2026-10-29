"""Builds the dashboard payload from the replayed model state."""

from __future__ import annotations

import datetime as dt

from .bank import Bank
from .model import (OUTCOME_LABELS, ModelState, readiness, replay, target_rating,
                    tier)
from .recommend import CLEAN_SCORE, review_states, suggest
from .topics import GROUP_IMPORTANCE, group_for_tag


def _day(ts: str) -> dt.date:
    t = dt.datetime.fromisoformat(ts)
    if t.tzinfo is None:
        t = t.astimezone()
    return t.astimezone().date()


def attempt_rows(state: ModelState) -> list[dict]:
    rows = []
    for sa in state.scored:
        a = sa.attempt
        rows.append({
            **a,
            "problem": {"id": sa.problem.id, "title": sa.problem.title,
                        "slug": sa.problem.slug, "difficulty": sa.problem.difficulty,
                        "rating": round(sa.problem.rating), "url": sa.problem.url},
            "limit": a.get("limit") or sa.problem_limit,
            "outcomeLabel": OUTCOME_LABELS[a["outcome"]],
            "score": sa.score,
            "expected": round(sa.expected, 3),
            "repeat": sa.repeat,
            "overallDelta": round(sa.overall_delta, 1),
            "overallAfter": round(sa.overall_after, 1),
            "overallRdAfter": round(sa.overall_rd_after, 1),
            "groupDeltas": {k: round(v, 1) for k, v in sa.group_deltas.items()},
        })
    rows.reverse()
    return rows


def dashboard(bank: Bank, attempts: list[dict], settings: dict,
              now: dt.datetime | None = None, shuffle: int = 0) -> dict:
    now = now or dt.datetime.now().astimezone()
    state = replay(bank, attempts, settings)
    overall = state.overall.snapshot(now)
    target = target_rating(bank)

    # Groups: every group in the bank, practised or not
    groups = []
    for grp in bank.groups():
        rating = state.groups.get(grp)
        if rating is None:
            groups.append({"group": grp, "r": overall["r"], "rd": 250.0, "attempts": 0,
                           "evidence": 0, "importance": GROUP_IMPORTANCE.get(grp, 0.2),
                           "rated": False, "readiness": readiness(overall["r"], bank),
                           "tags": []})
            continue
        snap = rating.snapshot(now)
        tags = []
        for t, tr in state.tags.items():
            if group_for_tag(t) == grp:
                ts = tr.snapshot(now)
                tags.append({"tag": t, **ts})
        tags.sort(key=lambda x: -x["evidence"])
        groups.append({"group": grp, **snap, "importance": GROUP_IMPORTANCE.get(grp, 0.2),
                       "rated": True, "readiness": readiness(snap["r"], bank),
                       "tags": tags})

    # History series (one point per attempt)
    history = [{"ts": sa.attempt["ts"], "r": round(sa.overall_after, 1),
                "rd": round(sa.overall_rd_after, 1), "score": sa.score,
                "difficulty": sa.problem.difficulty, "title": sa.problem.title,
                "problemId": sa.problem.id, "outcome": sa.attempt["outcome"]}
               for sa in state.scored]

    # Per-difficulty stats
    by_diff = {}
    for d in ("Easy", "Medium", "Hard"):
        xs = [sa for sa in state.scored if sa.problem.difficulty == d]
        clean = [sa for sa in xs if sa.score >= CLEAN_SCORE]
        solved = [sa for sa in xs if sa.attempt["outcome"] == "solved"]
        by_diff[d] = {
            "attempts": len(xs),
            "clean": len(clean),
            "cleanRate": round(len(clean) / len(xs), 3) if xs else None,
            "avgMinutes": round(sum(sa.attempt["minutes"] for sa in solved) / len(solved), 1)
            if solved else None,
            "limit": settings["timeLimits"][d],
            "typicalRating": round(bank.typical_rating[d]),
        }

    # Activity calendar + streak
    counts: dict[str, int] = {}
    for a in attempts:
        k = _day(a["ts"]).isoformat()
        counts[k] = counts.get(k, 0) + 1
    streak = 0
    day = now.date()
    if day.isoformat() not in counts:
        day -= dt.timedelta(days=1)
    while day.isoformat() in counts:
        streak += 1
        day -= dt.timedelta(days=1)

    week_ago = now - dt.timedelta(days=7)
    prior = [h for h in history if dt.datetime.fromisoformat(h["ts"]).astimezone() < week_ago]
    week_change = round(overall["r"] - (prior[-1]["r"] if prior else
                                        float(settings.get("startRating", 1400))), 1) \
        if history else 0.0

    rated_groups = [x for x in groups if x["rated"] and x["evidence"] >= 1.0
                    and x["importance"] >= 0.5]
    rated_groups.sort(key=lambda x: x["r"])

    reviews = review_states(state)
    review_pending = sum(1 for st in reviews.values() if st["active"])

    return {
        "now": now.isoformat(timespec="seconds"),
        "settings": settings,
        "overall": {**overall, "tier": tier(overall["r"], bank),
                    "readiness": readiness(overall["r"], bank),
                    "target": round(target), "weekChange": week_change,
                    "start": float(settings.get("startRating", 1400))},
        "groups": groups,
        "weakest": [x["group"] for x in rated_groups[:3]],
        "strongest": [x["group"] for x in reversed(rated_groups[-3:])],
        "history": history,
        "byDifficulty": by_diff,
        "totals": {
            "attempts": len(state.scored),
            "unique": len({sa.problem.id for sa in state.scored}),
            "clean": sum(1 for sa in state.scored if sa.score >= CLEAN_SCORE),
            "reviewPending": review_pending,
            "streak": streak,
            "today": counts.get(now.date().isoformat(), 0),
        },
        "calendar": counts,
        "suggestions": suggest(bank, state, settings, now, shuffle=shuffle),
        "recent": attempt_rows(state)[:15],
        "bankInfo": {"count": len(bank.problems), "generated": bank.meta.get("generated"),
                     "source": bank.meta.get("source"),
                     "typical": {k: round(v) for k, v in bank.typical_rating.items()}},
    }
