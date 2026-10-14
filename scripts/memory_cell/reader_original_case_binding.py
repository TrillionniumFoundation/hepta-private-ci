"""Bind an externally SHA-attested Reader shard to the immutable public task plan.

No target labels, model calls, scoring, training or semantic-review claims. A
partial raw answer is counted as evidence of a model attempt only when its
source IDs, source bytes, reader identity and input receipt agree with the
before-generation authored plan. Token IDs themselves are not replayed here.
"""

import hashlib
import json
import math
from pathlib import Path
import re
import zipfile

SOURCE_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
GENERATING_PARENT = "bc76ac57ba972bf105c71ddd997cd215cec5df2e"
SCHEMA = "hepta.memory-cell.reader-bottleneck-original.v1"
VIEW = "hepta.controlled-event.schema-expansion.v1"
IDENTITIES = {
    "smol-1.7b": "78ad24ab45f9620ada47df17a7de446f24ab4082fb993dd143ee30fce422acec",
    "qwen-3b": "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225",
}
ARMS = ("none", "selected_k", "hybrid_k4", "declared_support", "minus_one")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")


def h(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return h(json.dumps(value, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")).encode("utf-8"))


def strict(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate original JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite original JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def open_public_plan(source_zip):
    """Parse only target-free plan/source view; hash every original ZIP member."""
    path = Path(source_zip)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError("missing or oversized source ZIP")
    if h(path.read_bytes()) != SOURCE_SHA:
        raise ValueError("not the original source artifact")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 36 or len(set(names)) != len(names):
            raise ValueError("original source ZIP member census changed")
        if set(("SHA256SUMS", "plan/plan.json", "plan/source-view.json")) - set(names):
            raise ValueError("original source plan or manifest missing")
        sums = {}
        for line in archive.read("SHA256SUMS").decode("ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?([A-Za-z0-9_.\-/]+)", line)
            if match is None or match[2] in sums or match[2] == "SHA256SUMS":
                raise ValueError("source manifest drift")
            sums[match[2]] = match[1]
        if set(sums) != set(names) - {"SHA256SUMS"}:
            raise ValueError("source manifest incomplete")
        for key, expected in sums.items():
            if h(archive.read(key)) != expected:
                raise ValueError("original source byte drift")
        plan_data = archive.read("plan/plan.json")
        if h(plan_data) != PLAN_SHA:
            raise ValueError("original authored plan SHA drift")
        plan = strict(plan_data)
        source_data = archive.read("plan/source-view.json")
        if h(source_data) != plan["source_view_sha"]:
            raise ValueError("source-view content not bound to plan")
        docs = strict(source_data)
    if (
        plan.get("schema") != "hepta.event-organization.plan.v1"
        or plan.get("token_limit") != 2048
        or plan.get("independent_human_review") is not False
        or len(plan.get("cases", [])) != 8
        or len({x["query"]["identity"] for x in plan["cases"]}) != 8
        or len(docs) != len({doc["identity"] for doc in docs})
    ):
        raise ValueError("unregistered authored development population")
    return plan, {doc["identity"]: doc for doc in docs}


def frozen_case(case, docs, index):
    ids = case["candidate_ids"]
    if len(set(ids)) != len(ids) or not 4 <= len(ids) <= 32:
        raise ValueError("changed candidate cardinality")
    if digest(ids) != case["candidate_digest"]:
        raise ValueError("changed source candidate digest")
    controls = case["controls"]
    support = list(controls["program_support"]["selected"])
    if (
        not 1 <= len(support) <= 8
        or len(set(support)) != len(support)
        or controls["hybrid"]["selected"] != ids[:4]
        or controls["without_prerequisite"]["selected"] != support[1:]
        or controls["empty"]["selected"] != []
        or not set(support + ids).issubset(docs)
    ):
        raise ValueError("changed pre-registered evidence selection")
    expected = {
        "none": [],
        "selected_k": ids[:1],
        "hybrid_k4": ids[:4],
        "declared_support": support,
        "minus_one": support[1:],
    }
    return dict(
        schema=SCHEMA,
        original_plan_sha256=PLAN_SHA,
        original_generation=GENERATING_PARENT,
        case_index=index,
        case_id=case["query"]["identity"],
        kind=case["kind"],
        candidate_digest=case["candidate_digest"],
        frontier_digest=digest(case["frontier"]),
        critical_declared_id=support[0],
        arms=expected,
        declared_support_not_human_reviewed=True,
        public_authored_development=True,
        selected_k_originally_frozen=1,
        target_labels_exposed=False,
        independent_semantic_review=False,
        production_accepted=False,
    )


def bind_shard(files, *, tier, index, plan, docs):
    """Validate each original inference attempt without opening any gold file."""
    if tier not in IDENTITIES or type(index) is not int or not 0 <= index < 8:
        raise ValueError("unknown Reader tier or authored task index")
    case = plan["cases"][index]
    expected = frozen_case(case, docs, index)
    if "case-plan.json" not in files or strict(files["case-plan.json"]) != expected:
        raise ValueError("shard case plan differs from original public frozen plan")
    if "runtime-preflight.json" in files:
        runtime = strict(files["runtime-preflight.json"])
        torch = runtime.get("torch", {})
        if (
            runtime.get("schema") != "hepta.memory.runtime-preflight.v1"
            or torch.get("version") != "2.5.1+cpu"
            or torch.get("intra_op_threads") != 2
        ):
            raise ValueError("CPU inference runtime is not pinned")
    raw = files.get("raw-answers.jsonl")
    if raw is None:
        if "run.json" in files:
            raise ValueError("a run receipt cannot exist without an answer journal")
        return dict(tier=tier, case_index=index, rows=0, succeeded=0,
                    full_original_pair=False, exact_source_bound=True)
    if not raw.endswith(b"\n"):
        raise ValueError("non-terminated original journal")
    rows = [strict(line) for line in raw.splitlines()]
    if not 1 <= len(rows) <= len(ARMS):
        raise ValueError("unbounded original journal")
    for position, row in enumerate(rows):
        arm = ARMS[position]
        if (
            row.get("question_id") != expected["case_id"]
            or row.get("kind") != expected["kind"]
            or row.get("candidate_digest") != expected["candidate_digest"]
            or row.get("arm") != arm
            or row.get("selected") != expected["arms"][arm]
            or row.get("status") not in ("succeeded", "failed")
        ):
            raise ValueError("journal row is not an original frozen task/arm")
        if row["status"] != "succeeded":
            continue
        receipt = row.get("receipt")
        if not isinstance(receipt, dict):
            raise ValueError("missing original model inference receipt")
        if (
            receipt.get("reader_identity") != IDENTITIES[tier]
            or receipt.get("view_profile") != VIEW
            or receipt.get("query_digest") != digest(case["query"])
            or receipt.get("token_limit") != 2048
            or type(receipt.get("input_tokens")) is not int
            or not 0 < receipt["input_tokens"] <= 2048
            or type(receipt.get("generated_tokens")) is not int
            or not 0 < receipt["generated_tokens"] <= 64
            or receipt.get("trainable_parameters") != 0
            or receipt.get("answer_postprocessed") is not False
            or receipt.get("independent_semantic_review") is not False
            or receipt.get("semantic_citation_precision") is not None
            or receipt.get("production_accepted") is not False
            or not isinstance(row.get("answer"), str)
            or not row["answer"].strip()
            or not isinstance(receipt.get("seconds"), (int, float))
            or not math.isfinite(receipt["seconds"])
            or receipt["seconds"] < 0
            or any(SHA64.fullmatch(str(receipt.get(name))) is None
                   for name in ("reader_profile", "input_ids_digest", "generated_ids_digest"))
        ):
            raise ValueError("unqualified frozen Reader model/prompt/output receipt")
        provided = receipt.get("delivered_evidence")
        if not isinstance(provided, list) or [p.get("original_id") for p in provided] != row["selected"]:
            raise ValueError("delivered evidence IDs differ from frozen selection")
        for source in provided:
            doc = docs.get(source["original_id"])
            if (
                doc is None or doc["scope"] != case["query"]["scope"]
                or source.get("excerpt") != doc["content"]
            ):
                raise ValueError("source excerpt differs from original immutable content")
        citation = row.get("citation_audit", {})
        request = citation.get("request", {}) if isinstance(citation, dict) else {}
        if (
            not isinstance(request, dict)
            or request.get("query_id") != expected["case_id"]
            or request.get("prompt_digest") != receipt["input_ids_digest"]
            or request.get("answer") != row["answer"]
            or citation.get("semantic_precision") is not None
            or citation.get("production_accepted") is not False
        ):
            raise ValueError("literal answer/citation request provenance changed")
    full = len(rows) == len(ARMS) and all(r["status"] == "succeeded" for r in rows)
    if "run.json" in files:
        execution = strict(files["run.json"])
        if (
            len(rows) != len(ARMS)
            or execution.get("schema") != SCHEMA
            or execution.get("case_index") != index
            or execution.get("tier") != tier
            or execution.get("reader_identity") != IDENTITIES[tier]
            or execution.get("raw_sha256") != h(raw)
            or execution.get("attempts") != len(ARMS)
            or execution.get("actual_successes") != sum(
                row["status"] == "succeeded" for row in rows
            )
            or execution.get("case_plan_sha256") != h(files["case-plan.json"])
            or execution.get("production_accepted") is not False
        ):
            raise ValueError("complete journal and run receipt not synchronized")
    elif full:
        raise ValueError("five successful answers without a complete run receipt")
    return dict(tier=tier, case_index=index, rows=len(rows),
                succeeded=sum(r["status"] == "succeeded" for r in rows),
                full_original_pair=full, exact_source_bound=True)


def audit_attested_shards(source_zip, attestation, archive_dir):
    """Add exact public task/model/answer checks to an externally rooted ZIP audit."""
    from reader_external_artifact_audit import checked_archive

    if (
        attestation.get("schema") !=
        "hepta.memory-cell.reader-external-artifact-audit.v1"
        or attestation.get("github_outer_zip_sha256_verified") is not True
        or attestation.get("all_original_inner_sha256sums_verified") is not True
        or attestation.get("original_run_and_source_bound") is not True
        or attestation.get("production_accepted") is not False
        or attestation.get("new_model_calls_by_this_audit") != 0
        or len(attestation.get("shards", [])) != attestation.get("github_artifact_count")
        or attestation.get("github_artifact_count", 0) > 16
    ):
        raise ValueError("not an external-root SHA-audited original shard census")
    plan, docs = open_public_plan(source_zip)
    entries, identities = [], set()
    for item in attestation["shards"]:
        if not SHA64.fullmatch(item.get("github_zip_sha256", "")):
            raise ValueError("unbound external GitHub ZIP digest")
        aid = item.get("artifact_id")
        if type(aid) is not int or aid <= 0 or aid in identities:
            raise ValueError("duplicate or nonexistent original artifact ID")
        identities.add(aid)
        filename = archive_dir / f"artifact-{aid}.zip"
        if filename.is_symlink() or not filename.is_file():
            raise ValueError("external artifact ZIP missing")
        raw = filename.read_bytes()
        files = checked_archive(raw, dict(bytes=len(raw), sha256=item["github_zip_sha256"]))
        tier, index = item.get("tier"), item.get("case_index")
        if (
            tier not in IDENTITIES or type(index) is not int or not 0 <= index < 8
            or item.get("artifact_name") != f"memory-reader-bottleneck-{tier}-{index}"
        ):
            raise ValueError("external Reader shard name/case binding changed")
        if "case-plan.json" not in files:
            if item.get("outcome") != "hardware_ineligible" or "raw-answers.jsonl" in files:
                raise ValueError("missing source case plan on eligible original shard")
            result = dict(tier=tier, case_index=index, rows=0, succeeded=0,
                          full_original_pair=False, exact_source_bound=False)
        else:
            result = bind_shard(files, tier=tier, index=index, plan=plan, docs=docs)
        if (result["rows"] != item.get("raw_attempt_rows")
                or result["succeeded"] != item.get("raw_success_rows")
                or result["full_original_pair"] != item.get("full_original_journal")):
            raise ValueError("original GitHub source-bound journal census disagrees")
        entries.append(dict(artifact_id=aid, github_zip_sha256=item["github_zip_sha256"],
                            **result))
    if len({(v["tier"], v["case_index"]) for v in entries}) != len(entries):
        raise ValueError("one reader case has multiple claimed original artifacts")
    return dict(
        schema="hepta.memory-cell.reader-source-bound-original-receipts.v1",
        frozen_source_zip_sha256=SOURCE_SHA,
        frozen_plan_sha256=PLAN_SHA,
        original_generating_commit=attestation["generating_source_commit"],
        original_run_id=attestation["generating_run_id"],
        github_qualified_artifact_count=len(entries),
        original_attempt_rows=sum(r["rows"] for r in entries),
        source_bound_successful_generations=sum(r["succeeded"] for r in entries),
        complete_five_arm_shards=sum(r["full_original_pair"] for r in entries),
        eligible_source_bound_shards=sum(r["exact_source_bound"] for r in entries),
        source_bindings=entries,
        reader_capacity_effect=None,
        independent_sufficiency_review=False,
        source_semantic_entailment_verified=False,
        learned_memory_gain_proven=False,
        original_ground_truth_parsed=False,
        new_model_calls=0,
        production_accepted=False,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_source_zip", type=Path)
    parser.add_argument("externally_attested_report", type=Path)
    parser.add_argument("original_artifact_zip_directory", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    report = strict(args.externally_attested_report.read_bytes())
    result = audit_attested_shards(
        args.original_source_zip, report, args.original_artifact_zip_directory
    )
    with args.result.open("x", encoding="utf-8") as output:
        json.dump(result, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps(dict(original_source_bound_generations=result[
        "source_bound_successful_generations"], complete_shards=result[
        "complete_five_arm_shards"]), sort_keys=True))


if __name__ == "__main__":
    main()
