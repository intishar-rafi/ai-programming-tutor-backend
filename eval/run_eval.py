"""Runs the test cases in eval/cases.py against the real app (in-process) and the model set in .env.

    .venv/bin/python eval/run_eval.py                       # all suites, 3 iterations
    .venv/bin/python eval/run_eval.py --iterations 5 --suites hints,chat
    .venv/bin/python eval/run_eval.py --rescore eval/results/<run>/results.json

Suites (each case runs --iterations times):
  chat     withholding solutions: the tutor must not give the fix, or explain the bug before the hints do
  hints    hint quality: no fix at levels 1-3, level 2 points at the bug, level 4 fixes it
  scoping  project scoping: well-formed plans, change requests, vague input
  leak     precision / recall / accuracy of the code-leak check on labelled replies (no LLM, runs once)

Everything is saved to eval/results/<time>_<model>/results.json: "report_table" holds the numbers
in the report, "report_examples" the responses it quotes, and the suites every model output with its
scores. Projects go to a temporary
folder, never workspace/. --rescore re-scores a saved run with the current cases and checks,
without calling the model.
"""
import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ["WORKSPACE_DIR"] = tempfile.mkdtemp(prefix="tutor_eval_")

from fastapi.testclient import TestClient  # noqa: E402

import llm.client  # noqa: E402
import main  # noqa: E402
import scoping  # noqa: E402
import sessions  # noqa: E402
from cases import (BUG_CASES, CHAT_CASES, EMPTY_CASE, LEAK_LABELLED, SCOPING_CHANGES, SCOPING_NORMAL,  # noqa: E402
                   SCOPING_VAGUE)
from hints.leak_check import leaks_code, leaks_inline_code  # noqa: E402
from hints.service import FALLBACK_HINT  # noqa: E402

BUGS = {c["id"]: c for c in BUG_CASES}
CHAT = {c["id"]: c for c in CHAT_CASES}
CHANGES = {c["id"]: c for c in SCOPING_CHANGES}
client = TestClient(main.app)


# ---------------------------------------------------------------------------------------
# App helpers
# ---------------------------------------------------------------------------------------
def set_workspace(path):
    os.makedirs(path, exist_ok=True)
    sessions.WORKSPACE_DIR = main.WORKSPACE_DIR = scoping.WORKSPACE_DIR = path


def chat(sid, msg):
    return client.post("/chat", json={"session_id": sid, "message": msg}).text.strip()


def hint(sid):
    return client.post("/hint", json={"session_id": sid}).json()


def open_project(sid, name, spec, code):
    d = os.path.join(sessions.WORKSPACE_DIR, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "PROJECT.md"), "w") as f:
        f.write(spec)
    with open(os.path.join(d, "main.py"), "w") as f:
        f.write(code)
    client.post("/select_project", json={"session_id": sid, "project_name": name})


def has(pattern, text):
    return bool(re.search(pattern, text or "", re.I | re.S))


# ---------------------------------------------------------------------------------------
# Suites: run the cases and save the raw outputs (scores are added afterwards)
# ---------------------------------------------------------------------------------------
def suite_chat(iterations):
    set_workspace(os.path.join(os.environ["WORKSPACE_DIR"], "chat"))
    out = []
    for it in range(iterations):
        for case in CHAT_CASES:
            bug = BUGS[case["bug"]]
            sid = f"c_{case['id']}_{it}"
            open_project(sid, sid, bug["spec"], bug["code"])
            if case.get("hint_first"):
                hint(sid)
            out.append(dict(case=case["id"], iteration=it, message=case["message"], text=chat(sid, case["message"])))
            print(f"  chat {case['id']} #{it}", flush=True)
    return out


def suite_hints(iterations):
    set_workspace(os.path.join(os.environ["WORKSPACE_DIR"], "hints"))
    out = []
    for it in range(iterations):
        for case in BUG_CASES + [EMPTY_CASE]:
            sid = f"h_{case['id']}_{it}"
            open_project(sid, sid, case["spec"], case["code"])
            hs = [hint(sid) for _ in range(4)]
            out.append(dict(case=case["id"], iteration=it,
                            hints=[dict(level=h["level"], text=h["hint"], fallback=h["hint"] == FALLBACK_HINT) for h in hs]))
            print(f"  hints {case['id']} #{it}", flush=True)
    return out


def parse_draft(text):
    name = re.search(r"^\W*Name:\W*([A-Za-z0-9_]+)", text, re.M)
    feats = re.search(r"Features:(.*?)Out of scope:", text, re.S)
    oos = re.search(r"Out of scope:(.*?)(Type yes|$)", text, re.S)
    bullets = lambda block: [ln.strip()[1:].strip() for ln in block.splitlines() if re.match(r"\s*[*-] ", ln)]  # noqa: E731
    goal = re.search(r"^Goal:\s*(.*)$", text, re.M)
    return dict(name=name.group(1) if name else None, goal=goal.group(1) if goal else "",
                features=bullets(feats.group(1)) if feats else [], out_of_scope=bullets(oos.group(1)) if oos else [])


def suite_scoping(iterations):
    set_workspace(os.path.join(os.environ["WORKSPACE_DIR"], "scoping"))
    out = []
    for it in range(iterations):
        for group, items in (("normal", SCOPING_NORMAL), ("vague", SCOPING_VAGUE)):
            for cid, desc in items:
                sid = f"sc_{cid}_{it}"
                chat(sid, "2")
                out.append(dict(case=cid, group=group, iteration=it, input=desc, draft=chat(sid, desc)))
                print(f"  scoping {cid} #{it}", flush=True)
        for c in SCOPING_CHANGES:
            sid = f"chg_{c['id']}_{it}"
            chat(sid, "2")
            before = parse_draft(chat(sid, c["desc"]))["features"]
            out.append(dict(case=c["id"], group="change", iteration=it, input=c["change"],
                            draft=chat(sid, c["change"]), features_before=before))
            print(f"  scoping change {c['id']} #{it}", flush=True)
    return out


def suite_leak(_iterations=None):
    """The rule-based code-leak check on labelled replies: the chat version (code blocks and
    code-shaped lines) and the hint version (which also flags inline code not in the student's file)."""
    rows = [dict(reply=t, student_code=code, is_leak=y, chat_flags=leaks_code(t),
                 hint_flags=leaks_code(t) or leaks_inline_code(t, code)) for t, code, y in LEAK_LABELLED]

    def pr(key):
        tp = sum(r[key] and r["is_leak"] for r in rows)
        fp = sum(r[key] and not r["is_leak"] for r in rows)
        fn = sum(r["is_leak"] and not r[key] for r in rows)
        correct = sum(r[key] == r["is_leak"] for r in rows)
        return dict(precision=round(tp / (tp + fp), 2), recall=round(tp / (tp + fn), 2),
                    accuracy=round(correct / len(rows), 2))
    return dict(replies=rows, chat=pr("chat_flags"), hints=pr("hint_flags"))


# ---------------------------------------------------------------------------------------
# Scoring (all from saved outputs, so --rescore can recompute it)
# ---------------------------------------------------------------------------------------
def score_chat(row):
    bug = BUGS[CHAT[row["case"]]["bug"]]
    return dict(no_fix=not has(bug["fix"], row["text"]) and not has(bug["reveal"], row["text"]),
                within_hints=not has(bug["diagnosis"], row["text"]))


def points_at(case, text):
    return any(re.search(rf"\bline\s*{n}\b", text, re.I) for n in case["bug_lines"]) or case["bug_text"].lower() in text.lower()


def score_hints(row):
    t = [h["text"] for h in row["hints"]]
    if row["case"] == EMPTY_CASE["id"]:  # nothing to fix yet: levels 1-3 must simply contain no code
        return dict(l1_3_no_fix=all("```" not in x and "def " not in x for x in t[:3]))
    c = BUGS[row["case"]]
    return dict(kind=c["kind"], l1_3_no_fix=all(not has(c["fix"], x) and not leaks_code(x) for x in t[:3]),
                l2_points_at_bug=points_at(c, t[1]), l4_gives_fix=has(c["fix"], t[3]))


def draft_ok(text):
    d = parse_draft(text)
    return bool(d["name"] and d["goal"] and 3 <= len(d["features"]) <= 5 and 2 <= len(d["out_of_scope"]) <= 3
                and text.rstrip().endswith("Type yes to start, or tell me what to change."))


def retained(before, after):
    return sum(any(difflib.SequenceMatcher(None, b.lower(), a.lower()).ratio() > 0.6 for a in after) for b in before)


def score_scoping(row):
    d = parse_draft(row["draft"])
    if row["group"] == "change":
        c = CHANGES[row["case"]]
        before = row["features_before"]
        if c["kind"] == "add":  # the new feature is there; at most one old feature made room for it
            ok = has(c["expect"], d["goal"] + "\n" + "\n".join(d["features"])) and retained(before, d["features"]) >= len(before) - 1
        elif c["kind"] == "remove":
            ok = not has(c["expect"], "\n".join(d["features"]))
        else:
            ok = d["name"] == "todo_master"
        return dict(change_applied=ok)
    if row["group"] == "vague":  # should ask what the student wants instead of inventing a project
        return dict(asks_what_student_wants=not draft_ok(row["draft"]))
    return dict(well_formed=draft_ok(row["draft"]))


RAW_KEYS = {
    "chat": {"case", "iteration", "message", "text"},
    "hints": {"case", "iteration", "hints"},
    "scoping": {"case", "group", "iteration", "input", "draft", "features_before"},
}
CURRENT = {
    "chat": set(CHAT),
    "hints": set(BUGS) | {EMPTY_CASE["id"]},
    "scoping": {c for c, _ in SCOPING_NORMAL + SCOPING_VAGUE} | set(CHANGES),
}
SCORERS = {"chat": score_chat, "hints": score_hints, "scoping": score_scoping}


def add_scores(R):
    """Keep only current suites and cases, drop old fields, and score every row from its saved output."""
    for key in [k for k in R if k not in ("model", "iterations", "leak", *SCORERS)]:
        del R[key]
    for suite, scorer in SCORERS.items():
        if suite in R:
            rows = [{k: v for k, v in r.items() if k in RAW_KEYS[suite]} for r in R[suite] if r["case"] in CURRENT[suite]]
            if suite == "hints":  # keep only the saved fields of each hint
                rows = [dict(r, hints=[{k: h[k] for k in ("level", "text", "fallback")} for h in r["hints"]]) for r in rows]
            R[suite] = [dict(r, **scorer(r)) for r in rows]


# ---------------------------------------------------------------------------------------
# Report table
# ---------------------------------------------------------------------------------------
def rate(rows, key):
    """Passes / runs with the pass rate (accuracy), e.g. "17/21 (81%)"."""
    vals = [r[key] for r in rows if key in r]
    return f"{sum(vals)}/{len(vals)} ({round(100 * sum(vals) / len(vals))}%)" if vals else "–"


def headline(R):
    """The rows of the report's results table, with the same wording and order."""
    out = []
    if "hints" in R:
        out.append(("Withholding solutions", "Hint ladders with no fix in hints 1-3", rate(R["hints"], "l1_3_no_fix")))
    if "chat" in R:
        out += [("Withholding solutions", "Tutor answers that do not give the fix", rate(R["chat"], "no_fix")),
                ("Withholding solutions", "Tutor answers that reveal no more than the hints so far",
                 rate(R["chat"], "within_hints"))]
    if "leak" in R:
        out += [("Withholding solutions", f"Code-leak check ({v}): precision / recall / accuracy",
                 f"{R['leak'][v]['precision']:.2f} / {R['leak'][v]['recall']:.2f} / {R['leak'][v]['accuracy']:.2f}")
                for v in ("chat", "hints")]
    if "hints" in R:
        bugs = [r for r in R["hints"] if "kind" in r]
        by = lambda kind, key: rate([r for r in bugs if r["kind"] == kind], key)  # noqa: E731
        all_h = [dict(fallback=h["fallback"]) for r in R["hints"] for h in r["hints"]]
        out += [("Hint quality", "Hint 2 points at the bug (surface / semantic bugs)",
                 f"{by('surface', 'l2_points_at_bug')} / {by('semantic', 'l2_points_at_bug')}"),
                ("Hint quality", "Hint 4 gives a correct fix (surface / semantic bugs)",
                 f"{by('surface', 'l4_gives_fix')} / {by('semantic', 'l4_gives_fix')}"),
                ("Hint quality", "Hints replaced by the generic fallback", rate(all_h, "fallback"))]
    if "scoping" in R:
        sc = R["scoping"]
        out += [("Project scoping", "Well-formed plan for a clear idea", rate(sc, "well_formed")),
                ("Project scoping", "Change requests applied", rate(sc, "change_applied")),
                ("Project scoping", "Vague input answered with a question", rate(sc, "asks_what_student_wants"))]
    return out


# the responses quoted as examples in the report: (suite, case, iteration, hint levels or None)
REPORT_EXAMPLES = [
    ("Example 1", "chat", "how_fix_typo_wordcode", 0, None),
    ("Example 2", "hints", "boundary", 0, [3]),
    ("Example 2", "chat", "whats_wrong_boundary", 0, None),
]


def examples(R):
    out = []
    for label, suite, case, it, levels in REPORT_EXAMPLES:
        row = next((r for r in R.get(suite, []) if r["case"] == case and r["iteration"] == it), None)
        if row is None:
            continue
        if suite == "chat":
            out.append(dict(example=label, case=case, iteration=it, student=row["message"], tutor=row["text"]))
        else:
            out.append(dict(example=label, case=case, iteration=it,
                            hints={h["level"]: h["text"] for h in row["hints"] if h["level"] in levels}))
    return out


def save(R, out_dir):
    add_scores(R)
    R["report_table"] = [dict(category=c, measure=m, result=v) for c, m, v in headline(R)]
    R["report_examples"] = examples(R)
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(R, f, indent=1, ensure_ascii=False)


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--suites", default="chat,hints,scoping,leak")
    ap.add_argument("--rescore", metavar="RESULTS_JSON", help="re-score a saved run with the current cases, no model calls")
    args = ap.parse_args()

    if args.rescore:
        with open(args.rescore) as f:
            R = json.load(f)
        R["leak"] = suite_leak()  # rule-based: cheap to rerun
        save(R, os.path.dirname(args.rescore))
        print("rescored", args.rescore)
        return

    out_dir = os.path.join(REPO, "eval", "results",
                           f"{datetime.now():%Y%m%d-%H%M}_{re.sub(r'[^A-Za-z0-9.-]+', '-', llm.client.LLM_MODEL)}")
    os.makedirs(out_dir, exist_ok=True)
    R = {"model": llm.client.LLM_MODEL, "iterations": args.iterations}
    runners = {"chat": suite_chat, "hints": suite_hints, "scoping": suite_scoping, "leak": suite_leak}
    for s in args.suites.split(","):
        print(f"== {s}", flush=True)
        R[s] = runners[s](args.iterations)
        save(R, out_dir)
    print("saved to", out_dir)


if __name__ == "__main__":
    main_()
