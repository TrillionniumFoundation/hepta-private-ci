"""Actual frozen-Reader case-1 distractor factorial; POST-OBSERVATION study.

Eight original evidence subsets, all retain the author-declared support ID.
This is a development diagnostic selected after the Smol case-1 result, NOT a
preregistered prospective sample or any trained/parametric-memory gain.
Original generation never opens observations/labels.json. No answer rewrite.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from io import BytesIO
import zipfile

SCHEMA = "hepta.memory-cell.reader-case1-posthoc-factorial.v1"
SOURCE_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
ORIGINAL_GENERATOR = "5b0dead3b766bdc5e56c09e024a8f82c50ccbdd6"
ORIGINAL_OBSERVATION = 11892028435
CASE_INDEX = 1
QUESTION_ID = "controlled_cbfd4ba5"
SUPPORT = "event_cbfd4ba5_2"
HYBRID = (
    "event_cbfd4ba5_1",
    "event_cbfd4ba5_2",
    "event_cbfd4ba5_4",
    "event_cbfd4ba5_5",
)
OPTIONAL = tuple(key for key in HYBRID if key != SUPPORT)
TIERS = ("smol-1.7b", "qwen-3b")
IDENTITIES = {
    "smol-1.7b": "78ad24ab45f9620ada47df17a7de446f24ab4082fb993dd143ee30fce422acec",
    "qwen-3b": "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225",
}
ARMS = tuple(f"support_plus_{mask:03b}" for mask in range(8))
SHA = re.compile(r"[0-9a-f]{64}\Z")
SHA_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
FROZEN_INPUT = "hepta.controlled-event.schema-expansion.v1"


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def strict_json(data):
    def no_duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate original JSON field")
            result[key] = value
        return result

    def not_numeric_constant(value):
        raise ValueError("nonfinite original JSON: " + value)

    return json.loads(
        data, object_pairs_hook=no_duplicate, parse_constant=not_numeric_constant
    )


def selections():
    """Frozen mask => original Hybrid rank-order subset, never target-driven."""
    output = {}
    for mask in range(8):
        included = {SUPPORT} | {
            OPTIONAL[index] for index in range(3) if mask & (1 << index)
        }
        output[ARMS[mask]] = tuple(source for source in HYBRID if source in included)
    if (
        len(set(output.values())) != 8
        or output[ARMS[0]] != (SUPPORT,)
        or output[ARMS[-1]] != HYBRID
        or any(SUPPORT not in ids for ids in output.values())
    ):
        raise ValueError("frozen post-observation distractor factorial drift")
    return output


def registered_plan(case, originals):
    """No gold labels. Public plan and original bytes predate this diagnostic."""
    from native import digest

    lookup = case["query"]
    selection = selections()
    if (
        lookup["identity"] != QUESTION_ID
        or lookup["scope"] != QUESTION_ID
        or case["kind"] != "correction"
        or list(case["controls"]["program_support"]["selected"]) != [SUPPORT]
        or tuple(case["controls"]["hybrid"]["selected"]) != HYBRID
        or tuple(case["candidate_ids"][:4]) != HYBRID
        or digest(tuple(case["candidate_ids"])) != case["candidate_digest"]
        or any(key not in originals for key in HYBRID)
        or any(originals[key].scope != QUESTION_ID for key in HYBRID)
    ):
        raise ValueError("frozen original case-1 public task mismatch")
    return dict(
        schema=SCHEMA,
        original_source_zip_sha256=SOURCE_SHA,
        original_authored_plan_sha256=PLAN_SHA,
        originally_observed_model_commit=ORIGINAL_GENERATOR,
        originally_observed_model_artifact=ORIGINAL_OBSERVATION,
        case_id=QUESTION_ID,
        case_index=CASE_INDEX,
        kind="correction",
        candidate_digest=case["candidate_digest"],
        frontier_digest=digest(case["frontier"]),
        eight_arms=list(ARMS),
        masks={arm: list(keys) for arm, keys in selection.items()},
        observed_then_registered=True,
        one_authored_development_task=True,
        independent_source_family_count=0,
        author_declared_support_not_human_reviewed=True,
        frozen_reader_no_parameter_update=True,
        exact_reader_prompt_decoder_unchanged=True,
        target_labels_exposed=False,
        original_80_call_matrix_membership=False,
        production_accepted=False,
    )


def freeze(plan_dir):
    from reader_bottleneck_ablation import _plan

    plan, originals = _plan(plan_dir)
    if len(plan["cases"]) != 8 or plan["cases"][CASE_INDEX]["query"]["identity"] != QUESTION_ID:
        raise ValueError("case index changed in original frozen plan")
    case = plan["cases"][CASE_INDEX]
    return case, originals, selections(), registered_plan(case, originals)


def store(path, obj):
    from strong_rag_trial import dump

    dump(path, obj)


def generate(plan_dir, model_dir, output, *, tier, stage_sha):
    """Load genuine immutable BF16 Reader; flush all 8 raw generated responses."""
    from event_memory_trial import read
    from event_reader_view import EventPresentationReader
    from native import digest
    from reader_bottleneck_ablation import _journal_with_guard
    from reader_reference import MODELS
    from runtime_preflight import capture_runtime, configure_torch
    from strong_rag_trial import file_sha
    import torch

    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not SHA_COMMIT.fullmatch(commit) or tier not in TIERS or not SHA.fullmatch(stage_sha):
        raise ValueError("unregistered generator SHA/Reader tier/model seal")
    case, originals, mask, fixed = freeze(plan_dir)
    output.mkdir()
    store(output / "case-plan.json", fixed)
    stage = read(model_dir / "stage.json", stage_sha)
    model = read(model_dir / "inventory.json", stage["inventory_sha256"])
    if (
        stage["tier"] != tier
        or stage["revision"] != MODELS[tier][1]
        or model["repository"] != MODELS[tier][0]
        or model["revision"] != MODELS[tier][1]
        or model["inventory_digest"] != IDENTITIES[tier]
    ):
        raise ValueError("frozen Reader weights/inventory do not match original")
    threading = configure_torch(torch, bounded=False)
    if threading["effective_intra_op"] != 2:
        raise ValueError("Reader CPU original thread budget changed")
    reader = EventPresentationReader(
        model_dir / "reader", expected_inventory=IDENTITIES[tier]
    )
    store(output / "runtime-preflight.json", capture_runtime(torch, bounded=False))
    rows = _journal_with_guard(
        reader,
        [case],
        originals,
        ARMS,
        lambda _case, arm: mask[arm],
        output / "raw-answers.jsonl",
        seed=digest((PLAN_SHA, commit, tier, SCHEMA)),
    )
    store(
        output / "run.json",
        dict(
            schema=SCHEMA,
            generating_commit=commit,
            original_80_call_matrix_membership=False,
            case_index=CASE_INDEX,
            model_tier=tier,
            reader_identity=IDENTITIES[tier],
            original_authored_plan_sha256=PLAN_SHA,
            case_plan_sha256=file_sha(output / "case-plan.json"),
            stage_sha256=stage_sha,
            runtime_preflight_sha256=file_sha(output / "runtime-preflight.json"),
            raw_journal_sha256=file_sha(output / "raw-answers.jsonl"),
            attempts=len(rows),
            succeeded=sum(row["status"] == "succeeded" for row in rows),
            arms=list(ARMS),
            learned_parameters=0,
            posthoc_development_diagnostic=True,
            target_labels_exposed=False,
            production_accepted=False,
        ),
    )
    if len(rows) != 8 or any(row["status"] != "succeeded" for row in rows):
        raise ValueError("original failed attempts retained; no full 8-arm result")
    return 8


def check_rows(files, *, tier, case, originals, expected_commit):
    """Audit raw journal, not scored copies or regenerated/decorated answers."""
    from native import digest

    if tier not in TIERS or not SHA_COMMIT.fullmatch(expected_commit):
        raise ValueError("exact generating identity required")
    frozen = registered_plan(case, originals)
    if "case-plan.json" not in files:
        if "raw-answers.jsonl" in files or "run.json" in files:
            raise ValueError("model answer present without frozen case plan")
        return dict(tier=tier, attempted=0, succeeded=0, complete=False)
    if strict_json(files["case-plan.json"]) != frozen:
        raise ValueError("original case plan changed after registration")
    raw = files.get("raw-answers.jsonl")
    if raw is None:
        if "run.json" in files:
            raise ValueError("run seal exists with no original model journal")
        return dict(tier=tier, attempted=0, succeeded=0, complete=False)
    if not raw.endswith(b"\n"):
        raise ValueError("original journal not newline sealed")
    rows = [strict_json(line) for line in raw.splitlines()]
    if not 1 <= len(rows) <= len(ARMS):
        raise ValueError("bounded exact posthoc answer count required")
    selection = selections()
    for arm, row in zip(ARMS, rows, strict=False):
        if (
            row.get("question_id") != QUESTION_ID
            or row.get("kind") != "correction"
            or row.get("arm") != arm
            or row.get("candidate_digest") != case["candidate_digest"]
            or row.get("selected") != list(selection[arm])
            or row.get("status") not in ("succeeded", "failed")
            or "strict_task_success" in row
            or "parsed_identifier" in row
        ):
            raise ValueError("unexpected arm/selection or premature label exposure")
        if row["status"] == "failed":
            continue
        receipt = row.get("receipt")
        if (
            not isinstance(receipt, dict)
            or receipt.get("reader_identity") != IDENTITIES[tier]
            or receipt.get("view_profile") != FROZEN_INPUT
            or receipt.get("query_digest") != digest(case["query"])
            or receipt.get("omitted_evidence_bytes") != 0
            or not isinstance(receipt.get("derived_evidence"), list)
            or receipt.get("derived_view_digest")
            != digest(receipt.get("derived_evidence", None))
            or receipt.get("token_limit") != 2048
            or receipt.get("trainable_parameters") != 0
            or receipt.get("answer_postprocessed") is not False
            or receipt.get("production_accepted") is not False
            or type(receipt.get("input_tokens")) is not int
            or not 0 < receipt["input_tokens"] <= 2048
            or type(receipt.get("generated_tokens")) is not int
            or not 0 < receipt["generated_tokens"] <= 64
            or any(not SHA.fullmatch(str(receipt.get(name))) for name in (
                "input_ids_digest", "generated_ids_digest", "reader_profile"
            ))
            or not isinstance(row.get("answer"), str)
            or not row["answer"].strip()
        ):
            raise ValueError("missing real frozen Reader/decoding receipt")
        if (
            type(receipt.get("seconds")) not in (int, float)
            or not math.isfinite(receipt["seconds"])
            or receipt["seconds"] < 0
        ):
            raise ValueError("unbounded original model latency")
        delivered = receipt.get("delivered_evidence")
        if (
            not isinstance(delivered, list)
            or [x.get("original_id") for x in delivered] != list(selection[arm])
        ):
            raise ValueError("Reader received unregistered original source IDs")
        for source in delivered:
            doc = originals[source["original_id"]]
            if source.get("excerpt") != doc.content or source.get("scope") != QUESTION_ID:
                raise ValueError("delivered evidence bytes differ from frozen source")
        citation = row.get("citation_audit")
        if (
            not isinstance(citation, dict)
            or not isinstance(citation.get("request"), dict)
            or citation["request"].get("query_id") != QUESTION_ID
            or citation["request"].get("prompt_digest")
            != receipt["input_ids_digest"]
            or citation["request"].get("answer") != row["answer"]
            or citation.get("semantic_precision") is not None
            or citation.get("production_accepted") is not False
        ):
            raise ValueError("citation receipt is not original unreviewed evidence")
    run = files.get("run.json")
    if run is not None:
        sealed = strict_json(run)
        if (
            sealed.get("schema") != SCHEMA
            or sealed.get("generating_commit") != expected_commit
            or sealed.get("case_index") != CASE_INDEX
            or sealed.get("model_tier") != tier
            or sealed.get("reader_identity") != IDENTITIES[tier]
            or sealed.get("original_authored_plan_sha256") != PLAN_SHA
            or sealed.get("case_plan_sha256") != digest_bytes(files["case-plan.json"])
            or not isinstance(files.get("runtime-preflight.json"), bytes)
            or sealed.get("runtime_preflight_sha256")
            != digest_bytes(files["runtime-preflight.json"])
            or sealed.get("raw_journal_sha256") != digest_bytes(raw)
            or sealed.get("attempts") != len(rows)
            or sealed.get("original_80_call_matrix_membership") is not False
            or sealed.get("succeeded") != sum(x["status"] == "succeeded" for x in rows)
            or sealed.get("arms") != list(ARMS)
            or sealed.get("learned_parameters") != 0
            or sealed.get("target_labels_exposed") is not False
            or sealed.get("production_accepted") is not False
        ):
            raise ValueError("run SHA or original attempt count changed")
    complete = (
        run is not None
        and len(rows) == len(ARMS)
        and all(r["status"] == "succeeded" for r in rows)
    )
    counts = dict(
        tier=tier,
        attempted=len(rows),
        succeeded=sum(row["status"] == "succeeded" for row in rows),
        complete=complete,
        observed_inference_seconds=sum(
            row["receipt"]["seconds"]
            for row in rows if row["status"] == "succeeded"
        ),
        input_tokens=sum(
            row["receipt"]["input_tokens"]
            for row in rows if row["status"] == "succeeded"
        ),
        generated_tokens=sum(
            row["receipt"]["generated_tokens"]
            for row in rows if row["status"] == "succeeded"
        ),
        per_arm=[
            dict(
                arm=row["arm"],
                selected=row["selected"],
                status=row["status"],
                answer_sha256=digest_bytes(row["answer"].encode())
                if row["status"] == "succeeded" else None,
                original_answer=row.get("answer"),
            )
            for row in rows
        ],
    )
    return counts


def checked_zip(path, *, outer_sha):
    """Reject unsigned ZIPs, duplicate members, symlinks, path traversal."""
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 16 * 1024 * 1024
        or not SHA.fullmatch(outer_sha)
    ):
        raise ValueError("original artifact path/size/SHA invalid")
    data = path.read_bytes()
    if digest_bytes(data) != outer_sha:
        raise ValueError("external original Actions SHA256 mismatch")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        files = {}
        for entry in archive.infolist():
            if (
                entry.filename in files
                or entry.is_dir()
                or stat.S_ISLNK(entry.external_attr >> 16)
                or re.fullmatch(r"[A-Za-z0-9_.-]+", entry.filename) is None
                or entry.file_size > 8 * 1024 * 1024
                or len(files) >= 16
            ):
                raise ValueError("unsafe original Reader shard ZIP member")
            files[entry.filename] = archive.read(entry)
    if "SHA256SUMS" not in files:
        raise ValueError("missing inner manifest")
    pins = {}
    for line in files["SHA256SUMS"].decode().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?([A-Za-z0-9_.-]+)", line)
        if match is None or match[2] in pins or match[2] == "SHA256SUMS":
            raise ValueError("unsafe/duplicate original manifest row")
        pins[match[2]] = match[1]
    if set(pins) != set(files) - {"SHA256SUMS"} or any(
        digest_bytes(files[name]) != val for name, val in pins.items()
    ):
        raise ValueError("altered or unregistered inner ZIP member")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    v = sub.add_parser("validate")
    v.add_argument("plan_dir", type=Path)
    v.add_argument("report", type=Path)
    g = sub.add_parser("generate")
    g.add_argument("plan_dir", type=Path)
    g.add_argument("model_dir", type=Path)
    g.add_argument("result_dir", type=Path)
    g.add_argument("--tier", choices=TIERS, required=True)
    g.add_argument("--stage-sha", required=True)
    a = sub.add_parser("audit")
    a.add_argument("source_plan_dir", type=Path)
    a.add_argument("artifact_zip", type=Path)
    a.add_argument("report", type=Path)
    a.add_argument("--outer-sha", required=True)
    a.add_argument("--tier", choices=TIERS, required=True)
    a.add_argument("--generating-commit", required=True)
    args = parser.parse_args()
    if args.mode == "validate":
        _, _, _, fixed = freeze(args.plan_dir)
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(fixed, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        return
    if args.mode == "generate":
        generate(
            args.plan_dir, args.model_dir, args.result_dir,
            tier=args.tier, stage_sha=args.stage_sha,
        )
        return
    case, originals, _, _ = freeze(args.source_plan_dir)
    files = checked_zip(args.artifact_zip, outer_sha=args.outer_sha)
    if files.get("checkout-commit.txt", b"").decode().strip() != args.generating_commit:
        raise ValueError("model shard source commit changed")
    host = strict_json(files["host-gate.json"])
    if (
        host.get("schema") != "hepta.memory-strong-rag.bf16-host-gate.v1"
        or host.get("new_model_calls") != 0
        or host.get("production_accepted") is not False
        or type(host.get("host_eligible")) is not bool
        or (not host["host_eligible"] and "raw-answers.jsonl" in files)
        or (host["host_eligible"] and
            (host.get("all_cpus_bf16_accelerated") is not True or
             host.get("machine") != "x86_64" or
             not host.get("shared_acceleration_features")))
    ):
        raise ValueError("unqualified source-machine attestation")
    audited = check_rows(
        files, tier=args.tier, case=case, originals=originals,
        expected_commit=args.generating_commit,
    )
    audited.update(
        schema=SCHEMA,
        externally_pinned_outer_zip_sha256=args.outer_sha,
        model_generating_commit=args.generating_commit,
        host_eligible=host["host_eligible"],
        human_sufficiency_reviewed=False,
        original_trial_80_calls_completed=False,
        prospective_new_family=False,
        post_observation_dev_only=True,
        trained_memory_gain=None,
        production_accepted=False,
    )
    with args.report.open("x", encoding="utf-8") as out:
        json.dump(audited, out, indent=2, sort_keys=True, allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
