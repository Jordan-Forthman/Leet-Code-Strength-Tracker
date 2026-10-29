# LeetCode Strength Tracker

A local web app that measures how well you solve LeetCode-style problems **under a clock**, per topic and difficulty. It updates after every attempt you log and tells you what to practise next.

Built for timed coding assessments (e.g. a 35-minute Medium): a correct solution that lands after time is up gets little credit, the same as on test day.

- **Problem bank**: all ~3,700 LeetCode algorithm problems (number, title, link, difficulty, tags, acceptance rate, premium flag), grouped into ~20 interview topics, with NeetCode 150 / Blind 75 flagged. Nothing is copied from problem statements; every problem links to leetcode.com.
- **Logging**: built-in timer, four honest outcomes (solved alone / with a hint / needed the solution / couldn't solve), time taken, wrong submissions, and notes.
- **Strength model**: a Glicko-style rating (Elo plus uncertainty) at three levels: overall, per topic group, and per LeetCode tag. Each attempt moves every topic the problem touches.
- **Daily plan**: spaced-repetition reviews of problems you missed, focus problems for your weakest high-value topics pitched at the right difficulty, and a "blind" mock assessment.

## Quick start

Requires Python 3.9+. No third-party packages.

```bash
python3 lct.py
```

This starts the server at <http://localhost:8765> and opens your browser. Stop it with `Ctrl+C`.

## Daily workflow

1. Open the **Dashboard**. *Today's plan* lists what to do: reviews that are due, 3 focus problems, and a mock assessment.
2. Click **Start ▸** on a suggestion, or pick any problem in **Practice** / **Problem bank**.
3. Click **Open on LeetCode & start timer**. Solve it on leetcode.com. The timer keeps running if you navigate away, and a chip in the corner shows it.
4. Come back, choose the outcome truthfully, and click **Log attempt**. You'll see your score vs. the model's expectation and how much each rating moved.

You can also stay in the terminal:

```bash
python3 lct.py suggest                      # today's plan
python3 lct.py log 200 solved 18            # problem #200, solved alone in 18 min
python3 lct.py log two-sum hint 12 --wrong 1
python3 lct.py log 322 failed 35 --notes "didn't see the DP"
python3 lct.py report                       # ratings by topic
```

Outcomes: `solved`, `hint`, `solution`, `failed`.

## How the rating works (short version)

| Outcome | Performance score |
|---|---|
| Solved alone, ≤ 50% of the limit | 1.00 |
| Solved alone, at the limit | 0.80 (linear in between) |
| Solved alone, over the limit | 0.60, falling to 0.30 at 2× the limit |
| Solved with a hint | 0.45 within limit / 0.30 over |
| Needed the solution | 0.10 |
| Could not solve | 0.00 |
| Each wrong submission | −0.04 (max 5) |

Default limits: Easy 15 min, Medium 35, Hard 60. You can change them in Settings.

- **Problem difficulty.** ~2,600 problems use [zerotrac's contest-derived ratings](https://github.com/zerotrac/leetcode_problem_rating). The rest are estimated from difficulty and acceptance rate, using a regression fitted on the rated ones; the UI marks these with `~`.
- **Expected vs. actual.** The model predicts your score from the rating gap. Each rating moves by `K × (actual − expected)`, where K grows with that rating's uncertainty. Upsets move you a lot; expected results barely move you.
- **Topics.** A problem's tags are weighted by specificity (inverse document frequency), so "Topological Sort" counts fully and "Array" only a little. Untouched topics start at your overall rating with wide uncertainty.
- **Rust.** Uncertainty grows while a topic sits idle, so the next result there counts for more. Re-solving a problem you've seen counts at 60% weight.
- **Readiness.** Your expected score on a *typical* interview problem: the median NeetCode 150 rating for that difficulty. **Assessment-ready** means ≥ 70% expected on a typical Medium.

The **How it works** page in the app has the full explanation.

## Your data

Your log is stored as plain JSON in `data/user/` (`attempts.json`, `settings.json`). The model is recomputed from that log on every request, so you can edit or delete any attempt and every rating stays consistent. Commit `data/user/` to keep a history of your progress, or add it to `.gitignore` if the repo is public. Settings also has Export/Import. Set `LCT_DATA_DIR` to keep data somewhere else.

## Refreshing the problem bank

```bash
python3 lct.py sync
```

This pulls the current problem list from LeetCode's GraphQL API. If that's unreachable, it falls back to a GitHub mirror. It then re-fetches zerotrac's contest ratings and refits the rating estimates. Add `--source mirror` to skip LeetCode.

## Development

```bash
python3 -m unittest discover -s tests -v
```

```
lct.py                  entry point / CLI
tracker/
  bank.py               loads data/problems.json; tag & topic weights; typical ratings
  topics.py             LeetCode tag -> interview topic groups (+ importance)
  curated.py            NeetCode 150 / Blind 75 slugs
  model.py              performance score, Glicko engine, replay, readiness
  recommend.py          spaced repetition, topic needs, problem selection, mock
  analytics.py          dashboard payload
  storage.py            JSON persistence
  server.py             stdlib HTTP server + JSON API
  cli.py                terminal commands
scripts/sync_problems.py  builds data/problems.json
web/                    dashboard (vanilla JS, inline SVG charts, no build step)
tests/
```
