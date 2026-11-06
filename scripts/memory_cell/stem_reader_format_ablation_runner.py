"""Execute exactly 32 frozen Reader format-only trials from one pinned run.

No original six-arm decision is rewritten. The native benchmark labels are
loaded only after all new raw answers, including failures, have been sealed.
This script never evaluates or fits a Cell, and has no production interface.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import time

import torch

from native import digest, load
from pretrained import file_inventory
from selector_answering import FrozenAnswerGenerator, GENERATION, SYSTEM
from selector_evaluation import diagnose
from stem_audit_archive import PinnedArchive, require
from stem_reader_format_ablation import (
    ARCHIVED_SOURCE,
    ARCHIVED_TREE,
    ARCHIVED_ZIP_SHA256,
    FORMAT_ID,
    PHASES,
    fixed_frozen_cases,
    flat_user_message,
    evaluate_flat_answers,
)


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def append(path, row):
    with path.open("a", encoding="utf-8") as stream:
        json.dump(row, stream, ensure_ascii=False, allow_nan=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


@torch.no_grad()
def flat_generate(reader, case):
    """Exact same frozen decoder, changed fixed user-payload presentation only."""
    if reader.quarantined:
        raise ValueError("frozen format control Reader quarantined")
    q = case["question"]
    evidence = case["delivered_evidence"]
    user_text = flat_user_message(q, evidence)
    messages = [
        dict(role="system", content=SYSTEM),
        dict(role="user", content=user_text),
    ]
    ids = reader.tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True
    )
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 1024
        or any(type(x) is not int or x < 0 for x in ids)
    ):
        raise ValueError("bounded original Reader input tokens; no truncation")
    if (
        reader.identity != case["original_reader_identity"]
        or reader.profile != case["original_reader_profile"]
    ):
        raise ValueError("Reader weight/prompt identity changed from pinned execution")
    profile = digest(
        (
            SYSTEM,
            GENERATION,
            reader.tokenizer.chat_template,
            FORMAT_ID,
        )
    )
    if profile == reader.profile:
        raise ValueError("new prompt layout not separately identified")
    started = time.perf_counter()
    try:
        inp = torch.tensor([ids], dtype=torch.long)
        output = reader.model.generate(
            input_ids=inp,
            attention_mask=torch.ones_like(inp),
            **GENERATION,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id,
        )
        emitted = output[0, len(ids) :].tolist()
        answer = reader.tokenizer.decode(
            emitted,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty frozen Reader output")
        return answer, dict(
            generator_identity=reader.identity,
            original_reader_profile=reader.profile,
            flat_reader_profile=profile,
            input_ids_digest=digest(ids),
            generated_ids_digest=digest(emitted),
            question_digest=digest(q),
            delivered_evidence=evidence,
            evidence_count=1,
            input_tokens=len(ids),
            generated_tokens=len(emitted),
            generation_seconds=time.perf_counter() - started,
            generator_parameter_updates=0,
            decoded_max_new_tokens=GENERATION["max_new_tokens"],
            reached_token_ceiling=len(emitted) == GENERATION["max_new_tokens"],
            same_system_instruction=True,
            same_generator_weights=True,
            original_json_user_payload_preserved=False,
            new_flat_user_payload_only=True,
            new_flat_user_message_digest=digest(user_text),
            output_not_postprocessed=True,
            semantic_citation_precision=None,
            production_accepted=False,
        )
    except Exception:
        reader.quarantined = True
        raise


def run(staged, archived_zip, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    archive = PinnedArchive(archived_zip, ARCHIVED_ZIP_SHA256)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == ARCHIVED_SOURCE
            and archive.read("tested-tree.txt").decode().strip() == ARCHIVED_TREE,
            "original strict Stem source/tree identity drift",
        )
        plan = archive.json("comparison/preregistered.json")
        cases = fixed_frozen_cases(
            plan, archive.jsonl("comparison/policy-predictions.jsonl")
        )
        if (
            digest(SYSTEM) != plan["generator_template_digest"]
            or GENERATION != plan["generator_config"]
        ):
            raise ValueError("frozen original system prompt or generation budget drift")
        # Register cases and all source-byte hashes before any model call.
        write(
            output / "preregistered-flat-control.json",
            dict(
                schema="hepta.stem-flat-reader-experiment.preregistered.v1",
                original_archive_sha256=ARCHIVED_ZIP_SHA256,
                original_source=ARCHIVED_SOURCE,
                original_tree=ARCHIVED_TREE,
                registered_question_ids=[x["question_id"] for x in cases],
                phase_order=list(PHASES),
                sole_intervention="JSON-user-payload-to-flat-user-payload",
                system_digest=digest(SYSTEM),
                generation=GENERATION,
                expected_reader_inventory=plan["reader_inventory"],
                original_request_digests=[
                    x["original_canonical_request_sha256"] for x in cases
                ],
                evidence_bytes_changed=False,
                gold_answers_read_before_generation=False,
                model_training_permitted=False,
                production_accepted=False,
            ),
        )
        reader_load_started = time.perf_counter()
        reader = FrozenAnswerGenerator(
            staged / "reader", expected_inventory=plan["reader_inventory"]
        )
        load_seconds = time.perf_counter() - reader_load_started
        require(
            reader.inventory == file_inventory(staged / "reader")
            and all(
                reader.identity == x["original_reader_identity"]
                and reader.profile == x["original_reader_profile"]
                for x in cases
            ),
            "Reader weights/prompt/tokenizer differ from original",
        )
        raw = []
        for case in cases:
            row = dict(
                schema="hepta.stem-flat-format-answer.v1",
                phase=case["phase"],
                question_id=case["question_id"],
                case_original_digest=digest(case),
                original_reader_identity=case["original_reader_identity"],
                original_reader_profile=case["original_reader_profile"],
                previous_answer_sha256=case["original_answer_sha256"],
                source_count=1,
                training_or_policy_mutation=False,
            )
            try:
                answer, receipt = flat_generate(reader, case)
                row.update(status="succeeded", answer=answer, receipt=receipt)
            except Exception as error:
                row.update(
                    status="failed",
                    error_type=type(error).__name__,
                    error=str(error)[:1024],
                )
            append(output / "flat-answers.jsonl", row)
            raw.append(row)
        with (output / "flat-answers.jsonl").open("rb") as stream:
            raw_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        reader_frozen_after = False
        if not reader.quarantined:
            reader.verify_frozen()
            reader_frozen_after = True
        # Everything above completes before the published answer targets
        # are opened. These are diagnostic token-F1 values, not official QA.
        info = json.loads((staged / "staging.json").read_text())
        datasets = {
            name: load(
                staged / f"{name}.json",
                name,
                info[name]["sha256"],
                allow_unresolved_evidence=True,
                session_conflicts="retain-versioned",
                invalid_history="quarantine-question",
                empty_turns="preserve",
            )
            for name in ("locomo", "longmemeval")
        }
        targets = {
            qid: bench.targets[qid]
            for bench in datasets.values()
            for qid in (x["question_id"] for x in cases)
            if qid in bench.targets
        }
        report = evaluate_flat_answers(
            cases,
            raw,
            archive.json("comparison/scored-policy-attempts.json"),
            targets,
            diagnose,
        )
        report.update(
            original_strict_reader_zip_sha256=ARCHIVED_ZIP_SHA256,
            tested_control_source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT"),
            raw_generation_file_sha256=raw_sha256,
            reader_reloaded_from_original_pinned_model=True,
            frozen_reader_verified_after_run=reader_frozen_after,
            control_reader_cold_load_seconds=load_seconds,
            control_reader_successful_generations=sum(
                x["status"] == "succeeded" for x in raw
            ),
            control_reader_attempts_excluding_preflight_unmeasured=True,
            control_reader_failed_questions=sum(x["status"] == "failed" for x in raw),
            control_generation_seconds=sum(
                x.get("receipt", {}).get("generation_seconds", 0.0) for x in raw
            ),
            total_elapsed_seconds=time.perf_counter() - started,
            process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            production_accepted=False,
        )
        write(output / "flat-vs-json-evaluation.json", report)
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
        if any(x["status"] != "succeeded" for x in raw):
            raise RuntimeError("incomplete flat Reader control; failure rows retained")
        return report
    finally:
        archive.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staged", type=Path)
    parser.add_argument("original_archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.staged, args.original_archive, args.output)
