"""Read-only, independently reproducible disposition of real Qwen RAG records.

This audits exact, publicly pinned ORIGINAL artifacts without calling a model.
Neither a passing test nor a complete citation *label* is an entailment verdict.
There are no signatures, production writers or parameter-learning permissions.
"""

from collections import Counter, defaultdict
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SOURCE_COMMIT = "6304b451268c73f3d1a605985226b102df841bbf"
ORIGINAL_COMMIT = "c9dd3aeff958fbdc4356a98718e96dec47f9b820"
ORIGINAL_PLAN_SHA = (
    "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
)
ARCHIVES = {
    "original": "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b",
    "reader": "7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8",
    "replay": "2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071",
}
ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)
KS = (1, 2, 3, 4, 6)
SCORE_FIELDS = frozenset(
    ("parsed_identifier", "strict_task_success", "required_sources_covered",
     "procedure_verification")
)
IDENTIFIER = re.compile(
    r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*"
)
MARKER = re.compile(r"\[E[1-9][0-9]*\]")
NATIVE_ROOT_PROFILE = b"hepta.memory-benchmark.source-root.v1\0"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def native_digest(value):
    return sha(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    )


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON literal: " + value)

    return json.loads(
        raw, object_pairs_hook=unique, parse_constant=invalid
    )


def archive(path, expected):
    """Pin outer ZIP *and* the exact complete manifest; never extract it."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular archive required")
    raw = path.read_bytes()
    if len(raw) > 16_000_000 or sha(raw) != expected:
        raise ValueError("archive digest or byte limit changed")
    with zipfile.ZipFile(path) as z:
        records = z.infolist()
        if not 2 <= len(records) <= 128:
            raise ValueError("archive member census")
        if sum(r.file_size for r in records) > 16_000_000:
            raise ValueError("uncompressed archive bound")
        files = {}
        for info in records:
            key = PurePosixPath(info.filename)
            if (
                key.is_absolute()
                or ".." in key.parts
                or "\\" in info.filename
                or info.is_dir()
                or stat.S_ISLNK(info.external_attr >> 16)
                or str(key) != info.filename
                or info.filename in files
            ):
                raise ValueError("unsafe archive member")
            files[info.filename] = z.read(info)
    manifest = files.get("SHA256SUMS", b"").decode("utf-8").splitlines()
    expected_names = set(files) - {"SHA256SUMS"}
    names = set()
    for line in manifest:
        m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?([^\n]+)", line)
        if m is None:
            raise ValueError("malformed complete archive manifest")
        checksum, name = m.groups()
        if name in names or name not in expected_names:
            raise ValueError("manifest duplication or extraneous member")
        names.add(name)
        if sha(files[name]) != checksum:
            raise ValueError("manifest member changed: " + name)
    if names != expected_names:
        raise ValueError("incomplete archive manifest")
    return files, len(manifest)


def json_file(files, path):
    return strict_json(files[path].decode("utf-8"))


def raw_lines(files, path):
    return [strict_json(line) for line in files[path].splitlines()]


def response_identifier(answer):
    match = IDENTIFIER.fullmatch(answer)
    return match.group(1) if match else None


def task_success(parsed, truth):
    """Reproduce the bounded program's registered *result*, not a learned judge."""
    if truth["kind"] != "procedure":
        return parsed == truth["expected"]
    recipe = truth["procedure"]
    method = recipe["modes"].get(parsed)
    if method == "sort":
        actual = sorted(recipe["values"])
    elif method == "reverse":
        actual = list(reversed(recipe["values"]))
    else:
        actual = None
    return actual is not None and actual == recipe["target"]


def chosen_sources(case, arm, k, hop):
    candidates = case["candidate_ids"]
    if native_digest(candidates) != case["candidate_digest"]:
        raise ValueError("candidate pool drift")
    controls = case.get("controls", {})
    if arm.startswith("k") and arm[1:].isdigit():
        return candidates[: int(arm[1:])]
    if arm == "selected_k":
        return candidates[:k]
    if arm == "hybrid_k4":
        return candidates[:4]
    if arm == "hybrid_k6":
        return candidates[:6]
    if arm == "hybrid_k4_reversed":
        return list(reversed(candidates[:4]))
    if arm == "single_hop":
        return hop[case["query"]["identity"]]["first_hop"]
    if arm == "empty":
        return []
    if arm not in controls:
        raise ValueError("unknown evidence selection arm")
    return controls[arm]["selected"]


def native_root_digest(root):
    raw = root.encode("utf-8")
    return sha(NATIVE_ROOT_PROFILE + len(raw).to_bytes(8, "big") + raw)


def verify_row(row, scored, case, arm, k, truth, documents, hop):
    """Re-score original answer and check the delivered source/citation trace."""
    if row != {key: value for key, value in scored.items() if key not in SCORE_FIELDS}:
        raise ValueError("scorer rewrote raw evidence, answer or model receipt")
    qid = case["query"]["identity"]
    if (row["question_id"], row["arm"], row["kind"]) != (
        qid, arm, truth["kind"]
    ):
        raise ValueError("question, arm or task kind changed")
    selected = chosen_sources(case, arm, k, hop)
    if row["selected"] != selected or len(selected) != len(set(selected)):
        raise ValueError("changed or duplicate source selection")
    if row["candidate_digest"] != case["candidate_digest"]:
        raise ValueError("changed candidate digest")
    if row["status"] != "succeeded":
        raise ValueError("missing frozen reader answer; no silent denominator loss")
    receipt = row["receipt"]
    if (
        receipt["token_limit"] != 2048
        or receipt["input_tokens"] > 2048
        or not 0 <= receipt["generated_tokens"] <= 64
        or receipt["trainable_parameters"] != 0
        or receipt["answer_postprocessed"] is not False
        or receipt["production_accepted"] is not False
        or not math.isfinite(receipt["seconds"])
        or receipt["seconds"] < 0
    ):
        raise ValueError("reader, training or budget contract changed")
    delivered = receipt["delivered_evidence"]
    if [e["original_id"] for e in delivered] != selected:
        raise ValueError("source delivery order changed")
    request = row["citation_audit"]["request"]
    if (
        request["query_id"] != qid
        or request["scope"] != case["query"]["scope"]
        or request["question"] != case["query"]["content"]
        or request["question_time"] != case["query"]["observed_at"]
        or request["answer"] != row["answer"]
        or request["prompt_digest"] != receipt["input_ids_digest"]
        or row["citation_audit"]["judgement"] is not None
    ):
        raise ValueError("citation record changed original prompt or answer")
    if len(request["sources"]) != len(delivered):
        raise ValueError("citation source census mismatch")
    by_label = {}
    for index, (source, claim) in enumerate(
        zip(delivered, request["sources"], strict=True), start=1
    ):
        doc = documents[source["original_id"]]
        if (
            doc["scope"] != case["query"]["scope"]
            or source["label"] != f"E{index}"
            or source["excerpt"] != doc["content"]
            or source["root"] != doc["root"]
            or source["source_digest"] != native_digest(doc["content"])
            or source["source_start"] != 0
            or source["source_end"] != len(doc["content"].encode("utf-8"))
            or claim != {
                "label": source["label"],
                "id": source["id"],
                "root": native_root_digest(source["root"]),
                "excerpt": source["excerpt"],
            }
        ):
            raise ValueError("source bytes or native citation binding changed")
        by_label[source["label"]] = source["original_id"]
    parsed = response_identifier(row["answer"])
    success = task_success(parsed, truth)
    coverage = set(truth["support"]).issubset(selected)
    if (
        scored["parsed_identifier"] != parsed
        or scored["strict_task_success"] is not success
        or scored["required_sources_covered"] is not coverage
    ):
        raise ValueError("original answer was mis-scored")
    if truth["kind"] == "procedure":
        recorded = scored["procedure_verification"]
        mode = truth["procedure"]["modes"].get(parsed)
        actual = (
            sorted(truth["procedure"]["values"])
            if mode == "sort"
            else list(reversed(truth["procedure"]["values"]))
            if mode == "reverse"
            else None
        )
        expected_request = {
            "operation": "execute",
            "recipe": truth["procedure"],
            "supplied": parsed or "invalid_response",
        }
        expected_stdout = json.dumps(
            {"succeeded": success, "supplied": parsed or "invalid_response",
             "actual_output": actual},
            sort_keys=True,
        ) + "\n"
        if (
            recorded["request"] != expected_request
            or recorded["stdout"] != expected_stdout
            or recorded["stderr"] != ""
            or recorded["exit_code"] != (0 if success else 2)
        ):
            raise ValueError("recorded procedure execution differs from replay")
    cited = {
        by_label[marker[1:-1]]
        for marker in MARKER.findall(row["answer"])
        if marker[1:-1] in by_label
    }
    return {
        "task_success": success,
        "source_covered": coverage,
        "correct_and_source_covered": success and coverage,
        "correct_and_full_source_cited": (
            success and set(truth["support"]).issubset(cited)
        ),
        "input_tokens": receipt["input_tokens"],
        "output_tokens": receipt["generated_tokens"],
        "reader_seconds": receipt["seconds"],
        "prompt_digest": receipt["input_ids_digest"],
        "generated_digest": receipt["generated_ids_digest"],
        "answer": row["answer"],
        "selected": selected,
        "kind": row["kind"],
    }


def summarize(rows, arms):
    result = {}
    for arm in arms:
        data = [r for r in rows if r["arm"] == arm]
        result[arm] = {
            "planned": len(data),
            "strict_task_success": sum(r["task_success"] for r in data),
            "correct_and_source_covered": sum(
                r["correct_and_source_covered"] for r in data
            ),
            "correct_and_full_source_cited": sum(
                r["correct_and_full_source_cited"] for r in data
            ),
            "input_tokens": sum(r["input_tokens"] for r in data),
            "output_tokens": sum(r["output_tokens"] for r in data),
            "reader_seconds": sum(r["reader_seconds"] for r in data),
        }
    return result


def paired(results, left, right):
    groups = defaultdict(dict)
    for row in results:
        groups[row["question_id"]][row["arm"]] = row
    wins = losses = ties = 0
    for group in groups.values():
        a, b = group[left], group[right]
        delta = int(b["task_success"]) - int(a["task_success"])
        wins += delta == 1
        losses += delta == -1
        ties += delta == 0
    return {"wins": wins, "losses": losses, "ties": ties}



def leave_one_out(rows, qids):
    """Re-select top-k on seven original calibration answers each fold."""
    grouped = defaultdict(dict)
    for row in rows:
        grouped[row["question_id"]][row["arm"]] = row
    if len(grouped) != len(qids) or set(grouped) != set(qids):
        raise ValueError("missing original calibration rows")
    folds = []
    for omit in qids:
        training = [r for r in rows if r["question_id"] != omit]
        totals = summarize(training, tuple(f"k{k}" for k in KS))
        winner = min(
            KS,
            key=lambda k: (
                -totals[f"k{k}"]["strict_task_success"],
                totals[f"k{k}"]["input_tokens"],
                k,
            ),
        )
        heldout = grouped[omit]
        first = heldout[f"k{winner}"]["task_success"]
        fixed = heldout["k4"]["task_success"]
        disposition = (
            "selected_wins" if first and not fixed else
            "selected_loses" if fixed and not first else "tie"
        )
        folds.append({
            "omitted_calibration_question": omit,
            "chosen_k_without_that_question": winner,
            "heldout_comparison": disposition,
        })
    return folds



def verify_repeats(rows):
    """Same ordered question/evidence must retain token IDs and decoded output."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row["question_id"], tuple(row["selected"]))].append(row)
    observed = answer_drift = token_drift = 0
    for repeats in groups.values():
        for first, second in combinations(repeats, 2):
            observed += 1
            if (
                first["prompt_digest"] != second["prompt_digest"]
                or first["input_tokens"] != second["input_tokens"]
            ):
                raise ValueError("same source produced changed prompt or budget")
            answer_drift += first["answer"] != second["answer"]
            token_drift += (
                first["generated_digest"] != second["generated_digest"]
            )
    return {
        "matched_prompt_pairs": observed,
        "answer_disagreements": answer_drift,
        "generated_token_disagreements": token_drift,
    }


def independent_disposition(original, reader, replay):
    o, no = archive(original, ARCHIVES["original"])
    r, nr = archive(reader, ARCHIVES["reader"])
    p, np = archive(replay, ARCHIVES["replay"])
    if (
        o["tested-commit.txt"].decode().strip() != ORIGINAL_COMMIT
        or r["tested-commit.txt"].decode().strip() != SOURCE_COMMIT
        or p["auditor-source-commit.txt"].decode().strip() != SOURCE_COMMIT
    ):
        raise ValueError("model and independent replay source ancestry changed")
    if sha(o["plan/plan.json"]) != ORIGINAL_PLAN_SHA:
        raise ValueError("original authored test plan changed")
    plan = json_file(o, "plan/plan.json")
    labels = json_file(o, "observations/labels.json")
    originals = json_file(o, "plan/source-view.json")
    if len(labels) != 16 or len(originals) != 108:
        raise ValueError("original 16-label/108-event census changed")
    source_map = {row["identity"]: row for row in originals}
    truth = {row["id"]: row for row in labels}
    if len(source_map) != 108 or len(truth) != 16:
        raise ValueError("duplicate original source or label")
    frozen = json_file(r, "calibration/frozen-policy.json")
    cal = json_file(r, "calibration/report.json")
    ev = json_file(r, "evaluation/report.json")
    receipt = json_file(p, "receipt.json")
    run = json_file(r, "evaluation/run.json")
    if (
        run["model"]["repository"] != "Qwen/Qwen2.5-3B-Instruct"
        or run["model"]["revision"]
        != "82f42baa094a9600e39ccd80d34058aeeb3abbc1"
        or receipt["formal_citation_chain"] != ev["formal_citation_chain"]
        or receipt["paired_contrasts"] != ev["paired_contrasts"]
        or receipt["same_prompt_consistency"] != ev["same_prompt_consistency"]
    ):
        raise ValueError("reader revision or independent replay summary drift")
    if (
        frozen["source_commit"] != SOURCE_COMMIT
        or frozen["original_test_plan_sha256"] != ORIGINAL_PLAN_SHA
        or frozen["selected_k"] not in KS
        or cal["source_commit"] != SOURCE_COMMIT
        or ev["source_commit"] != SOURCE_COMMIT
        or receipt["generating_commit"] != SOURCE_COMMIT
        or receipt["model_identity"] != frozen["reader_identity"]
        or frozen["candidate_accepted"] is not False
        or frozen["production_accepted"] is not False
        or ev["production_accepted"] is not False
        or receipt["production_accepted"] is not False
    ):
        raise ValueError("model, policy, source or admission identity drift")
    cal_plan = json_file(r, "prep/calibration-plan.json")
    calibration_cases = cal_plan["cases"]
    test_cases = plan["cases"]
    cal_ids = [case["query"]["identity"] for case in calibration_cases]
    test_ids = [case["query"]["identity"] for case in test_cases]
    if (
        len(cal_ids) != 8
        or len(test_ids) != 8
        or set(cal_ids) & set(test_ids)
        or set(cal_ids) | set(test_ids) != set(truth)
        or set(cal_plan["frozen_indices"]) != set(cal_ids)
    ):
        raise ValueError("held-out scope or calibration partition changed")
    hop_cases = json_file(r, "evaluation/single-hop-control.json")["test_cases"]
    hops = {h["question_id"]: h for h in hop_cases}
    if len(hops) != 8 or set(hops) != set(test_ids):
        raise ValueError("single-hop frozen census missing")
    derived = {}
    detail = {}
    for phase, cases, arms in (
        ("calibration", calibration_cases, tuple(f"k{k}" for k in KS)),
        ("evaluation", test_cases, ARMS),
    ):
        original_rows = raw_lines(r, phase + "/raw-answers.jsonl")
        scored_rows = json_file(r, phase + "/scored-answers.json")
        n = len(cases) * len(arms)
        if len(original_rows) != n or len(scored_rows) != n:
            raise ValueError("missing 40/72 original generation census")
        expected = [
            (case["query"]["identity"], arm)
            for case in cases
            for arm in arms
        ]
        actual = [(row["question_id"], row["arm"]) for row in original_rows]
        if actual != expected or actual != [
            (row["question_id"], row["arm"]) for row in scored_rows
        ]:
            raise ValueError("raw or scored answer order/identity changed")
        totals = []
        for raw, scored, (qid, arm) in zip(
            original_rows, scored_rows, expected, strict=True
        ):
            case = next(c for c in cases if c["query"]["identity"] == qid)
            state = verify_row(
                raw, scored, case, arm, frozen["selected_k"],
                truth[qid], source_map, hops,
            )
            totals.append({"question_id": qid, "arm": arm, **state})
        summary = summarize(totals, arms)
        original_summary = (
            cal["arms"] if phase == "calibration" else ev["success_by_arm"]
        )
        for arm in arms:
            s, archived = summary[arm], original_summary[arm]
            if (
                s["strict_task_success"] != archived["strict_success"]
                or s["input_tokens"] != archived["input_tokens"]
                or s["output_tokens"] != archived["output_tokens"]
                or not math.isclose(
                    s["reader_seconds"], archived["inference_seconds"],
                    rel_tol=1e-10, abs_tol=1e-8,
                )
            ):
                raise ValueError("archived task effect or cost differs from raw")
        if phase == "calibration":
            winner = min(
                KS,
                key=lambda k: (
                    -summary[f"k{k}"]["strict_task_success"],
                    summary[f"k{k}"]["input_tokens"], k,
                ),
            )
            if winner != frozen["selected_k"] or winner != cal["frozen_k"]:
                raise ValueError("frozen top-k cannot be reproduced")
            folds = leave_one_out(totals, cal_ids)
            recorded = cal["calibration_sensitivity"]
            if (
                folds != recorded["folds"]
                or Counter(f["chosen_k_without_that_question"] for f in folds)
                != Counter({
                    int(k): v for k, v in recorded["chosen_k_counts"].items()
                    if v > 0
                })
            ):
                raise ValueError("leave-one-out calibration attribution changed")
        else:
            observed_repeats = verify_repeats(totals)
            published_repeats = ev["same_prompt_consistency"]
            if (
                observed_repeats["matched_prompt_pairs"]
                != published_repeats["observed_identical_prompt_pairs"]
                or observed_repeats["answer_disagreements"]
                != len(published_repeats["answer_disagreements"])
                or observed_repeats["generated_token_disagreements"]
                != len(published_repeats["output_token_disagreements"])
            ):
                raise ValueError("same-prompt repeatability cannot be reproduced")
            form = ev["formal_citation_chain"]["by_arm"]
            for arm in arms:
                if (
                    summary[arm]["correct_and_full_source_cited"]
                    != form[arm]["correct_with_full_program_declared_citations"]
                ):
                    raise ValueError("published citation count cannot be reproduced")
            for left, right, name in (
                ("hybrid_k4", "selected_k", "selected_minus_hybrid4"),
                ("single_hop", "entity_time", "entity_time_minus_single_hop"),
                ("entity_time", "organized", "organized_minus_entity_time"),
            ):
                observed = paired(totals, left, right)
                if any(
                    observed[k] != ev["paired_contrasts"][name][k]
                    for k in ("wins", "losses", "ties")
                ):
                    raise ValueError("published paired effect differs from raw")
            detail = {
                "replayed_paired_effects": {
                    name: paired(totals, left, right)
                    for left, right, name in (
                        ("hybrid_k4", "selected_k", "selected_minus_hybrid4"),
                        ("single_hop", "entity_time", "entity_time_minus_single_hop"),
                        ("entity_time", "organized", "organized_minus_entity_time"),
                    )
                },
                "identical_input_repeatability": observed_repeats,
                "model_task_independent_semantic_review": False,
            }
        derived[phase] = {
            "attempts": n,
            "all_generated": True,
            "arms": summary,
            "raw_sha256": sha(r[phase + "/raw-answers.jsonl"]),
        }
        if derived[phase]["raw_sha256"] != receipt[phase]["original_raw_sha256"]:
            raise ValueError("independent replay and original answer journal differ")
        if (
            receipt[phase]["attempts"] != n
            or not receipt[phase]["all_model_calls_succeeded"]
        ):
            raise ValueError("independent replay omitted original model calls")
    if len(derived) != 2 or derived["calibration"]["attempts"] != 40:
        raise ValueError("calibration answer census")
    eval_arms = derived["evaluation"]["arms"]
    selected = eval_arms["selected_k"]
    organized = eval_arms["organized"]
    simple = eval_arms["entity_time"]
    if (
        ev["total_attempts"] != 72
        or receipt["evaluation"]["attempts"] != 72
        or ev["independent_source_family_count"] != 0
    ):
        raise ValueError("false prospective claim or incomplete evaluation")
    return {
        "schema": "hepta.memory-cell.archived-qwen-disposition.v1",
        "generating_run_id": 38224780900,
        "generating_commit": SOURCE_COMMIT,
        "artifacts_sha256": dict(ARCHIVES),
        "artifact_manifest_file_counts": {
            "original": no, "reader": nr, "replay": np,
        },
        "model": "Qwen2.5-3B-Instruct / pinned revision / research-only",
        "model_training_executed": False,
        "reader_identity": frozen["reader_identity"],
        "selected_k": frozen["selected_k"],
        "calibration_replayed": derived["calibration"],
        "evaluation_replayed": derived["evaluation"],
        **detail,
        "observations": {
            "calibrated_rag_minus_hybrid4_task_wins": (
                selected["strict_task_success"]
                - eval_arms["hybrid_k4"]["strict_task_success"]
            ),
            "calibrated_rag_correct_without_full_support": (
                selected["strict_task_success"]
                - selected["correct_and_source_covered"]
            ),
            "full_path_minus_single_hop_task_wins": (
                simple["strict_task_success"]
                - eval_arms["single_hop"]["strict_task_success"]
            ),
            "organized_minus_full_path_task_wins": (
                organized["strict_task_success"]
                - simple["strict_task_success"]
            ),
            "organized_input_token_saving_vs_full_path": (
                simple["input_tokens"] - organized["input_tokens"]
            ),
            "organized_correct_without_full_chain_citation": (
                organized["strict_task_success"]
                - organized["correct_and_full_source_cited"]
            ),
        },
        "calibration_loo_stable": cal["calibration_sensitivity"][
            "stable_to_one_calibration_case_removal"
        ],
        "independent_future_source_families": 0,
        "independent_semantic_entailment_adjudication": False,
        "total_deployed_lifecycle_cost_established": False,
        "parametric_memory_gain_established": False,
        "memory_cell_learning_promotion_qualified": False,
        "production_accepted": False,
        "interpretation": (
            "Actual 40+72 frozen Qwen calls and separate-process replay succeeded; "
            "only eight exposed authored tasks. Grounded attribution, prospective "
            "transfer, semantic entailment and lifecycle cost remain unqualified."
        ),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("reader", type=Path)
    parser.add_argument("replay", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = independent_disposition(args.original, args.reader, args.replay)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {"source": SOURCE_COMMIT, "verified_calls": 112,
             "selected_k": report["selected_k"],
             "production_accepted": report["production_accepted"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
