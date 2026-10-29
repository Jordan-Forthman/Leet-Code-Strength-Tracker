"""Plain-JSON persistence for your log and settings.

Files live in data/user/ (override with LCT_DATA_DIR). They're human-readable
and diff-friendly, so you can commit them to keep a history of your progress.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import secrets
import threading

from .model import DEFAULT_SETTINGS, OUTCOMES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_dir() -> str:
    return os.environ.get("LCT_DATA_DIR") or os.path.join(ROOT, "data", "user")


class Store:
    def __init__(self, directory: str | None = None):
        self.dir = directory or _default_dir()
        os.makedirs(self.dir, exist_ok=True)
        self.attempts_path = os.path.join(self.dir, "attempts.json")
        self.settings_path = os.path.join(self.dir, "settings.json")
        self._lock = threading.Lock()

    # -- low level ---------------------------------------------------------
    def _read(self, path: str, default):
        if not os.path.exists(path):
            return copy.deepcopy(default)
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, path: str, data) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)

    # -- settings ----------------------------------------------------------
    def settings(self) -> dict:
        s = copy.deepcopy(DEFAULT_SETTINGS)
        stored = self._read(self.settings_path, {})
        for k, v in stored.items():
            if k == "timeLimits" and isinstance(v, dict):
                s["timeLimits"].update(v)
            else:
                s[k] = v
        return s

    def save_settings(self, patch: dict) -> dict:
        with self._lock:
            s = self.settings()
            if "timeLimits" in patch:
                for d, v in patch["timeLimits"].items():
                    if d in s["timeLimits"]:
                        s["timeLimits"][d] = max(1, int(v))
            for key, cast in (("includePremium", bool), ("startRating", int),
                              ("dailyGoal", int)):
                if key in patch:
                    s[key] = cast(patch[key])
            self._write(self.settings_path, s)
            return s

    # -- attempts ----------------------------------------------------------
    def attempts(self) -> list[dict]:
        return self._read(self.attempts_path, [])

    @staticmethod
    def validate(a: dict) -> dict:
        out = {
            "problemId": int(a["problemId"]),
            "outcome": str(a["outcome"]),
            "minutes": round(float(a["minutes"]), 2),
            "wrong": int(a.get("wrong") or 0),
            "notes": str(a.get("notes") or "")[:2000],
        }
        if out["outcome"] not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        if not 0 <= out["minutes"] <= 24 * 60:
            raise ValueError("minutes out of range")
        if not 0 <= out["wrong"] <= 100:
            raise ValueError("wrong submissions out of range")
        if a.get("limit") not in (None, ""):
            out["limit"] = max(1.0, float(a["limit"]))
        ts = a.get("ts")
        if ts:
            t = dt.datetime.fromisoformat(str(ts))
            if t.tzinfo is None:
                t = t.astimezone()
            out["ts"] = t.isoformat(timespec="seconds")
        else:
            out["ts"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        if a.get("source") in ("suggested", "review", "mock", "self"):
            out["source"] = a["source"]
        return out

    def add_attempt(self, a: dict) -> dict:
        rec = self.validate(a)
        with self._lock:
            items = self.attempts()
            rec = {"id": f"a{secrets.token_hex(5)}", **rec}
            items.append(rec)
            self._write(self.attempts_path, items)
        return rec

    def update_attempt(self, attempt_id: str, a: dict) -> dict:
        with self._lock:
            items = self.attempts()
            for i, old in enumerate(items):
                if old["id"] == attempt_id:
                    merged = {**old, **a}
                    rec = {"id": attempt_id, **self.validate(merged)}
                    items[i] = rec
                    self._write(self.attempts_path, items)
                    return rec
        raise KeyError(attempt_id)

    def delete_attempt(self, attempt_id: str) -> None:
        with self._lock:
            items = self.attempts()
            kept = [x for x in items if x["id"] != attempt_id]
            if len(kept) == len(items):
                raise KeyError(attempt_id)
            self._write(self.attempts_path, kept)

    def replace_all(self, attempts: list[dict], settings: dict | None = None) -> int:
        recs = []
        for a in attempts:
            rec = self.validate(a)
            recs.append({"id": str(a.get("id") or f"a{secrets.token_hex(5)}"), **rec})
        with self._lock:
            self._write(self.attempts_path, recs)
        if settings:
            self.save_settings(settings)
        return len(recs)
