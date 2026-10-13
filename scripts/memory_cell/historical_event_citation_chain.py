"""Read-only *formal event-chain* citation diagnostic for archived real answers.

This is NOT a human/semantic entailment judge. In particular the authored
program support set is not independently certified necessary or sufficient.
No model is called, no answer/citation is repaired, and no production admission
is possible through this diagnostic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile

SCHEMA = "hepta.memory-cell.historical-formal-citation.v1"
GENERATING_COMMIT = "59f9eadd5cc919359079e04442f7343838a60057"
PLAN_SHA256 = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
ARCHIVES = {
    "qwen-3b": "831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98",
    "smol-1.7b": "67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae",
}
ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)
MARKER = re.compile(r"\[(E[1-9][0-9]*)\]")
MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    return json.loads(
        data,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )


def digest_json(value):
    return sha(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def archived_files(path, expected_sha):
    """Reject renamed/replaced bytes or unlisted, duplicated, escaping members."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError("bounded original ZIP required")
    if sha(path.read_bytes()) != expected_sha:
        raise ValueError("historical outer ZIP SHA mismatch")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= 128:
            raise ValueError("archive member census")
        if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("archive uncompressed bound")
        files = {}
        for item in members:
            name = item.filename
            parts = name.split("/")
            if (
                name in files
                or item.is_dir()
                or name.startswith("/")
                or "\\" in name
                or any(p in ("", ".", "..") for p in parts)
                or stat.S_ISLNK(item.external_attr >> 16)
            ):
                raise ValueError("untrusted archive path or duplicate")
            files[name] = archive.read(item)
        if "SHA256SUMS" not in files or "tested-commit.txt" not in files:
            raise ValueError("missing immutable manifest")
        pinned = {}
        for line in files["SHA256SUMS"].decode("utf-8").splitlines():
            hit = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?([^ ]+)", line)
            if hit is None or hit[2] in pinned:
                raise ValueError("bad SHA256SUMS row")
            pinned[hit[2]] = hit[1]
        if set(pinned) != set(files) - {"SHA256SUMS"}:
            raise ValueError("unlisted or missing archive member")
        if any(sha(files[name]) != hexsha for name, hexsha in pinned.items()):
            raise ValueError("inner archive member SHA mismatch")
        if files["tested-commit.txt"].decode("utf-8").strip() != GENERATING_COMMIT:
            raise ValueError("generating commit identity mismatch")
        return files


def bounded_source(path, expected):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("bounded pinned source required")
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError("original source SHA mismatch")
    return strict_json(raw)


def trace_cited_chain(spec, cited_sources, original_docs, identifier):
    """Require EVERY cited source to support a complete current answer path.

    A forward-reachable dead end or unrelated delivered citation cannot be
    counted as a valid full source chain merely because another path succeeds.
    This remains a formal event-graph diagnostic, not semantic entailment.
    """
    if (
        not identifier
        or not cited_sources
        or len(set(cited_sources)) != len(cited_sources)
        or any(key not in original_docs for key in cited_sources)
    ):
        return False
    scope = original_docs[cited_sources[0]]["scope"]
    if any(original_docs[key]["scope"] != scope for key in cited_sources):
        return False
    if spec.get("id") is not None and spec["id"] != scope:
        return False
    visible = {}
    for key, source in original_docs.items():
        if source["scope"] == scope:
            event = strict_json(source["content"])
            if event["revision"] <= spec["revision"]:
                visible[key] = event
    entities = {spec["entity"]}
    hops = []
    for attribute in spec["path"]:
        replaced = {
            ancestor
            for event in visible.values()
            if event["entity"] in entities and event["attribute"] == attribute
            for ancestor in event["supersedes"]
        }
        edges = [
            (source_id, visible[source_id]["entity"], visible[source_id]["value"])
            for source_id in cited_sources
            if source_id in visible
            and source_id not in replaced
            and visible[source_id]["entity"] in entities
            and visible[source_id]["attribute"] == attribute
        ]
        if not edges:
            return False
        hops.append(edges)
        entities = {destination for _, _, destination in edges}
    if entities != {identifier}:
        return False
    # Work backwards from the claimed answer so a cited partial path which
    # never reaches the answer cannot count as supporting evidence.
    supported = {identifier}
    contributing = set()
    for edges in reversed(hops):
        predecessors = [
            (source_id, source)
            for source_id, source, destination in edges
            if destination in supported
        ]
        if not predecessors:
            return False
        contributing.update(source_id for source_id, _ in predecessors)
        supported = {source for _, source in predecessors}
    return spec["entity"] in supported and contributing == set(cited_sources)


def trace_row(row, spec, declared_support, original_docs):
    if row["status"] == "failed":
        return dict(
            question_id=row["question_id"],
            kind=row["kind"],
            arm=row["arm"],
            generation_status="failed",
            strict_task_success=None,
            cited_source_ids=[],
            missing_program_declared_support=None,
            program_declared_support_cited=None,
            publicly_declared_event_path_connected=None,
            answer_has_citation_marker=None,
        )
    if row["status"] != "succeeded":
        raise ValueError("unregistered generation status")
    answer, receipt = row["answer"], row["receipt"]
    if not isinstance(answer, str) or not isinstance(receipt, dict):
        raise ValueError("malformed generation")
    delivered = receipt["delivered_evidence"]
    labels = {}
    if [s["original_id"] for s in delivered] != row["selected"]:
        raise ValueError("selected evidence changed")
    for i, source in enumerate(delivered, 1):
        identity = source["original_id"]
        original = original_docs[identity]
        if (
            source["label"] != f"E{i}"
            or source["label"] in labels
            or source["excerpt"] != original["content"]
            or source["scope"] != original["scope"]
            or source["root"] != original["root"]
            or source["source_digest"] != digest_json(original["content"])
        ):
            raise ValueError("source excerpt/identity/label drift")
        labels[source["label"]] = identity
    claim_markers = MARKER.findall(answer)
    if len(set(claim_markers)) != len(claim_markers):
        raise ValueError("repeated citation marker")
    if any(m not in labels for m in claim_markers):
        raise ValueError("citation marker not in supplied evidence")
    request = row["citation_audit"]["request"]
    if (
        request["answer"] != answer
        or request["query_id"] != row["question_id"]
        or request["prompt_digest"] != receipt["input_ids_digest"]
    ):
        raise ValueError("citation queue detached from model generation")
    success = row["strict_task_success"]
    if type(success) is not bool:
        raise ValueError("nonboolean strict historical outcome")
    identifier = row.get("parsed_identifier")
    if identifier is not None and not isinstance(identifier, str):
        raise ValueError("invalid parsed identifier")
    cited = [labels[marker] for marker in claim_markers]
    missing = sorted(set(declared_support) - set(cited))
    path_connected = trace_cited_chain(spec, cited, original_docs, identifier)
    return dict(
        question_id=row["question_id"],
        kind=row["kind"],
        arm=row["arm"],
        answer=answer,
        generation_status="succeeded",
        strict_task_success=success,
        cited_source_ids=cited,
        missing_program_declared_support=missing,
        program_declared_support_cited=bool(cited) and not missing,
        publicly_declared_event_path_connected=path_connected,
        answer_has_citation_marker=bool(claim_markers),
    )


def summarize(rows, *, arms=ARMS, expected_questions=8):
    summaries = {}
    for arm in arms:
        group = [row for row in rows if row["arm"] == arm]
        if len(group) != expected_questions:
            raise ValueError("incomplete arm census")
        correct = [r for r in group if r["strict_task_success"] is True]
        summaries[arm] = dict(
            attempted=len(group),
            generations_succeeded=sum(
                r["generation_status"] == "succeeded" for r in group
            ),
            generations_failed=sum(r["generation_status"] == "failed" for r in group),
            strict_task_success=len(correct),
            correct_with_full_program_declared_citations=sum(
                r["program_declared_support_cited"] for r in correct
            ),
            correct_with_public_event_chain_connected=sum(
                r["publicly_declared_event_path_connected"] for r in correct
            ),
            correct_without_citation_marker=sum(
                not r["answer_has_citation_marker"] for r in correct
            ),
            correct_missing_program_declared_support=sum(
                bool(r["missing_program_declared_support"]) for r in correct
            ),
        )
    return summaries


def audit_evaluation(rows, specs, labels, documents, *, expected_qids, arms):
    """Recompute formal citation fidelity from sealed answers, never retrain.

    Original public questions and scorer labels are opened by the caller only
    AFTER the full raw-answer journal is durable. Failed model calls remain in
    the planned census and are never converted to successful empty citations.
    """
    spec_by_id = {s["id"]: s for s in specs}
    truth_by_id = {s["id"]: s for s in labels}
    docs_by_id = {
        (d["identity"] if isinstance(d, dict) else d.identity): (
            d
            if isinstance(d, dict)
            else dict(
                identity=d.identity,
                root=d.root,
                scope=d.scope,
                content=d.content,
            )
        )
        for d in (documents.values() if isinstance(documents, dict) else documents)
    }
    if (
        not expected_qids
        or len(set(expected_qids)) != len(expected_qids)
        or not arms
        or len(set(arms)) != len(arms)
        or len(rows) != len(expected_qids) * len(arms)
        or len(spec_by_id) != len(specs)
        or len(truth_by_id) != len(labels)
        or any(q not in spec_by_id or q not in truth_by_id for q in expected_qids)
        or {(r["question_id"], r["arm"]) for r in rows}
        != {(qid, arm) for qid in expected_qids for arm in arms}
        or len(docs_by_id)
        != (len(documents) if not isinstance(documents, dict) else len(documents))
    ):
        raise ValueError("incomplete formal citation census")
    verified = []
    for row in rows:
        qid = row["question_id"]
        if row["kind"] != spec_by_id[qid]["kind"]:
            raise ValueError("public task kind drift")
        verified.append(
            trace_row(
                row,
                spec_by_id[qid],
                truth_by_id[qid]["support"],
                docs_by_id,
            )
        )
    return dict(
        schema="hepta.memory-cell.formal-citation-evaluation.v1",
        planned_questions=len(expected_qids),
        planned_attempts=len(rows),
        by_arm=summarize(verified, arms=arms, expected_questions=len(expected_qids)),
        cases=verified,
        independent_semantic_adjudication=False,
        human_certified_necessity=False,
        production_accepted=False,
    )


def audit_model(archive, *, model, original, plan, specs, targets, files_sha):
    files = archived_files(archive, ARCHIVES[model])
    if sha(files["run/scored-answers.json"]) != files_sha:
        raise ValueError("scored answer bytes unpinned")
    scored = strict_json(files["run/scored-answers.json"])
    raw = [strict_json(line) for line in files["run/raw-answers.jsonl"].splitlines()]
    if len(scored) != len(raw) or len(scored) != 48:
        raise ValueError("not 48 true model attempts")
    for original_row, scored_row in zip(raw, scored):
        if any(scored_row.get(k) != v for k, v in original_row.items()):
            raise ValueError("scorer rewrote generated text/evidence/receipt")
    docs = {r["identity"]: r for r in original}
    if len(docs) != len(original) or len(docs) != 108:
        raise ValueError("original source census changed")
    cases = {r["query"]["identity"]: r for r in plan["cases"]}
    if len(cases) != 8:
        raise ValueError("original test population changed")
    if set(cases) != {q for q in specs if specs[q]["phase"] == "test"}:
        raise ValueError("public test partition drift")
    expected = {(qid, arm) for qid in cases for arm in ARMS}
    if (
        len({(r["question_id"], r["arm"]) for r in scored}) != len(scored)
        or {(r["question_id"], r["arm"]) for r in scored} != expected
    ):
        raise ValueError("missing/duplicated attempt")
    results = []
    for row in scored:
        qid = row["question_id"]
        if row["kind"] != specs[qid]["kind"]:
            raise ValueError("public task kind changed")
        results.append(trace_row(row, specs[qid], targets[qid]["support"], docs))
    return dict(
        archive_sha256=ARCHIVES[model],
        scored_answers_sha256=files_sha,
        generating_commit=GENERATING_COMMIT,
        attempted=len(results),
        by_arm=summarize(results),
        cases=results,
    )


def audit(original_root, *, archives, scored_pins):
    root = Path(original_root)
    plan = bounded_source(root / "plan/plan.json", PLAN_SHA256)
    documents = bounded_source(root / "plan/source-view.json", plan["source_view_sha"])
    targets = bounded_source(root / "observations/labels.json", plan["labels_sha"])
    collection = bounded_source(
        root / "observations/collection.json", plan["frozen"]["collection_sha"]
    )
    questions = bounded_source(
        root / "observations/questions.json", collection["files"]["questions.json"]
    )
    specs = {r["id"]: r for r in questions}
    truths = {r["id"]: r for r in targets}
    if len(specs) != 16 or len(truths) != 16:
        raise ValueError("16 original public tasks required")
    return dict(
        schema=SCHEMA,
        pinned_plan_sha256=PLAN_SHA256,
        generating_commit=GENERATING_COMMIT,
        real_model_generations=96,
        model_semantic_entailment_certified=False,
        program_declared_support_is_human_certified=False,
        formal_event_path_is_production_semantic_precision=False,
        independent_source_families=0,
        production_accepted=False,
        models={
            name: audit_model(
                archives[name],
                model=name,
                original=documents,
                plan=plan,
                specs=specs,
                targets=truths,
                files_sha=scored_pins[name],
            )
            for name in ARCHIVES
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("--qwen-archive", required=True, type=Path)
    parser.add_argument("--smol-archive", required=True, type=Path)
    parser.add_argument("--qwen-scored-sha256", required=True)
    parser.add_argument("--smol-scored-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    a = parser.parse_args()
    report = audit(
        a.original,
        archives={
            "qwen-3b": a.qwen_archive,
            "smol-1.7b": a.smol_archive,
        },
        scored_pins={
            "qwen-3b": a.qwen_scored_sha256,
            "smol-1.7b": a.smol_scored_sha256,
        },
    )
    with a.output.open("x", encoding="utf-8") as target:
        json.dump(
            report,
            target,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        target.write("\n")
    print(
        json.dumps(
            {n: r["by_arm"] for n, r in report["models"].items()}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
