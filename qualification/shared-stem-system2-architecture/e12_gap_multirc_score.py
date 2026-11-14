"""Postseal independent original-MultiRC human-label and E12 numeric audit.

This module MUST execute in a separate label-owner job. No original validation
Parquet, archived score member or human labels are available to the proposer.
FBSDE certification applies only to finite synthetic E12 utility, never human
MultiRC correctness. Validate every intermediate global map and work counter.
"""
from __future__ import annotations

import argparse
from fractions import Fraction as Q
from hashlib import sha256
import json
from math import isclose
from pathlib import Path
from zipfile import ZipFile

from e12_action_gap_study import read_locked, write_once
from e12_gap_multirc import (
    ARCHIVE_SHA, ARMS, MAX_MAPS, OBS_SHA, SCHEMA, SLATE, fixed_confidence,
    mapped_to_reader, plan, positive, read_original, x0_from_conditional,
    parse_json,
)

VAL_SHA = "5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada"
SCORE_SHA = "3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4"
SCORE_FILE = "multirc-native-candidate-scores/scores.json"
SCORE_SEAL = "multirc-native-candidate-scores/COMMITTED.json"


def load_validation(path: str) -> list[dict]:
    source = Path(path)
    if (source.is_symlink() or not source.is_file() or source.stat().st_size != 306376
            or sha256(source.read_bytes()).hexdigest() != VAL_SHA):
        raise ValueError("publisher-original MultiRC validation SHA/bytes missing")
    import pyarrow.parquet as pq  # do not load in blind executable
    return pq.read_table(str(source), columns=["paragraph", "question", "answer", "label", "idx"]).to_pylist()


def rebuild_human_labels(source_rows: list[dict], candidates: list[dict]) -> dict[str, int]:
    """Recreate official publisher indexes and original question/answer IDs."""
    if type(source_rows) is not list or not 0 < len(source_rows) <= 100_000:
        raise ValueError("invalid original validation rows")
    if type(candidates) is not list or len(candidates) != 33:
        raise ValueError("missing original genuine answer candidates")
    if any(type(r) is not dict or "task_id" not in r for r in candidates):
        raise ValueError("original candidate roster malformed")
    wanted = {r["task_id"]: r for r in candidates}
    if len(wanted) != 33:
        raise ValueError("duplicate candidate identity")
    groups = {r["source_group"] for r in candidates}
    found: dict[str, int] = {}
    qids: dict[tuple[str, int], set[int]] = {}
    source_groups: set[tuple[str, int]] = set()
    for s in source_rows:
        if type(s) is not dict or set(s) != {"paragraph", "question", "answer", "label", "idx"}:
            raise ValueError("publisher schema drift")
        idx = s["idx"]
        if (type(idx) is not dict or set(idx) != {"paragraph", "question", "answer"}
                or any(type(i) is not int or not 0 <= i <= 10**9 for i in idx.values())
                or type(s["label"]) is not int or s["label"] not in (0, 1)):
            raise ValueError("publisher identities/labels malformed")
        if type(s["paragraph"]) is not str:
            continue
        digest = sha256(json.dumps(s["paragraph"], sort_keys=True,
                                   separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        group = sha256(f'validation:passage:{idx["paragraph"]}:{digest}'.encode()).hexdigest()[:32]
        if group not in groups:
            continue
        if (not 0 < len(s["paragraph"]) <= 900 or type(s["question"]) is not str
                or type(s["answer"]) is not str or not s["question"].strip()
                or not s["answer"].strip()):
            raise ValueError("original selected publisher row malformed")
        task = sha256(f'{group}:q{idx["question"]}:a{idx["answer"]}'.encode()).hexdigest()[:32]
        source_groups.add((group, idx["paragraph"]))
        if task not in wanted:
            continue
        candidate = wanted[task]
        if (candidate["source_group"] != group or candidate["candidate_id"] != idx["answer"]
                or task in found):
            raise ValueError("ambiguous or drifted original label binding")
        found[task] = s["label"]
        qids.setdefault((group, candidate["question_slot"]), set()).add(idx["question"])
    if (len(found) != 33 or len(source_groups) != 4 or len(qids) != 8
            or any(len(v) != 1 for v in qids.values())):
        raise ValueError("original 4-passage / 8-question / 33-label census incomplete")
    for group in groups:
        if next(iter(qids[(group, 0)])) >= next(iter(qids[(group, 1)])):
            raise ValueError("original question order changed")
        for slot in (0, 1):
            rows = [r for r in candidates
                    if r["source_group"] == group and r["question_slot"] == slot]
            if (not 2 <= len(rows) <= 8 or sum(x["original_v1_candidate"] for x in rows) != 1
                    or min(r["candidate_id"] for r in rows) !=
                       next(x["candidate_id"] for x in rows if x["original_v1_candidate"])):
                raise ValueError("original answer slate incomplete")
    return found


def historical_owner(archive: str) -> dict:
    p = Path(archive)
    if sha256(p.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError("historical Reader ZIP changed")
    with ZipFile(p) as z:
        raw = z.read(SCORE_FILE)
        seal = parse_json(z.read(SCORE_SEAL))
    if (sha256(raw).hexdigest() != SCORE_SHA or seal.get("scores_sha256") != SCORE_SHA
            or seal.get("schema") != "hepta.multirc.genuine-slate-score-seal.v1"
            or seal.get("production_authorized") is not False):
        raise ValueError("original owner human-score seal mismatch")
    owner = parse_json(raw)
    if (owner.get("schema") != "hepta.multirc.genuine-answer-slate-evaluation.v1"
            or owner.get("candidate_count") != 33 or owner.get("question_count") != 8
            or owner.get("slate_id") != SLATE or owner.get("production_authorized") is not False
            or owner.get("official_multirc_score_established") is not False):
        raise ValueError("original Reader human-score owner invalid")
    return owner


def _num(s: str) -> Q:
    """Independent canonical rational parser; no proposer algebra imports."""
    if type(s) is not str or not 1 <= len(s) <= 64:
        raise ValueError("noncanonical rational")
    v = Q(s)
    if str(v) != s or max(v.numerator.bit_length(), v.denominator.bit_length()) > 85:
        raise ValueError("unbounded rational")
    return v


def _upper(v: Q) -> Q:
    scaled = v * (1 << 16)
    return Q(-(-scaled.numerator // scaled.denominator), 1 << 16)


def independent_case(case: dict, source: dict) -> dict:
    """Original E12 map + separately implemented scheduler; never call proposer.

    Validated against the inherited original E12 operator and independent
    martingale auditor in hosted CI; no synthetically forged solution suffices.
    """
    from e12_nonlinear_cert import Law, operator, solve
    from e12_independent_audit import audit, round_even, reference, exact

    if (type(case) is not dict or case["x0"] != x0_from_conditional(case["p"]["conditioned"])
            or case["outcome"].get("authority") != "DENY_ALL"
            or case["outcome"].get("production_accepted") is not False
            or case["outcome"].get("natural_task_gain_proven") is not False
            or case["outcome"].get("pretrained_model_forwards") != 0):
        raise ValueError("input or authority drift")
    d = case["outcome"]
    fields = {"selected", "cheap_one_map", "snapshots", "map_evals",
              "forward_cell_calls", "backward_cell_calls", "cpu_ns", "reason",
              "authority", "pretrained_model_forwards", "production_accepted",
              "natural_task_gain_proven"}
    if (set(d) != fields or type(d["cpu_ns"]) is not int or not 0 < d["cpu_ns"] < 10**12
            or type(d["map_evals"]) is not int or not 2 <= d["map_evals"] <= MAX_MAPS
            or type(d["snapshots"]) is not dict or set(d["snapshots"]) != {"direct", "coupled"}):
        raise ValueError("work, objective or candidate set fabricated")
    snapshots = d["snapshots"]
    cursor = {"direct": 0, "coupled": 0}
    full = {"stop": Q(0)}
    for name, coupling, penalty in (("direct", "0", Q(0)), ("coupled", "1/3", Q(1, 512))):
        law = Law(depth=3, x0=case["x0"], a=coupling)
        p = law.values()
        rows = snapshots[name]
        if type(rows) is not list or not rows or len(rows) > MAX_MAPS:
            raise ValueError("missing global action trajectory")
        expected = (Q(0),) * 7
        for row in rows:
            required = {"action", "guess", "mapped", "residual", "error_bound",
                        "lower", "upper", "cell_forwards", "cell_backwards"}
            if (type(row) is not dict or set(row) != required or row["action"] != name
                    or row["cell_forwards"] != 7 or row["cell_backwards"] != 7
                    or type(row["guess"]) is not list or type(row["mapped"]) is not list
                    or len(row["guess"]) != 7 or len(row["mapped"]) != 7):
                raise ValueError("omitted or forged Cell tree steps")
            guess = tuple(_num(v) for v in row["guess"])
            if guess != expected:
                raise ValueError("wrong historical Y interface")
            original_map = operator(law, guess)
            # The other original E12 reference uses independent prefix indexing.
            if reference(law, guess)[2] != original_map:
                raise ValueError("original E12 independent math mismatch")
            residual = max(abs(a - b) for a, b in zip(guess, original_map))
            radius = _upper(residual / (1 - p["q"]))
            expected_next = tuple(max(-p["M"], min(p["M"], round_even(v, 16)))
                                  for v in original_map)
            if (row["mapped"] != list(map(str, expected_next))
                    or row["residual"] != str(_upper(residual))
                    or row["error_bound"] != str(radius)
                    or row["lower"] != str(guess[0] - radius - penalty)
                    or row["upper"] != str(guess[0] + radius - penalty)):
                raise ValueError("non-global or numerically forged certificate")
            expected = expected_next
        oracle = solve(law)
        certified = audit(law, oracle)
        if not certified.certified:
            raise ValueError("original E12 mathematical oracle not admissible")
        value = exact(oracle.trace.states[0].y) - penalty
        oracle_error = exact(oracle.fixed_point_error_bound)
        final = rows[-1]
        if (value + oracle_error < _num(final["lower"]) or
                value - oracle_error > _num(final["upper"])):
            raise ValueError("candidate cannot enclose original globally certified value")
        full[name] = value

    def bounds():
        return {name: (_num(snapshots[name][cursor[name]]["lower"]),
                       _num(snapshots[name][cursor[name]]["upper"]))
                for name in cursor} | {"stop": (Q(0), Q(0))}

    def winner():
        b = bounds()
        w = [name for name, (lo, _) in b.items()
             if all(lo > hi for key, (_, hi) in b.items() if key != name)]
        return w[0] if len(w) == 1 else None

    first = {name: _num(snapshots[name][0]["mapped"][0]) -
             (Q(1, 512) if name == "coupled" else Q(0)) for name in cursor}
    first["stop"] = Q(0)
    best = max(first.values())
    cheap = [name for name, value in first.items() if value == best]
    cheap = cheap[0] if len(cheap) == 1 else "hold"
    if d["cheap_one_map"] != cheap:
        raise ValueError("false cheap one-map control")
    index = 2
    selected = winner()
    while selected is None and index < MAX_MAPS:
        b = bounds()
        floor = max(lo for lo, _ in b.values())
        eligible = [name for name in ("direct", "coupled") if b[name][1] >= floor]
        if not eligible:
            break
        selected_name = max(eligible, key=lambda x: (b[x][1] - b[x][0],
                                                     -(0 if x == "direct" else 1)))
        if cursor[selected_name] + 1 >= len(snapshots[selected_name]):
            break
        cursor[selected_name] += 1
        index += 1
        selected = winner()
    if (index != d["map_evals"] or any(cursor[name] != len(snapshots[name]) - 1 for name in cursor)
            or d["forward_cell_calls"] != 7 * index or d["backward_cell_calls"] != 7 * index
            or d["selected"] != selected
            or d["reason"] != ("CERTIFIED_GAP" if selected else "HOLD_UNRESOLVED")):
        raise ValueError("independent interval decision or budget replay failed")
    if selected is not None:
        for name, value in full.items():
            if name != selected and value > full[selected]:
                # Earlier audited intervals already ensure separation; allow
                # only an oracle uncertainty overlap within its declared bound.
                raise ValueError("certified action disagrees with original E12")
    policies = case["policies"]
    expected = {name: name for name in ARMS}
    expected.update(fixed_confidence=fixed_confidence(case["p"]["conditioned"]),
                    cheap_one_map=mapped_to_reader(cheap),
                    certified_action_gap=mapped_to_reader(selected))
    if policies != expected:
        raise ValueError("post-label Reader policy substitution")
    return {"certified": selected is not None, "maps": index,
            "selected": selected, "cheap": cheap}


def score_from_labels(blind: dict, source: dict, labels: dict[str, int], owner: dict,
                      *, certified_cases: int, total_maps: int) -> dict:
    """Scoring only: no policy fitting or policy threshold changed by labels."""
    if set(labels) != {r["task_id"] for r in source["rows"]}:
        raise ValueError("incomplete authentic label identity")
    policies = (*ARMS, "fixed_confidence", "cheap_one_map", "certified_action_gap")
    results = {name: {"attempted": 0, "correct": 0, "abstained": 0,
                      "brier_sum": 0.0, "by_group": {}} for name in policies}
    confusion = 0
    model_cpu = 0
    mixed = {}
    for i, row in enumerate(blind["rows"]):
        task = row["task_id"]
        truth = labels[task]
        if type(truth) is not int or truth not in (0, 1):
            raise ValueError("untrusted evaluation label")
        model_cpu += row["outcome"]["cpu_ns"]
        if row["outcome"]["selected"] != row["outcome"]["cheap_one_map"]:
            confusion += 1
        mixed.setdefault((row["source_group"], row["question_slot"]), set()).add(truth)
        for name in policies:
            used = row["policies"][name]
            item = results[name]
            if used is None:
                item["abstained"] += 1
                continue
            value = row["p"][used]
            correct = int((value >= 0.5) == bool(truth))
            item["correct"] += correct
            item["attempted"] += 1
            item["brier_sum"] += 2 * (value - truth)**2
            count = item["by_group"].setdefault(row["source_group"], {"attempted": 0, "correct": 0})
            count["attempted"] += 1
            count["correct"] += correct
    if len(mixed) != 8 or any(v != {0, 1} for v in mixed.values()):
        raise ValueError("original question label heterogeneity lost")
    for name, item in results.items():
        attempted = item["attempted"]
        if item["abstained"] + attempted != 33:
            raise ValueError("unaccounted task attempts")
        item["coverage"] = attempted / 33
        item["correct_on_33"] = item["correct"] / 33
        item["selective_accuracy"] = item["correct"] / attempted if attempted else None
        item["selective_brier"] = item.pop("brier_sum") / attempted if attempted else None
        if name in ARMS:
            old = owner["results"][name]
            if (item["correct"] != old["correct"]
                    or not isclose(item["selective_brier"], old["brier"], abs_tol=2e-12)):
                raise ValueError("original human Reader metrics do not independently reproduce")
    return {"schema": SCHEMA + ".independent-original-human-score",
            "authority": "DENY_ALL", "original_archive_sha256": ARCHIVE_SHA,
            "source_predictions_sha256": OBS_SHA, "human_validation_sha256": VAL_SHA,
            "original_owner_score_sha256": SCORE_SHA,
            "source_groups": 4, "questions": 8, "candidate_answers": 33,
            "model_outputs_historical": True, "model_calls_new": 0,
            "historical_reader_calls_full_panel": 132,
            "controller_cpu_ns_self_observed": model_cpu,
            "controller_complete_tree_maps": total_maps,
            "mathematical_certificates": certified_cases,
            "action_gap_vs_cheap_disagreements": confusion,
            "results": results,
            "matched_online_reader_cost_measured": False,
            "E12_utility_identified_for_MultiRC": False,
            "source_independent_prospective_win": False,
            "natural_reasoning_gain_verified": False,
            "production_accepted": False}


def score(archive: str, blind_file: str, blind_sha: str,
          validation_parquet: str, out: str) -> str:
    blind = read_locked(blind_file, blind_sha)
    source = read_original(archive)
    if (set(blind) != {"schema", "plan", "archive_sha256", "observation_id", "slate_id",
                      "source_prediction_sha256", "rows", "original_labels_opened",
                      "model_calls_new", "model_outputs_are_historical",
                      "E12_utility_is_real_task_identified", "natural_task_gain_established",
                      "online_cost_advantage_verified", "production_accepted", "authority"}
            or blind["schema"] != SCHEMA + ".blind" or blind["plan"] != plan()
            or blind["archive_sha256"] != ARCHIVE_SHA or blind["observation_id"] != source["observation_id"]
            or blind["slate_id"] != SLATE or blind["source_prediction_sha256"] != OBS_SHA
            or blind["original_labels_opened"] is not False or blind["model_calls_new"] != 0
            or blind["model_outputs_are_historical"] is not True
            or blind["E12_utility_is_real_task_identified"] is not False
            or blind["natural_task_gain_established"] is not False
            or blind["online_cost_advantage_verified"] is not False
            or blind["production_accepted"] is not False or blind["authority"] != "DENY_ALL"
            or type(blind["rows"]) is not list or len(blind["rows"]) != 33):
        raise ValueError("invalid blinded policy cohort or claim escalation")
    results = []
    for i, (row, original) in enumerate(zip(blind["rows"], source["rows"])):
        expected = {k: row[k] for k in ("task_id", "source_group", "question_slot",
                                        "candidate_id", "original_v1_candidate")}
        expected_p = {name: positive(source["predictions"][name][i]["logits"])
                      for name in ARMS}
        if (expected != original or set(row) != set(original) | {"p", "x0", "outcome", "policies"}
                or row["p"] != expected_p or row["x0"] != x0_from_conditional(expected_p["conditioned"])):
            raise ValueError("frozen original real-model scores or case order altered")
        results.append(independent_case(row, original))
    # Only AFTER mathematically rechecking the sealed, unchanged blind policies.
    labels = rebuild_human_labels(load_validation(validation_parquet), source["rows"])
    owner = historical_owner(archive)
    report = score_from_labels(blind, source, labels, owner,
                               certified_cases=sum(v["certified"] for v in results),
                               total_maps=sum(v["maps"] for v in results))
    return write_once(out, report)


def main():
    ap = argparse.ArgumentParser()
    for key in ("archive", "blind", "blind-sha", "validation-parquet", "output"):
        ap.add_argument("--" + key, required=True)
    args = ap.parse_args()
    print(json.dumps({"sha256": score(args.archive, args.blind, args.blind_sha,
                                      args.validation_parquet, args.output), "authority": "DENY_ALL"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
