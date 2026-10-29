"""The strength model.

Overview
--------
Every logged attempt is treated as a *match* between you and the problem, in
the style of the Glicko rating system (Elo + uncertainty):

* Each problem has a fixed difficulty rating (contest-derived where available,
  otherwise estimated) with its own uncertainty.
* You have a rating + rating deviation (RD) at three levels: overall, per topic
  group (e.g. "Graphs"), and per raw LeetCode tag (e.g. "Topological Sort").
* An attempt produces a *performance score* in [0, 1] from the outcome and the
  time taken relative to the time limit (see ``performance_score``).
* The model predicts an *expected score* from the rating gap. Every rating the
  problem touches moves by (actual - expected), scaled by how uncertain that
  rating is and by how strongly the problem belongs to that topic.

So a fast solve of a problem rated well above you moves you up a lot; failing
a problem rated well below you moves you down a lot; doing exactly as expected
barely moves anything. Ratings you haven't exercised in a while become less
certain (RD grows), so the next result there counts for more.

The full attempt log is replayed from scratch on every request: the log is the
single source of truth, and editing/deleting an attempt or changing settings is
always consistent.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from .bank import Bank, Problem

OUTCOMES = ("solved", "hint", "solution", "failed")
OUTCOME_LABELS = {
    "solved": "Solved on my own",
    "hint": "Solved with a hint",
    "solution": "Needed the solution",
    "failed": "Could not solve",
}

# --- Glicko parameters -----------------------------------------------------
Q = math.log(10) / 400
RD_MAX = 350.0
RD_MIN = 70.0               # floor keeps ratings responsive while you're improving
RD_DAILY_GROWTH = 10.0      # RD grows by sqrt(days) * this while a rating is idle
START_RD = 250.0            # overall rating uncertainty with no data
TOPIC_PRIOR_RD = 250.0      # how far a topic may plausibly sit from your overall rating
REPEAT_WEIGHT = 0.6         # re-solving a seen problem is weaker evidence (memory)
READY_EXPECTATION = 0.70    # "assessment-ready" = expected score >= this on a typical Medium

DEFAULT_SETTINGS = {
    "timeLimits": {"Easy": 15, "Medium": 35, "Hard": 60},
    "includePremium": False,
    "startRating": 1400,
    "dailyGoal": 3,
}


def performance_score(outcome: str, minutes: float, limit: float, wrong: int = 0) -> float:
    """Convert an attempt into a score in [0, 1].

    solved within limit   1.00 (at <=50% of the limit) sliding to 0.80 (at the limit)
    solved over limit     0.60 just over the limit, sliding to 0.30 at 2x the limit
                          (the drop at the limit is deliberate: a timed assessment
                          gives no credit for a solution that lands after time is up)
    solved with a hint    0.45 within limit, 0.30 over
    needed the solution   0.10
    could not solve       0.00
    Each wrong submission costs 0.04 (max 5 counted) on solved/hint outcomes.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    limit = max(float(limit), 1.0)
    ratio = max(float(minutes), 0.0) / limit
    if outcome == "solved":
        if ratio <= 0.5:
            s = 1.0
        elif ratio <= 1.0:
            s = 1.0 - 0.2 * (ratio - 0.5) / 0.5
        else:
            s = max(0.3, 0.6 - 0.3 * (ratio - 1.0))
    elif outcome == "hint":
        s = 0.45 if ratio <= 1.0 else 0.3
    elif outcome == "solution":
        s = 0.1
    else:
        s = 0.0
    if outcome in ("solved", "hint"):
        s -= 0.04 * min(max(int(wrong or 0), 0), 5)
    return round(min(max(s, 0.0), 1.0), 4)


def g(rd: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * Q * Q * rd * rd / (math.pi ** 2))


def expected_score(r: float, opp_r: float, opp_rd: float = 0.0) -> float:
    return 1.0 / (1.0 + 10 ** (-g(opp_rd) * (r - opp_r) / 400.0))


def parse_ts(ts: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(ts)
    if t.tzinfo is None:
        t = t.astimezone()
    return t


@dataclass
class Rating:
    r: float
    rd: float
    last: dt.datetime | None = None
    attempts: int = 0
    evidence: float = 0.0  # sum of weights of attempts that touched this rating

    def inflate(self, now: dt.datetime) -> None:
        """Grow uncertainty for the time since this rating was last exercised."""
        if self.last is None:
            return
        days = max((now - self.last).total_seconds() / 86400.0, 0.0)
        self.rd = min(RD_MAX, math.sqrt(self.rd ** 2 + RD_DAILY_GROWTH ** 2 * days))
        self.last = now

    def update(self, opp_r: float, opp_rd: float, score: float, weight: float,
               now: dt.datetime) -> float:
        """Weighted Glicko-1 update against a single opponent. Returns the delta."""
        self.inflate(now)
        gj = g(opp_rd)
        e = expected_score(self.r, opp_r, opp_rd)
        d2_inv = Q * Q * gj * gj * e * (1 - e) * weight
        denom = 1.0 / (self.rd ** 2) + d2_inv
        delta = (Q / denom) * gj * (score - e) * weight
        self.r += delta
        self.rd = max(RD_MIN, math.sqrt(1.0 / denom))
        self.last = now
        self.attempts += 1
        self.evidence += weight
        return delta

    def snapshot(self, now: dt.datetime | None = None) -> dict:
        rd = self.rd
        if now is not None and self.last is not None:
            days = max((now - self.last).total_seconds() / 86400.0, 0.0)
            rd = min(RD_MAX, math.sqrt(rd ** 2 + RD_DAILY_GROWTH ** 2 * days))
        return {"r": round(self.r, 1), "rd": round(rd, 1), "attempts": self.attempts,
                "evidence": round(self.evidence, 2),
                "last": self.last.isoformat(timespec="seconds") if self.last else None}


@dataclass
class ScoredAttempt:
    attempt: dict
    problem: Problem
    score: float
    expected: float
    weight: float
    repeat: bool
    overall_delta: float
    group_deltas: dict[str, float]
    tag_deltas: dict[str, float]
    overall_after: float
    overall_rd_after: float
    problem_limit: float


@dataclass
class ModelState:
    overall: Rating
    groups: dict[str, Rating] = field(default_factory=dict)
    tags: dict[str, Rating] = field(default_factory=dict)
    scored: list[ScoredAttempt] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # attempts on unknown problems


def time_limit_for(problem: Problem, settings: dict) -> float:
    limits = settings.get("timeLimits", DEFAULT_SETTINGS["timeLimits"])
    return float(limits.get(problem.difficulty, 35))


def replay(bank: Bank, attempts: list[dict], settings: dict) -> ModelState:
    """Rebuild every rating from the attempt log, oldest first."""
    state = ModelState(overall=Rating(float(settings.get("startRating", 1400)), START_RD))
    seen: set[int] = set()
    for a in sorted(attempts, key=lambda a: (a["ts"], a["id"])):
        p = bank.by_id.get(int(a["problemId"]))
        if p is None:
            state.skipped.append(a)
            continue
        now = parse_ts(a["ts"])
        limit = float(a.get("limit") or time_limit_for(p, settings))
        score = performance_score(a["outcome"], a.get("minutes", 0), limit,
                                  a.get("wrong", 0))
        repeat = p.id in seen
        seen.add(p.id)
        weight = REPEAT_WEIGHT if repeat else 1.0

        # New topics start at your current overall rating with a wide prior.
        for grp in p.group_weights:
            if grp not in state.groups:
                state.groups[grp] = Rating(state.overall.r, TOPIC_PRIOR_RD, now)
        for t in p.tag_weights:
            if t not in state.tags:
                state.tags[t] = Rating(state.overall.r, TOPIC_PRIOR_RD, now)

        expected = expected_score(state.overall.r, p.rating, p.rating_rd)
        od = state.overall.update(p.rating, p.rating_rd, score, weight, now)
        gd = {grp: state.groups[grp].update(p.rating, p.rating_rd, score, weight * w, now)
              for grp, w in p.group_weights.items()}
        td = {t: state.tags[t].update(p.rating, p.rating_rd, score, weight * w, now)
              for t, w in p.tag_weights.items()}
        state.scored.append(ScoredAttempt(
            attempt=a, problem=p, score=score, expected=expected, weight=weight,
            repeat=repeat, overall_delta=od, group_deltas=gd, tag_deltas=td,
            overall_after=state.overall.r, overall_rd_after=state.overall.rd,
            problem_limit=limit,
        ))
    return state


def readiness(r: float, bank: Bank) -> dict[str, float]:
    """Expected performance score on a typical interview problem of each difficulty."""
    return {d: round(expected_score(r, bank.typical_rating[d], 100.0), 3)
            for d in ("Easy", "Medium", "Hard")}


def target_rating(bank: Bank) -> float:
    """Rating at which a typical Medium is expected to score READY_EXPECTATION."""
    gap = 400.0 * math.log10(READY_EXPECTATION / (1 - READY_EXPECTATION)) / g(100.0)
    return bank.typical_rating["Medium"] + gap


def tier(r: float, bank: Bank) -> str:
    rd = readiness(r, bank)
    if rd["Hard"] >= 0.5:
        return "Strong"
    if rd["Medium"] >= READY_EXPECTATION:
        return "Assessment-ready"
    if rd["Medium"] >= 0.5:
        return "Competitive"
    if rd["Medium"] >= 0.3:
        return "Developing"
    return "Foundations"
