"""Frozen Reader evidence-cardinality/salience ablation on authenticated one-hop sources.

This is a development-only model adequacy diagnostic.  The immutable one-hop
80-call baseline is reused; no answers, targets or training labels enter the
online selection.  Candidate source-order and cardinality changes alone.
"""

from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import zipfile

from system2_multihop_evidence import digest, parse_relation
from system2_multihop_trial import ABSTAIN, CITATION_RE, TOKEN_RE, evidence
from system2_native_receipt import strict_json
from system2_onehop_reader import (
    READER_IDENTITY,
    READER_PROFILE,
    cases,
    evaluate_one,
    select,
)

PARENT_SHA256 = "4e9e48bb266a7390089da5c80172d033d99522b1e786b05fc01973b63275ab03"
PARENT_COMMIT = "b38174570e3afe9299208945422b13f527bfd416"
PARENT_TREE = "51a11b5a52c39c1506e9cbeeac8a6953b0bc1abf"
PARENT_RAW_SHA256 = "092b1e9dfabef0fd710fe92512a1f43215f25b67035b43bf674e01ee11f4096f"
PARENT_MODEL_ZIP_SHA256 = (
    "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
)
ARMS = (
    "target_decoy_two_first",
    "target_decoy_two_last",
    "target_context_two",
    "target_decoys_three_last",
    "target_context_three",
    "decoy_one",
    "decoy_two",
)
POSITIVE = frozenset(ARMS[:5])
REPEATED = ("single_fact", "fact_plus_distractors", "distractors_only", "no_evidence")
TOTAL_TASKS = 20
PLANNED = TOTAL_TASKS * len(ARMS)
LABEL_ONLY = re.compile(r"\s*E\d+(?:\s+E\d+)*\s*", re.I)


def sha256_stream(stream):
    h = hashlib.sha256()
    while chunk := stream.read(1 << 20):
        h.update(chunk)
    return h.hexdigest()


def load_parent(path):
    """Pin every historic member while streaming large nested model archives."""
    archive = Path(path)
    if archive.is_symlink() or any(p.is_symlink() for p in archive.parents):
        raise ValueError("symlink archive")
    if not 1 <= archive.stat().st_size <= 512 * 1024**2:
        raise ValueError("unbounded archive bytes")
    with archive.open("rb") as fd:
        if sha256_stream(fd) != PARENT_SHA256:
            raise ValueError("GitHub artifact SHA256 mismatch")
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        if (
            not 1 <= len(members) <= 64
            or sum(m.file_size for m in members) > 512 * 1024**2
            or len({m.filename for m in members}) != len(members)
        ):
            raise ValueError("unbounded/duplicate archived members")
        for info in members:
            name = info.filename
            posix = PurePosixPath(name)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (
                info.is_dir()
                or posix.is_absolute()
                or ".." in posix.parts
                or posix.as_posix() != name
                or "\\" in name
                or any(ord(x) < 32 for x in name)
                or mode not in (0, stat.S_IFREG)
            ):
                raise ValueError("unsafe archived file")
        lines = z.read("SHA256SUMS").decode("utf-8").splitlines()
        hashes = {}
        for line in lines:
            match = re.fullmatch(r"([a-f0-9]{64})  \./(.+)", line)
            if match is None or match[2] in hashes:
                raise ValueError("duplicate/malformed member digest")
            hashes[match[2]] = match[1]
        if set(hashes) != {m.filename for m in members} - {"SHA256SUMS"}:
            raise ValueError("incomplete archived SHA256 manifest")
        for name, digest_value in hashes.items():
            with z.open(name) as fd:
                if sha256_stream(fd) != digest_value:
                    raise ValueError("changed archive source: " + name)
        if hashes["history-models.zip"] != PARENT_MODEL_ZIP_SHA256:
            raise ValueError("original frozen Reader archive changed")
        if (
            z.read("tested-commit.txt").decode().strip() != PARENT_COMMIT
            or z.read("tested-tree.txt").decode().strip() != PARENT_TREE
        ):
            raise ValueError("archived Git source identity drift")
        original_raw = z.read("native/raw-answers.jsonl")
        seal = strict_json(z.read("native/raw-seal.json"))
        if hashlib.sha256(
            original_raw
        ).hexdigest() != PARENT_RAW_SHA256 or seal != dict(
            sha256=PARENT_RAW_SHA256, rows=80, scoring_started=False
        ):
            raise ValueError("unsealed or changed 80 original answers")
        plan = strict_json(z.read("native/plan.json"))
        if (
            plan["source_commit"] != PARENT_COMMIT
            or plan["reader_identity"] != READER_IDENTITY
            or plan["reader_profile"] != READER_PROFILE
            or plan["arms"] != list(REPEATED)
            or plan["planned"] != 80
            or plan["question_ids"] != [c.question.identity for c in cases()]
        ):
            raise ValueError("original one-hop registered task drift")
        rows = [strict_json(line) for line in original_raw.splitlines()]
        scored = strict_json(z.read("native/scored.json"))
        original = {(r["qid"], r["arm"]): r for r in rows}
        verdicts = {(r["qid"], r["arm"]): r for r in scored}
        expected = {(c.question.identity, a) for c in cases() for a in REPEATED}
        if (
            len(rows) != 80
            or len(scored) != 80
            or set(original) != expected
            or set(verdicts) != expected
        ):
            raise ValueError("original reader answer census drift")
        from native import digest as native_digest

        for case in cases():
            for arm in REPEATED:
                key = case.question.identity, arm
                row = original[key]
                if row["status"] != "succeeded" or not row.get("answer"):
                    raise ValueError("missing historical model answer")
                docs = select(case.question, case.documents, arm)
                if row["selected"] != [d.identity for d in docs]:
                    raise ValueError("historical selected original bytes drift")
                bundle, _, frontier = evidence(case, docs, arm)
                receipt = row["reader"]
                if (
                    row["bundle_digest"] != bundle.seal()
                    or receipt["bundle_digest"] != bundle.seal()
                    or receipt["reader_identity"] != READER_IDENTITY
                    or receipt["reader_profile"] != READER_PROFILE
                    or receipt["query_digest"] != native_digest(asdict(case.question))
                    or receipt["trainable_parameters"] != 0
                    or receipt["answer_postprocessed"] is not False
                    or receipt["token_limit"] != 1024
                    or not 1 <= receipt["generated_tokens"] <= 64
                    or [d["original_id"] for d in receipt["delivered_evidence"]]
                    != row["selected"]
                ):
                    raise ValueError("Reader signature or evidence binding drift")
                if (
                    len(receipt["input_ids_digest"]) != 64
                    or len(receipt["generated_ids_digest"]) != 64
                ):
                    raise ValueError("missing token-identity seal")
                if verdicts[key].get("status") != "succeeded":
                    raise ValueError("original scored status drift")
                for field, value in evaluate_one(
                    case, arm, row["selected"], row["answer"]
                ).items():
                    if verdicts[key].get(field) != value:
                        raise ValueError("original scored field drift: " + field)
                if (
                    "source_frontier" in receipt
                    and frontier != receipt["source_frontier"]
                ):
                    raise ValueError("original source frontier drift")
        return dict(
            rows=original,
            manifest_entries=len(hashes),
            sha256=PARENT_SHA256,
            original_seal=PARENT_RAW_SHA256,
        )


def choose_onehop(case, arm):
    """Read ONLY observable question/source records; case.answer is unused."""
    if arm not in ARMS:
        raise ValueError("unregistered one-hop evidence intervention")
    target = select(case.question, case.documents, "single_fact")
    decoys = select(case.question, case.documents, "distractors_only")
    contexts = tuple(
        sorted(
            (
                d
                for d in case.documents
                if (e := parse_relation(d))
                and not (e[0] == "device" and e[2] == "token")
            ),
            key=lambda x: x.identity,
        )
    )
    if len(target) != 1 or len(decoys) < 2 or len(contexts) < 2:
        raise ValueError("insufficient fixed evidence for registered arms")
    t, a, b, u, v = target[0], decoys[0], decoys[1], contexts[0], contexts[1]
    table = {
        "target_decoy_two_first": (t, a),
        "target_decoy_two_last": (a, t),
        "target_context_two": (t, u),
        "target_decoys_three_last": (a, b, t),
        "target_context_three": (t, u, v),
        "decoy_one": (a,),
        "decoy_two": (a, b),
    }
    docs = table[arm]
    if len({d.identity for d in docs}) != len(docs):
        raise ValueError("duplicate selected source")
    must_be_sufficient = arm in POSITIVE
    if (t.identity in {d.identity for d in docs}) != must_be_sufficient:
        raise ValueError("unregistered ground-truth-source inclusion")
    if any(
        d.scope != case.question.scope or d.observed_at > case.question.observed_at
        for d in docs
    ):
        raise ValueError("inadmissible evidence source")
    return docs


def score_one(case, arm, selected_ids, answer):
    if arm not in ARMS or not isinstance(answer, str) or not answer.strip():
        raise ValueError("invalid candidate answer")
    selected = choose_onehop(case, arm)
    if selected_ids != [d.identity for d in selected]:
        raise ValueError("chosen source changed since Reader generation")
    sufficient = arm in POSITIVE
    found = TOKEN_RE.findall(answer.upper())
    token_exact = len(found) == 1 and found[0] == case.answer
    citations = [c.upper() for c in CITATION_RE.findall(answer)]
    mapping = {f"E{i + 1}": doc.identity for i, doc in enumerate(selected)}
    citation_valid = bool(citations) and all(c in mapping for c in citations)
    citation_sufficient = citation_valid and case.required_id in (
        mapping[c] for c in citations
    )
    abstained = answer.strip().strip('"').casefold() == ABSTAIN.casefold()
    return dict(
        sufficient=sufficient,
        target_token_mentioned=case.answer in answer.upper(),
        correct_single_token=token_exact,
        citation_syntax_valid=citation_valid,
        cites_required_source=citation_sufficient,
        grounded_answer_success=sufficient and token_exact and citation_sufficient,
        strict_abstention=abstained,
        unsupported_token_copy=not sufficient and bool(found),
        label_only_answer=bool(LABEL_ONLY.fullmatch(answer)),
        exact_unreferenced_answer=sufficient
        and token_exact
        and not citation_sufficient,
        human_semantic_judgment=False,
    )


def census(rows, registered):
    expected = {(case.question.identity, arm) for case in registered for arm in ARMS}
    actual = [(r["qid"], r["arm"]) for r in rows]
    if (
        len(actual) != len(expected)
        or set(actual) != expected
        or len(set(actual)) != len(actual)
    ):
        raise ValueError("incomplete, duplicate, or altered one-hop cardinality census")
    if any(r["status"] not in ("succeeded", "failed") for r in rows):
        raise ValueError("unregistered Reader status")
    return dict(
        planned=len(expected),
        recorded=len(rows),
        succeeded=sum(r["status"] == "succeeded" for r in rows),
        failed=sum(r["status"] == "failed" for r in rows),
    )


def write(path, data):
    path.write_text(
        json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def append(path, data):
    with path.open("a", encoding="utf-8") as fd:
        fd.write(
            json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        )
        fd.flush()
        os.fsync(fd.fileno())


def run(output, reader, parent_archive, *, source_commit, count=TOTAL_TASKS):
    if (
        not re.fullmatch(r"[a-f0-9]{40}", source_commit or "")
        or type(count) is not int
        or not 1 <= count <= TOTAL_TASKS
    ):
        raise ValueError("exact source identity and bounded cohort required")
    parent = load_parent(parent_archive)
    registered = cases()[:count]
    output.mkdir(parents=True, exist_ok=False)
    combinations = [(c, a) for c in registered for a in ARMS]
    combinations.sort(
        key=lambda item: (
            item[0].question.identity,
            (ARMS.index(item[1]) + int(digest(item[0].question.identity)[:8], 16))
            % len(ARMS),
        )
    )
    plan = dict(
        schema="hepta.system2.onehop-cardinality.v1",
        source_commit=source_commit,
        parent_commit=PARENT_COMMIT,
        parent_sha256=PARENT_SHA256,
        parent_raw_sha256=PARENT_RAW_SHA256,
        parent_manifest_files=parent["manifest_entries"],
        registered_question_ids=[c.question.identity for c in registered],
        old_control_arms=list(REPEATED),
        new_arms=list(ARMS),
        expected_new_calls=len(combinations),
        reader_identity=READER_IDENTITY,
        reader_profile=READER_PROFILE,
        max_new_tokens=64,
        input_budget_tokens=1024,
        zero_training_updates=True,
        source_label_read_only_after_seal=True,
        outcome_labels_unavailable_online=True,
        never_count_generated_evidence_as_reader_citations=True,
        independent_natural_domain=False,
        production_accepted=False,
    )
    write(output / "plan.json", plan)
    rows = []
    try:
        for case, arm in combinations:
            row = dict(qid=case.question.identity, arm=arm, status="started")
            append(output / "starts.jsonl", row)
            started = time.perf_counter()
            try:
                selected = choose_onehop(case, arm)
                bundle, originals, frontier = evidence(case, selected, arm)
                row.update(
                    selected=[d.identity for d in selected],
                    bundle_digest=bundle.seal(),
                    scanned_original_bytes=sum(
                        len(d.content.encode()) for d in case.documents
                    ),
                )
                answer, rec = reader.answer(
                    case.question,
                    bundle,
                    originals,
                    frontier=frontier,
                    revoked=set(),
                    token_limit=1024,
                )
                if (
                    not isinstance(answer, str)
                    or not answer.strip()
                    or rec.get("reader_identity") != READER_IDENTITY
                    or rec.get("reader_profile") != READER_PROFILE
                    or rec.get("bundle_digest") != row["bundle_digest"]
                    or rec.get("query_digest") != digest(asdict(case.question))
                    or rec.get("delivered_evidence") != bundle.delivered()
                    or not 1 <= rec.get("input_tokens", 0) <= 1024
                    or rec.get("answer_postprocessed") is not False
                    or rec.get("trainable_parameters") != 0
                    or rec.get("token_limit") != 1024
                    or not 1 <= rec.get("generated_tokens", 0) <= 64
                ):
                    raise ValueError(
                        "Reader frozen model/output/evidence receipt drift"
                    )
                row.update(status="succeeded", answer=answer, reader=rec)
            except Exception as exc:
                row.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    incomplete_cost_unknown=True,
                )
            row["elapsed_seconds"] = time.perf_counter() - started
            append(output / "raw-answers.jsonl", row)
            rows.append(row)
        raw = (output / "raw-answers.jsonl").read_bytes()
        seal = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=seal, rows=len(rows), scoring_started=False),
        )
        ca = census(rows, registered)
        scored = []
        summary = []
        cmap = {c.question.identity: c for c in registered}
        for row in rows:
            if row["status"] == "succeeded":
                result = score_one(
                    cmap[row["qid"]], row["arm"], row["selected"], row["answer"]
                )
                scored.append(
                    dict(qid=row["qid"], arm=row["arm"], status="succeeded", **result)
                )
            else:
                scored.append(
                    dict(
                        qid=row["qid"],
                        arm=row["arm"],
                        status="failed",
                        grounded_answer_success=None,
                    )
                )
        for arm in ARMS:
            group = [s for s in scored if s["arm"] == arm]
            good = [s for s in group if s["status"] == "succeeded"]
            summary.append(
                dict(
                    arm=arm,
                    planned=len(group),
                    completed=len(good),
                    sufficient=sum(s["sufficient"] for s in good),
                    target_token_mentions=sum(
                        s["target_token_mentioned"] for s in good
                    ),
                    correct_single_token=sum(s["correct_single_token"] for s in good),
                    grounded_answers=sum(s["grounded_answer_success"] for s in good),
                    strict_abstentions=sum(s["strict_abstention"] for s in good),
                    label_only_answers=sum(s["label_only_answer"] for s in good),
                    unsupported_token_copy=sum(
                        s["unsupported_token_copy"] for s in good
                    ),
                    failures=len(group) - len(good),
                    unknown_failed_work=True,
                )
            )
        for arm in (
            "single_fact",
            "fact_plus_distractors",
            "distractors_only",
            "no_evidence",
        ):
            controls = [parent["rows"][c.question.identity, arm] for c in registered]
            summary.append(
                dict(
                    arm="historic_" + arm,
                    planned=len(controls),
                    completed=len(controls),
                    target_token_mentions=sum(
                        cmap[r["qid"]].answer in r["answer"].upper() for r in controls
                    ),
                    label_only_answers=sum(
                        bool(LABEL_ONLY.fullmatch(r["answer"])) for r in controls
                    ),
                    strict_abstentions=sum(
                        r["answer"].strip().strip('"').casefold() == ABSTAIN.casefold()
                        for r in controls
                    ),
                    reader_calls_replayed=0,
                    authenticated_parent=True,
                )
            )
        rows_by_arm = {g["arm"]: g for g in summary}
        adequate = (
            all(
                rows_by_arm[arm]["grounded_answers"] >= 15
                for arm in ("target_decoy_two_first", "target_decoy_two_last")
            )
            and all(
                rows_by_arm[arm]["strict_abstentions"] >= 18
                for arm in ("decoy_one", "decoy_two")
            )
            and ca["failed"] == 0
            and count == TOTAL_TASKS
        )
        write(output / "scored.json", scored)
        write(
            output / "summary.json",
            dict(
                census=ca,
                groups=summary,
                candidate_disposition=(
                    "independent_natural_reader_confirmation_required"
                    if adequate
                    else "reader_cardinality_preflight_failed"
                ),
                source_commit=source_commit,
                no_new_model_training=True,
                independent_human_review=False,
                production_accepted=False,
            ),
        )
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != seal
        ):
            raise ValueError("sealed Reader answers changed during scoring")
        if ca["failed"]:
            raise RuntimeError("failed Reader calls retain entire planned denominator")
        return ca, summary
    except BaseException as exc:
        write(
            output / "run-failure.json",
            dict(
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                planned=len(combinations),
                recorded=len(rows),
                incomplete_work_not_free=True,
            ),
        )
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("historical_zip", type=Path)
    ap.add_argument("reader", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--development", action="store_true")
    args = ap.parse_args()
    if not args.development:
        raise ValueError("explicit research-only execution required")
    from bundle_reader import FrozenBundleReader

    reader = FrozenBundleReader(args.reader, expected_inventory=READER_IDENTITY)
    result = run(
        args.output,
        reader,
        args.historical_zip,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    reader.verify_frozen()
    print(json.dumps(dict(census=result[0], groups=result[1]), allow_nan=False))


if __name__ == "__main__":
    main()
