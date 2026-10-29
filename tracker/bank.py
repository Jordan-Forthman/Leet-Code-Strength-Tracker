"""Problem bank: loads data/problems.json and derives per-problem metadata the
rating model needs (topic weights, groups, curated-list membership)."""

from __future__ import annotations

import json
import math
import os
import statistics
from dataclasses import dataclass, field

from .curated import LISTS
from .topics import GROUP_ORDER, group_for_tag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, "data", "problems.json")

# Uncertainty (Glicko RD) attached to a problem's difficulty rating.
CONTEST_RATING_RD = 75.0     # derived from thousands of real contest results
ESTIMATED_RATING_RD = 200.0  # regression on acceptance rate; noisy


@dataclass
class Problem:
    id: int
    title: str
    slug: str
    difficulty: str
    rating: float
    rating_source: str
    ac_rate: float | None
    paid: bool
    tags: list[str]
    likes: int | None = None
    lists: list[str] = field(default_factory=list)
    # tag -> weight in (0, 1]; the most specific tag of the problem gets 1.0
    tag_weights: dict[str, float] = field(default_factory=dict)
    # group -> weight in (0, 1]
    group_weights: dict[str, float] = field(default_factory=dict)

    @property
    def rating_rd(self) -> float:
        return CONTEST_RATING_RD if self.rating_source == "contest" else ESTIMATED_RATING_RD

    @property
    def url(self) -> str:
        return f"https://leetcode.com/problems/{self.slug}/"

    def to_json(self) -> dict:
        return {
            "id": self.id, "title": self.title, "slug": self.slug,
            "difficulty": self.difficulty, "rating": round(self.rating),
            "ratingSource": self.rating_source, "acRate": self.ac_rate,
            "paid": self.paid, "tags": self.tags, "likes": self.likes,
            "lists": self.lists, "groups": sorted(self.group_weights,
                                                  key=lambda g: -self.group_weights[g]),
            "url": self.url,
        }


class Bank:
    def __init__(self, problems: list[Problem], meta: dict | None = None):
        self.meta = meta or {}
        self.problems = problems
        self.by_id = {p.id: p for p in problems}
        self.by_slug = {p.slug: p for p in problems}
        self._compute_weights()
        self._apply_lists()
        self.typical_rating = self._typical_ratings()

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "Bank":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        problems = [
            Problem(
                id=int(p["id"]), title=p["title"], slug=p["slug"],
                difficulty=p["difficulty"], rating=float(p["rating"]),
                rating_source=p.get("ratingSource", "estimated"),
                ac_rate=p.get("acRate"), paid=bool(p.get("paid")),
                tags=list(p.get("tags") or []), likes=p.get("likes"),
            )
            for p in raw["problems"]
        ]
        meta = {k: v for k, v in raw.items() if k != "problems"}
        return cls(problems, meta)

    def _compute_weights(self) -> None:
        """Inverse-document-frequency tag weighting.

        "Array" appears on ~60% of problems and says little about what a problem
        tests; "Topological Sort" appears on ~1% and says a lot. A tag's weight
        on a problem is idf(tag) / max idf among that problem's tags, so the most
        specific tag gets full credit and generic tags get partial credit.
        """
        n = len(self.problems)
        tag_counts: dict[str, int] = {}
        group_counts: dict[str, int] = {}
        problem_groups: dict[int, set[str]] = {}
        for p in self.problems:
            for t in p.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
            gs = {group_for_tag(t) for t in p.tags}
            problem_groups[p.id] = gs
            for g in gs:
                group_counts[g] = group_counts.get(g, 0) + 1
        self.tag_counts = tag_counts

        def idf(c: int) -> float:
            return math.log((n + 1) / (c + 1)) + 0.1

        tag_idf = {t: idf(c) for t, c in tag_counts.items()}
        group_idf = {g: idf(c) for g, c in group_counts.items()}
        for p in self.problems:
            if not p.tags:
                continue
            top = max(tag_idf[t] for t in p.tags)
            p.tag_weights = {t: round(tag_idf[t] / top, 4) for t in p.tags}
            gs = problem_groups[p.id]
            gtop = max(group_idf[g] for g in gs)
            p.group_weights = {g: round(group_idf[g] / gtop, 4) for g in gs}

    def _apply_lists(self) -> None:
        for name, slugs in LISTS.items():
            for s in slugs:
                p = self.by_slug.get(s)
                if p and name not in p.lists:
                    p.lists.append(name)

    def _typical_ratings(self) -> dict[str, float]:
        """Median rating of interview-style problems at each difficulty.

        Uses the NeetCode 150 set (what assessments resemble) when available,
        otherwise the whole bank.
        """
        out = {}
        for diff in ("Easy", "Medium", "Hard"):
            curated = [p.rating for p in self.problems
                       if p.difficulty == diff and "neetcode150" in p.lists]
            pool = curated if len(curated) >= 5 else [
                p.rating for p in self.problems if p.difficulty == diff]
            out[diff] = statistics.median(pool) if pool else 1500.0
        return out

    def groups(self) -> list[str]:
        present = {g for p in self.problems for g in p.group_weights}
        return [g for g in GROUP_ORDER if g in present]
