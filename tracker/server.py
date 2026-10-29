"""Tiny stdlib HTTP server: JSON API + the static dashboard in web/."""

from __future__ import annotations

import datetime as dt
import json
import mimetypes
import os
import re
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .analytics import attempt_rows, dashboard
from .bank import Bank
from .model import OUTCOME_LABELS, replay, time_limit_for
from .recommend import expected_for, review_states
from .storage import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")


class App:
    def __init__(self, bank: Bank, store: Store):
        self.bank = bank
        self.store = store

    def now(self) -> dt.datetime:
        return dt.datetime.now().astimezone()

    def problems(self) -> dict:
        settings = self.store.settings()
        state = replay(self.bank, self.store.attempts(), settings)
        now = self.now()
        status: dict[int, dict] = {}
        for sa in state.scored:
            s = status.setdefault(sa.problem.id, {"n": 0, "best": 0.0, "last": None})
            s["n"] += 1
            s["best"] = max(s["best"], sa.score)
            s["last"] = sa.attempt["ts"]
        for pid, st in review_states(state).items():
            if st["active"]:
                status[pid]["reviewDue"] = st["due"].isoformat(timespec="seconds")
        out = []
        for p in self.bank.problems:
            j = p.to_json()
            j["expected"] = round(expected_for(p, state, now), 3)
            j["timeLimit"] = time_limit_for(p, settings)
            if p.id in status:
                j["status"] = status[p.id]
            out.append(j)
        return {"problems": out, "groups": self.bank.groups(),
                "typical": {k: round(v) for k, v in self.bank.typical_rating.items()}}

    def problem(self, pid: int) -> dict:
        p = self.bank.by_id.get(pid)
        if p is None:
            raise KeyError(pid)
        settings = self.store.settings()
        state = replay(self.bank, self.store.attempts(), settings)
        rows = [r for r in attempt_rows(state) if r["problemId"] == pid]
        j = p.to_json()
        j["expected"] = round(expected_for(p, state, self.now()), 3)
        j["timeLimit"] = time_limit_for(p, settings)
        j["tagWeights"] = p.tag_weights
        j["groupWeights"] = p.group_weights
        return {"problem": j, "attempts": rows}

    def attempt_feedback(self, attempt_id: str) -> dict | None:
        state = replay(self.bank, self.store.attempts(), self.store.settings())
        for r in attempt_rows(state):
            if r["id"] == attempt_id:
                return r
        return None


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LeetCodeStrengthTracker/1.0"

        def log_message(self, fmt, *args):  # quieter console
            if os.environ.get("LCT_VERBOSE"):
                super().log_message(fmt, *args)

        # -- helpers -------------------------------------------------------
        def _json(self, data, status: int = 200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, msg: str):
            self._json({"error": msg}, status)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 10 * 1024 * 1024:
                raise ValueError("request too large")
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw or b"{}")

        def _static(self, path: str):
            if path in ("", "/"):
                path = "/index.html"
            full = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
            if not full.startswith(WEB + os.sep) or not os.path.isfile(full):
                return self._error(404, "not found")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method: str):
            url = urlparse(self.path)
            path = url.path
            qs = parse_qs(url.query)
            try:
                if not path.startswith("/api/"):
                    if method != "GET":
                        return self._error(405, "method not allowed")
                    return self._static(path)

                if path == "/api/dashboard" and method == "GET":
                    shuffle = int((qs.get("shuffle") or ["0"])[0])
                    return self._json(dashboard(app.bank, app.store.attempts(),
                                                app.store.settings(), shuffle=shuffle))
                if path == "/api/problems" and method == "GET":
                    return self._json(app.problems())
                m = re.fullmatch(r"/api/problems/(\d+)", path)
                if m and method == "GET":
                    return self._json(app.problem(int(m.group(1))))
                if path == "/api/attempts" and method == "GET":
                    state = replay(app.bank, app.store.attempts(), app.store.settings())
                    return self._json({"attempts": attempt_rows(state),
                                       "outcomes": OUTCOME_LABELS})
                if path == "/api/attempts" and method == "POST":
                    data = self._body()
                    if int(data.get("problemId", -1)) not in app.bank.by_id:
                        return self._error(400, "unknown problem id")
                    rec = app.store.add_attempt(data)
                    return self._json({"attempt": rec,
                                       "feedback": app.attempt_feedback(rec["id"])}, 201)
                m = re.fullmatch(r"/api/attempts/([\w-]+)", path)
                if m and method == "PUT":
                    rec = app.store.update_attempt(m.group(1), self._body())
                    return self._json({"attempt": rec,
                                       "feedback": app.attempt_feedback(rec["id"])})
                if m and method == "DELETE":
                    app.store.delete_attempt(m.group(1))
                    return self._json({"ok": True})
                if path == "/api/settings" and method == "GET":
                    return self._json(app.store.settings())
                if path == "/api/settings" and method == "PUT":
                    return self._json(app.store.save_settings(self._body()))
                if path == "/api/export" and method == "GET":
                    return self._json({"exported": app.now().isoformat(timespec="seconds"),
                                       "settings": app.store.settings(),
                                       "attempts": app.store.attempts()})
                if path == "/api/import" and method == "POST":
                    data = self._body()
                    n = app.store.replace_all(data.get("attempts") or [], data.get("settings"))
                    return self._json({"imported": n})
                return self._error(404, "no such endpoint")
            except KeyError as e:
                return self._error(404, f"not found: {e}")
            except (ValueError, TypeError) as e:
                return self._error(400, str(e))
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._error(500, f"{type(e).__name__}: {e}")

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          data_dir: str | None = None) -> None:
    bank = Bank.load()
    store = Store(data_dir)
    httpd = ThreadingHTTPServer((host, port), make_handler(App(bank, store)))
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}/"
    print(f"LeetCode Strength Tracker running at {url}")
    print(f"  problem bank: {len(bank.problems)} problems | your data: {store.dir}")
    print("  Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()
