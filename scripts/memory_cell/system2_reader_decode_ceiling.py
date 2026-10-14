"""Frozen Reader decoding-cap diagnostic against an immutable hosted 64-token run.

Research only: 96 new 128-token continuations on exactly the same prompt IDs,
selected evidence and weights. The source 160 answers are NOT regenerated.
Lengthened decoding is extra compute, not a budget-matched search or NDU win.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

from system2_multihop_counterfactual import ARMS, cases, select, source_manifest
from system2_multihop_counterfactual_trial import evidence, score
from system2_multihop_evidence import digest
from system2_native_receipt import strict_json, verified_archive

PARENT_SHA256 = "9ee9e63a725b3a5598ba6e89d728d6b17582d60853ee994151c1b58a15bf4a95"
PARENT_COMMIT = "f3609d11cbe715c0202cb09e1463fa4ad002bd3d"
PARENT_TREE = "4846438b33ccf78ef715011f9c181488848f850b"
PARENT_RAW_SEAL = "cf3c06d54d86d6a9ea44e08a86083cd583fb319774468e6ad1acae7c57d4ec40"
READER_ID = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
NEW_ARMS = ("joined_top3", "reversed_join_top3", "missing_start_top3")
GENERATION_CAP = 128
BASELINE_CAP = 64
PLANNED = 32 * len(NEW_ARMS)


def write(path, data):
    with path.open("x", encoding="utf8") as f:
        json.dump(
            data, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        f.write("\n")


def append(path, data):
    with path.open("a", encoding="utf8") as f:
        f.write(
            json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        )
        f.flush()
        os.fsync(f.fileno())


def load_parent(path):
    """Fail closed on ZIP, internal hashes, 160 raw rows, seal and exact cohort."""
    files = verified_archive(Path(path), PARENT_SHA256)
    if (
        files["tested-commit.txt"].decode().strip() != PARENT_COMMIT
        or files["tested-tree.txt"].decode().strip() != PARENT_TREE
    ):
        raise ValueError("archived generating source changed")
    raw = files["native/raw-answers.jsonl"]
    seal = strict_json(files["native/raw-seal.json"])
    if hashlib.sha256(raw).hexdigest() != PARENT_RAW_SEAL or seal != dict(
        sha256=PARENT_RAW_SEAL, rows=160, scoring_started=False
    ):
        raise ValueError("parent original answer seal drift")
    plan = strict_json(files["native/plan.json"])
    if (
        plan["source_commit"] != PARENT_COMMIT
        or plan["arms"] != list(ARMS)
        or plan["planned_reader_calls"] != 160
        or plan["pair_count"] != 16
    ):
        raise ValueError("parent registration drift")
    pairs = cases()
    expected = {
        (case.question.identity, arm) for pair in pairs for case in pair for arm in ARMS
    }
    by_key = {}
    for raw_line in raw.splitlines():
        item = strict_json(raw_line)
        key = (item["qid"], item["arm"])
        if (
            key not in expected
            or key in by_key
            or item["status"] != "succeeded"
            or type(item.get("answer")) is not str
            or not item["answer"].strip()
        ):
            raise ValueError("missing/duplicate/failed historic arm")
        rec = item["reader"]
        if (
            rec["reader_identity"] != READER_ID
            or rec["trainable_parameters"] != 0
            or rec["answer_postprocessed"] is not False
            or rec["production_accepted"] is not False
            or rec["generated_tokens"] not in range(1, BASELINE_CAP + 1)
            or rec["token_limit"] != 1024
        ):
            raise ValueError("original frozen Reader receipt drift")
        if len(rec["delivered_evidence"]) != len(item["selected"]):
            raise ValueError("selected source/cardinality mismatch")
        by_key[key] = item
    if set(by_key) != expected:
        raise ValueError("incomplete historical arm denominator")
    scored = strict_json(files["native/scored.json"])
    scored_by_key = {(r["qid"], r["arm"]): r for r in scored}
    if len(scored_by_key) != 160 or set(scored_by_key) != expected:
        raise ValueError("historic scores changed")
    for j, pair in enumerate(pairs):
        for v, case in enumerate(pair):
            for arm in ARMS:
                r = by_key[case.question.identity, arm]
                selected = select(arm, case.question, case.documents)
                if (
                    r["pair_index"] != j
                    or r["variant"] != v
                    or r["source_manifest"] != source_manifest(case)
                    or r["selected"] != [d.identity for d in selected]
                    or [d["original_id"] for d in r["reader"]["delivered_evidence"]]
                    != r["selected"]
                ):
                    raise ValueError("source/document identity drift")
                for key, value in score(case, selected, r["answer"]).items():
                    if scored_by_key[r["qid"], arm].get(key) != value:
                        raise ValueError("old model output score drift")
    return dict(
        by_key=by_key,
        pairs=pairs,
        parent_digest=PARENT_SHA256,
        raw_seal=PARENT_RAW_SEAL,
        verified_files=len(files) - 1,
    )


def decode_128(reader, query, bundle, originals, *, frontier):
    """Only a decoding ceiling changes; no targets or search policies are inputs."""
    import torch
    from bundle_reader import GENERATION, SYSTEM
    from native import digest as native_digest

    ids, receipt = reader.compile_input(
        query, bundle, originals, frontier=frontier, revoked=set(), token_limit=1024
    )
    config = dict(GENERATION, max_new_tokens=GENERATION_CAP)
    if (
        config["do_sample"] is not False
        or config["num_beams"] != 1
        or len(ids) + GENERATION_CAP > reader.model.config.max_position_embeddings
    ):
        raise ValueError("unregistered or oversized frozen decode")
    inp = torch.tensor([ids], dtype=torch.long)
    started = time.perf_counter()
    with torch.inference_mode():
        output = reader.model.generate(
            input_ids=inp,
            attention_mask=torch.ones_like(inp),
            **config,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id,
        )
    elapsed = time.perf_counter() - started
    tokens = output[0, len(ids) :].tolist()
    if not 1 <= len(tokens) <= GENERATION_CAP:
        raise ValueError("unexpected decode length")
    answer = reader.tokenizer.decode(
        tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    if not answer.strip():
        raise ValueError("empty extended Reader response")
    bundle.validate(query, originals, frontier=frontier, revoked=set())
    return answer, receipt | dict(
        reader_identity=reader.identity,
        reader_profile=native_digest((SYSTEM, config, reader.tokenizer.chat_template)),
        trainable_parameters=0,
        answer_postprocessed=False,
        production_accepted=False,
        generated_tokens=len(tokens),
        generated_ids_digest=native_digest(tokens),
        first64_ids_digest=native_digest(tokens[:BASELINE_CAP]),
        seconds=elapsed,
        max_new_tokens=GENERATION_CAP,
        frozen_decoder_unmodified=True,
    )


def match_historical(source, receipt, answer):
    """Verify same prompt and exact greedy decoding prefix, or abort."""
    old = source["reader"]
    for k in (
        "reader_identity",
        "input_ids_digest",
        "query_digest",
        "bundle_digest",
        "token_limit",
        "input_tokens",
        "delivered_evidence",
    ):
        if receipt.get(k) != old.get(k):
            raise ValueError("same-prompt or same-Reader invariant failed: " + k)
    if old["generated_tokens"] == BASELINE_CAP:
        if (
            receipt["generated_tokens"] < BASELINE_CAP
            or receipt["first64_ids_digest"] != old["generated_ids_digest"]
        ):
            raise ValueError("greedy first-64-token continuation drift")
        return "prefix64-identical"
    if (
        receipt["generated_tokens"] != old["generated_tokens"]
        or receipt["generated_ids_digest"] != old["generated_ids_digest"]
        or answer != source["answer"]
    ):
        raise ValueError("early-EOS baseline output changed under longer cap")
    return "same-early-eos"


def assess(raw_rows, parent):
    """Score all completed rows only after their original bytes are sealed."""
    key_map = {(row["qid"], row["arm"]): row for row in raw_rows}
    expected = {
        (case.question.identity, arm)
        for pair in parent["pairs"]
        for case in pair
        for arm in NEW_ARMS
    }
    if (
        len(raw_rows) != PLANNED
        or set(key_map) != expected
        or len(key_map) != len(raw_rows)
    ):
        raise ValueError("incomplete/duplicated decoding comparison")
    details, summary = [], []
    for arm in NEW_ARMS:
        old_valid, new_valid, old_exact, new_exact = 0, 0, 0, 0
        old_abstain, new_abstain, original_cap, output_cap = 0, 0, 0, 0
        for pair in parent["pairs"]:
            for case in pair:
                old = parent["by_key"][case.question.identity, arm]
                latest = key_map[case.question.identity, arm]
                if latest["status"] != "succeeded":
                    details.append(
                        dict(
                            qid=case.question.identity,
                            arm=arm,
                            status="unknown",
                            strict64=None,
                            strict128=None,
                        )
                    )
                    continue
                sel = select(arm, case.question, case.documents)
                a, b = (
                    score(case, sel, old["answer"]),
                    score(case, sel, latest["answer"]),
                )
                old_valid += bool(a["strict_success"])
                new_valid += bool(b["strict_success"])
                old_exact += bool(a["raw_answer_exact"])
                new_exact += bool(b["raw_answer_exact"])
                old_abstain += bool(a["raw_abstention_exact"])
                new_abstain += bool(b["raw_abstention_exact"])
                original_cap += old["reader"]["generated_tokens"] == BASELINE_CAP
                output_cap += latest["receipt"]["generated_tokens"] == GENERATION_CAP
                details.append(
                    dict(
                        qid=case.question.identity,
                        arm=arm,
                        status="succeeded",
                        complete=a["programmatic_evidence_sufficient"],
                        strict64=a["strict_success"],
                        strict128=b["strict_success"],
                        exact64=a["raw_answer_exact"],
                        exact128=b["raw_answer_exact"],
                        abstain64=a["raw_abstention_exact"],
                        abstain128=b["raw_abstention_exact"],
                        token64=old["reader"]["generated_tokens"],
                        token128=latest["receipt"]["generated_tokens"],
                        same_first64=latest["prefix_match"],
                    )
                )
        summary.append(
            dict(
                arm=arm,
                planned=32,
                completed=sum(
                    d["status"] == "succeeded" for d in details if d["arm"] == arm
                ),
                strict64=old_valid,
                strict128=new_valid,
                raw_answer_exact64=old_exact,
                raw_answer_exact128=new_exact,
                abstentions64=old_abstain,
                abstentions128=new_abstain,
                original_generation_cap_hit=original_cap,
                extended_generation_cap_hit=output_cap,
            )
        )
    return details, summary


def run(source, output, reader, *, source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact generating Git commit required")
    parent = load_parent(source)
    if reader.identity != READER_ID:
        raise ValueError("changed pre-trained model inventory")
    reader.verify_frozen()
    output.mkdir(parents=True, exist_ok=False)
    entries = [
        (j, v, case, arm)
        for j, pair in enumerate(parent["pairs"])
        for v, case in enumerate(pair)
        for arm in NEW_ARMS
    ]
    entries.sort(
        key=lambda z: (
            z[0],
            (
                z[1] * len(NEW_ARMS)
                + NEW_ARMS.index(z[3])
                + int(digest(z[2].question.identity)[:8], 16)
            )
            % (2 * len(NEW_ARMS)),
        )
    )
    write(
        output / "plan.json",
        dict(
            schema="hepta.system2.decode-ceiling.v1",
            source_commit=source_commit,
            parent_commit=PARENT_COMMIT,
            parent_zip_sha256=PARENT_SHA256,
            parent_raw_seal=PARENT_RAW_SEAL,
            arms=list(NEW_ARMS),
            questions=[
                case.question.identity for pair in parent["pairs"] for case in pair
            ],
            planned=PLANNED,
            old_max_new_tokens=BASELINE_CAP,
            new_max_new_tokens=GENERATION_CAP,
            unchanged_tokenizer_reader_prompt=True,
            no_answer_labels_available_during_generation=True,
            decode_work_budget_increased=True,
            independent_human_judgment=False,
            production_accepted=False,
        ),
    )
    records = []
    try:
        for j, v, case, arm in entries:
            row = dict(
                qid=case.question.identity,
                arm=arm,
                pair_index=j,
                variant=v,
                source_manifest=source_manifest(case),
                status="started",
            )
            append(output / "starts.jsonl", row)
            try:
                selected = select(arm, case.question, case.documents)
                bundle, originals, frontier = evidence(case, selected, arm)
                row["selected"] = [d.identity for d in selected]
                answer, receipt = decode_128(
                    reader, case.question, bundle, originals, frontier=frontier
                )
                previous = parent["by_key"][case.question.identity, arm]
                row["prefix_match"] = match_historical(previous, receipt, answer)
                row.update(answer=answer, receipt=receipt, status="succeeded")
            except BaseException as exc:
                row.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    incomplete_cost_unknown=True,
                )
                records.append(row)
                append(output / "raw-answers.jsonl", row)
                if not isinstance(exc, Exception):
                    raise
                continue
            records.append(row)
            append(output / "raw-answers.jsonl", row)
        raw = (output / "raw-answers.jsonl").read_bytes()
        seal = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=seal, rows=len(records), scoring_started=False),
        )
        if any(r["status"] != "succeeded" for r in records):
            write(
                output / "failures.json",
                dict(
                    planned=PLANNED,
                    attempted=len(records),
                    failed=sum(r["status"] != "succeeded" for r in records),
                    incomplete_work_not_free=True,
                ),
            )
            raise RuntimeError("decode ceiling trial has incomplete model attempts")
        reader.verify_frozen()
        details, summary = assess(records, parent)
        write(output / "scored.json", details)
        write(
            output / "summary.json",
            dict(
                planned=PLANNED,
                recorded=len(records),
                failed=0,
                source_commit=source_commit,
                arms=summary,
                conclusion="decode-only developmental diagnostic, not compute matched",
                independent_human_judgment=False,
                production_accepted=False,
            ),
        )
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != seal
        ):
            raise ValueError("immutable raw answer seal drift")
        return summary
    except BaseException as exc:
        if not (output / "run-failure.json").exists():
            write(
                output / "run-failure.json",
                dict(
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    attempted=len(records),
                    planned=PLANNED,
                    unknown_work_not_imputed=True,
                ),
            )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("reader_directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if not args.development:
        raise ValueError("explicit development-only run required")
    from bundle_reader import FrozenBundleReader
    from stem_cell_trial import READER

    reader = FrozenBundleReader(args.reader_directory, expected_inventory=READER)
    result = run(
        args.source_zip,
        args.output,
        reader,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    reader.verify_frozen()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
