import datetime as dt
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from tracker.analytics import dashboard
from tracker.bank import Bank
from tracker.model import (DEFAULT_SETTINGS, RD_MIN, Rating, expected_score,
                           performance_score, replay, target_rating)
from tracker.recommend import review_states, suggest
from tracker.server import App, make_handler
from tracker.storage import Store

BANK = Bank.load()
NOW = dt.datetime(2026, 10, 29, 20, 0, tzinfo=dt.timezone.utc)


def attempt(pid, outcome, minutes, days_ago=0.0, i=0, **kw):
    ts = (NOW - dt.timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {"id": f"t{i}", "ts": ts, "problemId": pid, "outcome": outcome,
            "minutes": minutes, **kw}


class ScoreTests(unittest.TestCase):
    def test_score_table(self):
        self.assertEqual(performance_score("solved", 10, 35), 1.0)
        self.assertAlmostEqual(performance_score("solved", 35, 35), 0.8)
        self.assertAlmostEqual(performance_score("solved", 36, 35), 0.6 - 0.3 / 35, places=3)
        self.assertAlmostEqual(performance_score("solved", 70, 35), 0.3)
        self.assertAlmostEqual(performance_score("solved", 500, 35), 0.3)
        self.assertEqual(performance_score("hint", 20, 35), 0.45)
        self.assertEqual(performance_score("hint", 50, 35), 0.3)
        self.assertEqual(performance_score("solution", 35, 35), 0.1)
        self.assertEqual(performance_score("failed", 35, 35), 0.0)

    def test_faster_is_never_worse(self):
        scores = [performance_score("solved", m, 35) for m in range(0, 90)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_wrong_submission_penalty(self):
        self.assertAlmostEqual(performance_score("solved", 10, 35, wrong=2), 0.92)
        self.assertAlmostEqual(performance_score("solved", 10, 35, wrong=50), 0.8)
        self.assertEqual(performance_score("failed", 10, 35, wrong=3), 0.0)

    def test_bad_outcome(self):
        with self.assertRaises(ValueError):
            performance_score("crushed", 10, 35)


class GlickoTests(unittest.TestCase):
    def test_expected_symmetry(self):
        self.assertAlmostEqual(expected_score(1500, 1500), 0.5)
        self.assertAlmostEqual(expected_score(1600, 1500) + expected_score(1500, 1600), 1.0)

    def test_update_direction_and_rd(self):
        r = Rating(1500, 250, NOW)
        d = r.update(1700, 75, 1.0, 1.0, NOW)
        self.assertGreater(d, 0)
        self.assertLess(r.rd, 250)
        r2 = Rating(1500, 250, NOW)
        self.assertLess(r2.update(1300, 75, 0.0, 1.0, NOW), 0)

    def test_upset_moves_more(self):
        a, b = Rating(1500, 150, NOW), Rating(1500, 150, NOW)
        da = a.update(1800, 75, 1.0, 1.0, NOW)   # beat a much harder problem
        db = b.update(1300, 75, 1.0, 1.0, NOW)   # beat a much easier problem
        self.assertGreater(da, db)

    def test_weight_scales_update(self):
        a, b = Rating(1500, 200, NOW), Rating(1500, 200, NOW)
        self.assertGreater(a.update(1600, 75, 1.0, 1.0, NOW), b.update(1600, 75, 1.0, 0.3, NOW))

    def test_rd_floor_and_inflation(self):
        r = Rating(1500, 250, NOW)
        for _ in range(200):
            r.update(1500, 75, 0.5, 1.0, NOW)
        self.assertEqual(r.rd, RD_MIN)
        r.inflate(NOW + dt.timedelta(days=100))
        self.assertGreater(r.rd, RD_MIN + 20)


class ReplayTests(unittest.TestCase):
    def test_topics_follow_results(self):
        graphs = [p.id for p in BANK.problems
                  if p.group_weights.get("Graphs") == 1.0 and p.difficulty == "Medium"][:6]
        dp = [p.id for p in BANK.problems
              if p.group_weights.get("Dynamic Programming") == 1.0
              and "Graphs" not in p.group_weights and p.difficulty == "Medium"][:6]
        log = []
        for i, pid in enumerate(graphs):
            log.append(attempt(pid, "solved", 12, days_ago=10 - i, i=i))
        for i, pid in enumerate(dp):
            log.append(attempt(pid, "failed", 35, days_ago=10 - i, i=100 + i))
        st = replay(BANK, log, DEFAULT_SETTINGS)
        self.assertGreater(st.groups["Graphs"].r, st.groups["Dynamic Programming"].r + 150)
        self.assertEqual(len(st.scored), 12)

    def test_order_independent_of_input_order(self):
        log = [attempt(1, "solved", 5, 3, 1), attempt(15, "failed", 35, 2, 2),
               attempt(200, "hint", 30, 1, 3)]
        a = replay(BANK, log, DEFAULT_SETTINGS).overall.r
        b = replay(BANK, list(reversed(log)), DEFAULT_SETTINGS).overall.r
        self.assertAlmostEqual(a, b)

    def test_repeat_weight(self):
        log = [attempt(15, "failed", 35, 5, 1), attempt(15, "solved", 10, 1, 2)]
        st = replay(BANK, log, DEFAULT_SETTINGS)
        self.assertFalse(st.scored[0].repeat)
        self.assertTrue(st.scored[1].repeat)
        self.assertLess(st.scored[1].weight, 1.0)

    def test_unknown_problem_skipped(self):
        st = replay(BANK, [attempt(999999, "solved", 5)], DEFAULT_SETTINGS)
        self.assertEqual(len(st.scored), 0)
        self.assertEqual(len(st.skipped), 1)

    def test_target_above_typical_medium(self):
        self.assertGreater(target_rating(BANK), BANK.typical_rating["Medium"])


class RecommendTests(unittest.TestCase):
    def test_review_schedule(self):
        log = [attempt(15, "failed", 35, days_ago=3, i=1)]
        st = replay(BANK, log, DEFAULT_SETTINGS)
        rs = review_states(st)
        self.assertTrue(rs[15]["active"])
        s = suggest(BANK, st, DEFAULT_SETTINGS, NOW)
        self.assertIn(15, [r["problem"]["id"] for r in s["review"]])
        # clean re-solve pushes it out
        log.append(attempt(15, "solved", 10, days_ago=0.5, i=2))
        st = replay(BANK, log, DEFAULT_SETTINGS)
        s = suggest(BANK, st, DEFAULT_SETTINGS, NOW)
        self.assertNotIn(15, [r["problem"]["id"] for r in s["review"]])

    def test_focus_excludes_seen_and_premium(self):
        log = [attempt(pid, "solved", 10, days_ago=1, i=i)
               for i, pid in enumerate([1, 15, 20, 121, 200, 206])]
        st = replay(BANK, log, DEFAULT_SETTINGS)
        s = suggest(BANK, st, DEFAULT_SETTINGS, NOW)
        ids = [f["problem"]["id"] for f in s["focus"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(ids)
        for f in s["focus"] + ([s["mock"]] if s["mock"] else []):
            self.assertNotIn(f["problem"]["id"], {1, 15, 20, 121, 200, 206})
            self.assertFalse(f["problem"]["paid"])

    def test_dashboard_empty(self):
        d = dashboard(BANK, [], DEFAULT_SETTINGS, NOW)
        self.assertEqual(d["totals"]["attempts"], 0)
        self.assertTrue(d["suggestions"]["focus"])


class StoreAndServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.store.add_attempt({"problemId": 1, "outcome": "nope", "minutes": 3})
        with self.assertRaises(ValueError):
            self.store.add_attempt({"problemId": 1, "outcome": "solved", "minutes": -1})
        rec = self.store.add_attempt({"problemId": 1, "outcome": "solved", "minutes": 3})
        self.assertIn("ts", rec)
        self.store.update_attempt(rec["id"], {"minutes": 9})
        self.assertEqual(self.store.attempts()[0]["minutes"], 9)
        self.store.delete_attempt(rec["id"])
        self.assertEqual(self.store.attempts(), [])

    def test_settings_merge(self):
        s = self.store.save_settings({"timeLimits": {"Medium": 25}, "includePremium": True})
        self.assertEqual(s["timeLimits"], {"Easy": 15, "Medium": 25, "Hard": 60})
        self.assertTrue(self.store.settings()["includePremium"])

    def test_http_api(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(BANK, self.store)))
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{port}"

        def call(path, method="GET", body=None):
            req = urllib.request.Request(base + path, method=method,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        try:
            res = call("/api/attempts", "POST", {"problemId": 200, "outcome": "solved", "minutes": 14})
            self.assertGreater(res["feedback"]["overallDelta"], 0)
            d = call("/api/dashboard")
            self.assertEqual(d["totals"]["attempts"], 1)
            self.assertIn("Graphs", res["feedback"]["groupDeltas"])
            p = call("/api/problems/200")
            self.assertEqual(len(p["attempts"]), 1)
            probs = call("/api/problems")
            self.assertEqual(len(probs["problems"]), len(BANK.problems))
            with urllib.request.urlopen(base + "/") as r:
                self.assertIn(b"LeetCode Strength Tracker", r.read())
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/../tracker/model.py")
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
