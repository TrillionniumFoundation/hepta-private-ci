"""Posthoc original-index frontier of publisher-cited native sources.

Never a retrieval policy, human sufficiency ruling, future holdout or Reader gain.
The two immutable source experiments were already exposed; label/oracle data is
used ONLY after the frozen top-64 journal was produced. No selected source,
benchmark question, index, prompt or model output is rewritten.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import tempfile
from zipfile import ZipFile

GRID_SHA = "227453015e4535cff2f7f4df77fa374c0a027eb0ba9873d6625699ddbb96738c"
MATRIX_SHA = "3fe286f84d7f719ebe9ee300d3772aec1842dafb5c97ab9dfdb792eb4daaf43c"
PHASES = ("select", "retention", "test", "transfer")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(data):
    def pairs(rows):
        result = {}
        for k, v in rows:
            require(k not in result, "duplicate JSON key")
            result[k] = v
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON value: " + value)

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def sha256_file(path):
    require(path.is_file() and not path.is_symlink(), "regular archive required")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_zip(path, expected):
    require(sha256_file(path) == expected, "original GitHub artifact bytes drifted")
    z = ZipFile(path)
    files = {}
    for info in z.infolist():
        name = info.filename
        p = PurePosixPath(name)
        require(
            not p.is_absolute()
            and ".." not in p.parts
            and "\\" not in name
            and not stat.S_ISLNK(info.external_attr >> 16)
            and name == str(p)
            and name not in files
            and info.file_size <= 24 * 1024 * 1024,
            "unsafe, duplicate or oversized archived path",
        )
        if not info.is_dir():
            files[name] = info
    require(
        len(files) <= 512
        and sum(i.file_size for i in files.values()) < 90 * 1024 * 1024,
        "unbounded archive",
    )
    receipt = z.read("SHA256SUMS").decode("utf-8")
    declared = {}
    for line in receipt.splitlines():
        digest, separator, name = line.partition("  ")
        require(
            separator and HEX64.fullmatch(digest) and name and name not in declared,
            "malformed checksum inventory",
        )
        canonical = str(PurePosixPath(name))
        require(
            canonical not in declared and canonical != "SHA256SUMS",
            "duplicate or self-referential digest",
        )
        declared[canonical] = digest
    require(
        set(declared) == set(files) - {"SHA256SUMS"},
        "incomplete original checksum inventory",
    )
    for name, expected_digest in declared.items():
        require(
            hashlib.sha256(z.read(name)).hexdigest() == expected_digest,
            "original artifact member drifted",
        )
    return z, len(declared)


def classify(*, ranked, original_top8, oracle_ids, eligible, indexed):
    """Rank depth uses an *unchanged* score order and previously published IDs."""
    require(
        isinstance(ranked, list)
        and 8 <= len(ranked) <= 64
        and len(set(ranked)) == len(ranked)
        and all(isinstance(k, str) and k for k in ranked)
        and ranked[:8] == original_top8,
        "original frozen ranking or top-eight changed",
    )
    if not eligible:
        return dict(bucket="not-native-scored", first_rank=None)
    if not oracle_ids:
        return dict(bucket="no-publisher-oracle-source", first_rank=None)
    require(
        len(oracle_ids) == len(set(oracle_ids))
        and all(isinstance(i, str) and i for i in oracle_ids),
        "invalid oracle sources",
    )
    hits = [ranked.index(s) + 1 for s in oracle_ids if s in ranked]
    if hits:
        rank = min(hits)
        return dict(bucket="top8" if rank <= 8 else "ranks9-64", first_rank=rank)
    if indexed is None:
        return dict(bucket="index-unchecked", first_rank=None)
    return dict(
        bucket="indexed-beyond-64" if indexed else "not-in-original-index",
        first_rank=None,
    )


def load_index_identities(zipfile, key, family):
    name = f"comparison/index-{key}.sqlite"
    require(name in zipfile.namelist(), "original scoped as-of index missing")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "index.sqlite"
        path.write_bytes(zipfile.read(name))
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        try:
            docs = {}
            for (serialized,) in conn.execute("select record from docs"):
                item = strict_json(serialized)
                identity = item["identity"]
                require(
                    item["scope"] == family
                    and identity not in docs
                    and isinstance(identity, str)
                    and isinstance(item["root"], str)
                    and item["root"],
                    "inconsistent original scoped indexed document",
                )
                docs[identity] = item["root"]
            return docs
        finally:
            conn.close()


def analyze(grid, matrix):
    """Consume real frozen outputs; never choose a policy from exposed labels."""
    grid_plan = strict_json(grid.read("receipts/experiment-manifest.json"))
    matrix_plan = strict_json(matrix.read("comparison/preregistered.json"))
    require(
        grid_plan["schema"] == "hepta.stem-frozen-retrieval-grid-execution.v1"
        and grid_plan["number_original_questions"] == 80
        and grid_plan["number_asof_immutable_indexes"] == 18
        and grid_plan["original_pretrained_reader_calls"] == 0
        and matrix_plan["schema"] == "hepta.stem-cell.native-development.v1",
        "original generating cohorts or archive roles drifted",
    )
    raw = [
        strict_json(s)
        for s in grid.read("receipts/session-diverse-label-blind.jsonl")
        .decode()
        .splitlines()
    ]
    require(
        len(raw) == 80
        and all(
            r["read_targets_for_retrieval"] is False
            and r["pretrained_reader_calls"] == 0
            for r in raw
        ),
        "not a complete label-blind original frontier",
    )
    ranked = {}
    for row in raw:
        key = row["question_id"]
        require(
            key not in ranked and row["phase"] in ("train", *PHASES),
            "duplicate label-blind question",
        )
        values = row["ranked_original_source_sessions"]
        require(
            all(set(v) == {"id", "root", "session"} for v in values),
            "original indexed rows have changed fields",
        )
        identities = [v["id"] for v in values]
        require(
            len(identities) == len(set(identities)) and 8 <= len(identities) <= 64,
            "invalid original ranked frontier",
        )
        require(
            row["original_baseline_source_ids"] == identities[:8],
            "baseline is not the frozen top-eight",
        )
        ranked[key] = row
    native = strict_json(
        matrix.read("comparison/post-policy-native-source-ceiling.json")
    )
    require(
        native["after_all_policy_answers"] is True
        and native["final_checkpoint"] == 48
        and native["independent_semantic_review_performed"] is False,
        "not a completed historical posthoc native audit",
    )
    decisions = native["decisions"]
    oracle = [
        strict_json(s)
        for s in matrix.read("comparison/oracle-diagnostic.jsonl").decode().splitlines()
    ]
    expected = [(phase, q) for phase in PHASES for q in matrix_plan["questions"][phase]]
    require(
        len(expected) == 32 and len(set(expected)) == 32,
        "no exact registered evaluation census",
    )
    require(
        [(d["phase"], d["question_id"]) for d in decisions] == expected,
        "native diagnostic order or census changed",
    )
    require(
        [(d["phase"], d["question_id"]) for d in oracle] == expected,
        "publisher oracle order or census changed",
    )
    admission = strict_json(matrix.read("comparison/source-admission.json"))
    index_by_family = {}
    for index_key, record in admission.items():
        family = record["receipt"]["source_scope"]
        require(
            HEX64.fullmatch(index_key) and family not in index_by_family,
            "inconsistent original family index",
        )
        index_by_family[family] = index_key
    buckets = {phase: Counter() for phase in PHASES}
    rows = []
    scoped_indexes = {}
    for (phase, question), decision, example in zip(
        expected, decisions, oracle, strict=True
    ):
        item = ranked.get(question)
        require(
            item is not None
            and item["phase"] == phase
            and item["source_family"] == decision["source_family"],
            "original label-blind rank identity changed",
        )
        require(
            example.get("policy_comparator") is False
            and example.get("semantic_entailment_independently_verified") is False
            and (
                (
                    example.get("oracle_kind") == "native-source-literal-span"
                    and example.get("status") == "succeeded"
                )
                or (
                    example.get("oracle_kind") == "annotated-unanswerable"
                    and example.get("status") == "succeeded"
                )
                or (
                    example.get("oracle_kind") == "no-admitted-literal-reference-span"
                    and example.get("status") == "unavailable"
                )
            ),
            "oracle role, status or review state changed",
        )
        eligible = decision["weak_native_support_resolved"] is True
        delivered = example.get("receipt", {}).get("delivered_evidence", [])
        require(isinstance(delivered, list), "invalid recorded oracle evidence")
        ids = [v["original_id"] for v in delivered]
        require(
            (bool(ids) == (example["oracle_kind"] == "native-source-literal-span"))
            and len(set(ids)) == len(ids)
            and all(v["root"] for v in delivered)
            and (not delivered or example["status"] == "succeeded"),
            "unbound, repeated or unsuccessful oracle source",
        )
        recorded_roots = {
            v["id"]: v["root"] for v in item["ranked_original_source_sessions"]
        }
        for source in delivered:
            if source["original_id"] in recorded_roots:
                require(
                    recorded_roots[source["original_id"]] == source["root"],
                    "oracle root differs from original ranked source",
                )
        indexed = None
        if (
            eligible
            and ids
            and not set(ids).intersection(
                v["id"] for v in item["ranked_original_source_sessions"]
            )
        ):
            family = decision["source_family"]
            if family not in scoped_indexes:
                scoped_indexes[family] = load_index_identities(
                    matrix, index_by_family[family], family
                )
            known = scoped_indexes[family]
            for v in delivered:
                if v["original_id"] in known:
                    require(
                        known[v["original_id"]] == v["root"],
                        "oracle root differs from original indexed source",
                    )
            indexed = any(v["original_id"] in known for v in delivered)
        result = classify(
            ranked=[v["id"] for v in item["ranked_original_source_sessions"]],
            original_top8=item["original_baseline_source_ids"],
            oracle_ids=ids,
            eligible=eligible,
            indexed=indexed,
        )
        buckets[phase][result["bucket"]] += 1
        rows.append(
            dict(
                phase=phase,
                question_id=question,
                original_family=decision["source_family"],
                weak_source_labeled=eligible,
                publisher_oracle_status=example["status"],
                publisher_oracle_source_count=len(ids),
                **result,
            )
        )
    return dict(
        schema="hepta.stem-frozen-frontier-depth-audit.v1",
        generating_grid_source=grid_plan["generating_source"],
        generating_matrix_source=matrix_plan["source_commit"],
        planned=32,
        family_count=len({r["original_family"] for r in rows}),
        by_phase={phase: dict(buckets[phase]) for phase in PHASES},
        total=dict(sum((buckets[phase] for phase in PHASES), Counter())),
        decisions=rows,
        original_oracle_labels_already_exposed=True,
        only_publisher_oracle_source_ids_are_tested=True,
        native_weak_membership_not_semantic_entailment=True,
        absence_of_oracle_source_is_not_absence_of_ground_truth=True,
        did_not_propose_or_select_a_retrieval_policy=True,
        new_reader_executions=0,
        new_independent_observations=0,
        independent_semantic_citation_precision=None,
        significant_task_gain=None,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grid_zip", type=Path)
    parser.add_argument("native_zip", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), "do not overwrite previous historical audit")
    grid, grid_count = verify_zip(args.grid_zip, GRID_SHA)
    matrix, matrix_count = verify_zip(args.native_zip, MATRIX_SHA)
    try:
        result = analyze(grid, matrix)
    finally:
        grid.close()
        matrix.close()
    result["original_archive_members_checked"] = {
        "grid": grid_count,
        "matrix": matrix_count,
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, allow_nan=False, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "decisions"}, allow_nan=False
        )
    )


if __name__ == "__main__":
    main()
