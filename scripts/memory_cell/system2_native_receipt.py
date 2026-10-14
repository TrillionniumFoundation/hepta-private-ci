"""Read-only audit of the first System2 native run; never new model evidence.

The outer ZIP pin comes from GitHub, not from the archive being inspected.
Recorded diagnostic F1 is preserved, not independently rejudged from unavailable
reference annotations. No training, parameter selection, or Reader invocation.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SOURCE = "aecde9ee5882879cfb2b34d98c241c44b752ef3e"
TREE = "25acf4de2b0e7fedae546a31276efa3e65be8e1f"
ARCHIVE = "80037375c44927f71e15dea508abb6ac3a2d5ccd03cefe2a5c21beedad37247e"
ARMS = (
    "rag",
    "linear",
    "gated",
    "recurrent",
    "tree_critic",
    "ndu_deterministic",
    "fbsde_stochastic",
    "wrong_stitch_control",
)
CONDITIONS = (
    "no_evidence",
    "ordinary_retrieval",
    "human_sufficient",
    "critical_premise_removed",
)
PHASES = ("select", "retention", "test", "transfer")


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON field")
            out[key] = value
        return out

    def invalid(_):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def verified_archive(path, expected):
    """Read bounded regular files only; never extract or execute archive code."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise ValueError("external archive pin required")
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("symlink archive")
    if path.stat().st_size > 64 * 1024**2:
        raise ValueError("compressed archive budget")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("archive digest mismatch")
    out = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 256 or sum(i.file_size for i in infos) > 256 * 1024**2:
            raise ValueError("archive expansion budget")
        for info in infos:
            name = info.filename
            p = PurePosixPath(name)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (
                name in out
                or p.is_absolute()
                or p.as_posix() != name
                or ".." in p.parts
                or "\\" in name
                or not p.parts
                or any(ord(c) < 32 for c in name)
                or info.is_dir()
                or mode not in (0, stat.S_IFREG)
            ):
                raise ValueError("unsafe/duplicate archive member")
            out[name] = archive.read(info)
    manifest = {}
    for line in out["SHA256SUMS"].decode().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if not match or match[2] in manifest:
            raise ValueError("malformed/duplicate file manifest")
        manifest[match[2]] = match[1]
    if set(manifest) != set(out) - {"SHA256SUMS"}:
        raise ValueError("incomplete or extra file inventory")
    for name, sha in manifest.items():
        if hashlib.sha256(out[name]).hexdigest() != sha:
            raise ValueError("inner file digest mismatch")
    return out


def number(value, minimum=0, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError("invalid measured number")
    if maximum is not None and value > maximum:
        raise ValueError("measured number outside registered range")
    return value


def index_rows(rows, fields, expected):
    result = {}
    for row in rows:
        key = tuple(row[f] for f in fields)
        if key in result:
            raise ValueError("duplicated census row")
        result[key] = row
    if set(result) != expected:
        raise ValueError("missing or extra planned row")
    return result


def request(receipt):
    return (
        receipt["reader_identity"],
        receipt["reader_profile"],
        receipt["query_digest"],
        receipt["input_ids_digest"],
    )


def generated(row, key="reader"):
    return (row["answer"], row[key]["generated_ids_digest"])


def analyze(plan, rows, scores, controls):
    if (
        tuple(plan["arms"]) != ARMS
        or plan["checkpoints"] != [16, 32, 48]
        or plan["production_accepted"] is not False
        or plan["reasoning_superiority"] is not False
    ):
        raise ValueError("unregistered arms, stages or acceptance claim")
    ids = plan["question_ids"]
    all_ids = [q for group in ids.values() for q in group]
    if set(ids) != {*PHASES, "train"} or len(set(all_ids)) != len(all_ids):
        raise ValueError("overlapping or unknown question cuts")
    qphase = {q: p for p in PHASES for q in ids[p]}
    expected = {(q, a, c) for q in qphase for a in ARMS for c in plan["checkpoints"]}
    raw = index_rows(rows, ("question_id", "arm", "checkpoint"), expected)
    scored = index_rows(scores, ("question_id", "arm", "checkpoint"), expected)
    ctrl = index_rows(
        controls,
        ("question_id", "condition"),
        {(q, c) for q in qphase for c in CONDITIONS},
    )
    families, features, queries, profiles, answers = {}, {}, {}, set(), {}
    aggregates = {}
    for key, row in raw.items():
        q, arm, checkpoint = key
        score = scored[key]
        if (
            row["status"] not in ("succeeded", "failed")
            or score["family"] != row["family"]
            or type(score["failure"]) is not bool
            or score["failure"] != (row["status"] == "failed")
        ):
            raise ValueError("status or scoring identity drift")
        for mapping, identity, value in (
            (families, q, row["family"]),
            (features, q, row["feature_digest"]),
        ):
            if identity in mapping and mapping[identity] != value:
                raise ValueError("family/shared representation drift")
            mapping[identity] = value
        value = score["diagnostic_f1"]
        if value is not None:
            number(value, maximum=1)
        if row["status"] == "failed":
            if value != 0:
                raise ValueError("failed execution scored as success")
            continue
        rec = row["reader"]
        if not isinstance(row["answer"], str) or not row["answer"].strip():
            raise ValueError("empty successful answer")
        if (
            rec["reader_identity"] != plan["reader_inventory"]
            or rec["token_limit"] != plan["reader_input_token_limit"]
            or rec["answer_postprocessed"] is not False
            or rec["trainable_parameters"] != 0
            or rec["production_accepted"] is not False
        ):
            raise ValueError("Reader profile or provenance drift")
        for field in ("input_tokens", "generated_tokens"):
            if type(rec[field]) is not int:
                raise ValueError("token count is not an integer")
            number(rec[field], maximum=4096 if field == "input_tokens" else 64)
        number(rec["seconds"])
        number(row["cost"]["elapsed_seconds"])
        if (
            row["cost"]["limits"] != plan["limits"]
            or row["cost"]["attempted_operations"].get("reader_calls") != 1
        ):
            raise ValueError("budget or Reader attempt drift")
        for count in row["cost"]["attempted_operations"].values():
            if type(count) is not int:
                raise ValueError("operation counter type")
            number(count)
        selected = row["selected"]
        if (
            not isinstance(selected, list)
            or len(set(selected)) != len(selected)
            or any(type(i) is not int or i < 0 for i in selected)
            or len(selected) > plan["limits"]["evidence"]
            or len(selected) != len(rec["delivered_evidence"])
        ):
            raise ValueError("selection/delivery mismatch")
        for solver in row["policy"].get("solvers", []):
            for field in (
                "forward_residual",
                "backward_residual",
                "terminal_residual",
                "iteration_delta",
                "z_max",
            ):
                number(solver[field])
            if (
                type(solver["converged"]) is not bool
                or solver["wrong_boundary_control"]
                is not (arm == "wrong_stitch_control")
                or (arm != "wrong_stitch_control" and not solver["converged"])
            ):
                raise ValueError("invalid numerical solver status")
        query = rec["query_digest"]
        if q in queries and queries[q] != query:
            raise ValueError("query digest drift")
        queries[q] = query
        profiles.add((rec["reader_identity"], rec["reader_profile"]))
        signature = request(rec)
        output = generated(row)
        if signature in answers and answers[signature] != output:
            raise ValueError("identical deterministic request changed answer")
        answers[signature] = output
    if len(profiles) != 1:
        raise ValueError("mixed or absent frozen Reader")
    for (q, condition), row in ctrl.items():
        if row["status"] not in ("succeeded", "failed", "unavailable"):
            raise ValueError("unknown control status")
        if row["status"] != "succeeded":
            continue
        rec = row["receipt"]
        if (
            (rec["reader_identity"], rec["reader_profile"]) not in profiles
            or rec["query_digest"] != queries[q]
            or rec["token_limit"] != plan["reader_input_token_limit"]
            or rec["answer_postprocessed"] is not False
        ):
            raise ValueError("unmatched Reader control")
        if condition == "no_evidence" and rec["delivered_evidence"]:
            raise ValueError("nonempty no-evidence control")
        if request(rec) in answers and answers[request(rec)] != generated(
            row, "receipt"
        ):
            raise ValueError("control output drift")

    for checkpoint in plan["checkpoints"]:
        for arm in ARMS:
            group = [
                r for r in rows if r["arm"] == arm and r["checkpoint"] == checkpoint
            ]
            known = [
                scored[(r["question_id"], arm, checkpoint)]["diagnostic_f1"]
                for r in group
            ]
            valid = [v for v in known if v is not None]
            missing = len(known) - len(valid)
            success = [r for r in group if r["status"] == "succeeded"]
            solvers = [s for r in success for s in r["policy"].get("solvers", [])]
            same = sum(
                ctrl[(r["question_id"], "no_evidence")]["status"] == "succeeded"
                and request(r["reader"])
                == request(ctrl[(r["question_id"], "no_evidence")]["receipt"])
                and generated(r)
                == generated(ctrl[(r["question_id"], "no_evidence")], "receipt")
                for r in success
            )
            aggregates[f"{checkpoint}/{arm}"] = dict(
                planned=len(group),
                succeeded=len(success),
                failed=len(group) - len(success),
                scored=len(valid),
                unscored=missing,
                recorded_diagnostic_f1_mean=sum(valid) / len(valid) if valid else None,
                all_planned_f1_bounds=[
                    sum(valid) / len(group),
                    (sum(valid) + missing) / len(group),
                ],
                empty_evidence=sum(not r["selected"] for r in success),
                same_request_and_output_as_no_evidence=same,
                policy_and_reader_seconds=sum(
                    r.get("cost", {}).get("elapsed_seconds", 0) for r in group
                ),
                missing_cost_receipts=sum("cost" not in r for r in group),
                reader_seconds=sum(r["reader"]["seconds"] for r in success),
                input_tokens=sum(r["reader"]["input_tokens"] for r in success),
                output_tokens=sum(r["reader"]["generated_tokens"] for r in success),
                evaluated_path_solvers=len(solvers),
                nonconverged_path_solvers=sum(not s["converged"] for s in solvers),
                maximum_backward_residual=max(
                    (s["backward_residual"] for s in solvers), default=None
                ),
                maximum_terminal_residual=max(
                    (s["terminal_residual"] for s in solvers), default=None
                ),
                selected_solver_paths=sum(
                    r["policy"].get("selected_solver") is not None for r in success
                ),
            )
    matched = []
    for checkpoint in plan["checkpoints"]:
        for candidate in ARMS[1:]:
            changes = wins = losses = unknown = 0
            delta = 0.0
            for q in qphase:
                a, b = raw[(q, "rag", checkpoint)], raw[(q, candidate, checkpoint)]
                sa, sb = (
                    scored[(q, "rag", checkpoint)]["diagnostic_f1"],
                    scored[(q, candidate, checkpoint)]["diagnostic_f1"],
                )
                changes += a.get("selected") != b.get("selected")
                if sa is None or sb is None:
                    unknown += 1
                else:
                    delta += sb - sa
                    wins += sb > sa
                    losses += sb < sa
            n = len(qphase)
            matched.append(
                dict(
                    checkpoint=checkpoint,
                    candidate=candidate,
                    baseline="rag",
                    planned_pairs=n,
                    changed_selections=changes,
                    diagnostic_wins=wins,
                    diagnostic_losses=losses,
                    unscored_pairs=unknown,
                    all_planned_delta_bounds=[
                        (delta - unknown) / n,
                        (delta + unknown) / n,
                    ],
                    significance_established=False,
                )
            )
    collapsed = [
        arm
        for arm in ARMS[3:]
        if all(
            aggregates[f"{c}/{arm}"]["same_request_and_output_as_no_evidence"]
            == len(qphase)
            for c in plan["checkpoints"]
        )
    ]
    return dict(
        schema="hepta.system2.original-native-audit.v1",
        generating_source=plan["source_commit"],
        planned_policy_records=len(expected),
        successful_policy_records=sum(r["status"] == "succeeded" for r in rows),
        unique_evaluation_questions=len(qphase),
        recorded_source_family_groups=len(set(families.values())),
        source_family_counts=dict(Counter(families.values())),
        control_statuses={
            c: dict(Counter(ctrl[(q, c)]["status"] for q in qphase)) for c in CONDITIONS
        },
        arms_collapsed_to_no_evidence=collapsed,
        arms=aggregates,
        matched_contrasts=matched,
        verdict="reject_current_policy_candidate"
        if collapsed
        else "requires_independent_review",
        boundary_causal_effect_established=False,
        reader_adequacy_established=False,
        scoring="original recorded diagnostic token F1; reference labels not independently rejudged",
        historical_output_rewritten=False,
        new_reader_calls=0,
        independent_observations_added=0,
        production_accepted=False,
        superiority_claim=False,
    )


def audit(path):
    files = verified_archive(path, ARCHIVE)
    if (
        files["tested-commit.txt"].decode().strip() != SOURCE
        or files["tested-tree.txt"].decode().strip() != TREE
    ):
        raise ValueError("wrong generating source/tree")
    plan = strict_json(files["native/plan.json"])
    if (
        plan["source_commit"] != SOURCE
        or any(len(plan["question_ids"][p]) != 8 for p in PHASES)
        or len(plan["question_ids"]["train"]) != 48
    ):
        raise ValueError("not the frozen complete native cohort")

    def lines(name):
        return [strict_json(l) for l in files["native/" + name].splitlines()]

    result = analyze(
        plan,
        lines("attempts.jsonl"),
        strict_json(files["native/diagnostic-scores.json"]),
        lines("reader-controls.jsonl"),
    )
    summary = strict_json(files["native/run-summary.json"])
    if (
        summary["source_commit"] != SOURCE
        or summary["attempted"] != result["planned_policy_records"]
        or summary["failed"]
        != result["planned_policy_records"] - result["successful_policy_records"]
    ):
        raise ValueError("summary differs from actual row census")
    result.update(
        artifact_id=11703482865,
        run_id=38139194731,
        archive_sha256=ARCHIVE,
        verified_manifest_files=len(files) - 1,
        tested_tree=TREE,
        original_end_to_end_seconds=number(summary["elapsed_seconds"]),
    )
    # Exact source sampler arithmetic, not an inferred outcome/label observation.
    skipped = {
        r["question_id"]
        for r in strict_json(files["native/training-dispositions.json"])[
            "skipped_training"
        ]
    }
    eligible = [q for q in plan["question_ids"]["train"] if q not in skipped]
    visits = defaultdict(set)
    for step in range(96):
        visits[eligible[step % len(eligible)]].add(step % 4)
    result["historical_sampler_schedule"] = dict(
        final_stage_admitted_rows=len(eligible),
        reconstructed_from_pinned_source=True,
        observed_subset_label_counts_available=False,
        questions_with_only_one_requested_cardinality=sum(
            len(v) == 1 for v in visits.values()
        ),
        questions_scheduled_only_empty=sum(v == {0} for v in visits.values()),
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.archive)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "verdict",
                    "planned_policy_records",
                    "successful_policy_records",
                    "arms_collapsed_to_no_evidence",
                    "historical_sampler_schedule",
                )
            },
            sort_keys=True,
        )
    )
