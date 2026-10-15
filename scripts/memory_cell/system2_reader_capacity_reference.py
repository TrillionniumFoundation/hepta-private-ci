"""Pinned stronger-frozen-Reader capacity control on exact one-hop evidence.

This is deliberately NOT matched FLOPs or proof that an NDU/Cell learned anything.
The same 20 formerly exposed questions plus 20 fixed disjoint new synthetic
questions, same evidence selectors and answer-only instruction, but a DIFFERENT
pretrained Reader and tokenizer. All original baseline answers are immutable.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import re
import time

from system2_multihop_evidence import digest, make_case, parse_relation
from system2_multihop_trial import ABSTAIN, TOKEN_RE, evidence
from system2_onehop_reader import OneHopCase, cases, select
from system2_onehop_cardinality import choose_onehop
from system2_onehop_label_ablation import (
    LABEL_ONLY,
    MAX_NEW_TOKENS,
    READER_IDENTITY,
    SYSTEM,
    TOKEN_LIMIT,
    prompt_messages,
)
from system2_native_receipt import strict_json, verified_archive
from system2_onehop_label_pair_audit import audit as validate_old_label_census

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REV = "a338b55dd21219a5f4da42bc11a9313d1a27d4cc"
MODEL_FILES = ("model.safetensors", "config.json", "tokenizer_config.json")
ARMS = ("single_fact", "target_decoy_two_first", "decoy_one", "no_evidence")
COHORTS = ("exposed_20", "fixed_new_20")
CASE_COUNT = 20
LABEL_PARENT_SHA = "a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a"
LABEL_PARENT_COMMIT = "24a1175958870816e40c7c62bbe1421b83e55dbd"
LABEL_PARENT_TREE = "84689f6c75dc35b8e9ff515be32094182438fa05"
LABEL_RAW_SHA = "6f630a86d374658049377d4611f92fd6c0dd6626c267eef7c37d77f07f5aeaa2"
PLAN_SIZE = len(ARMS) * len(COHORTS) * CASE_COUNT
REV_HASH = re.compile(r"[0-9a-f]{40}\Z")


def write(path, item):
    with path.open("x", encoding="utf8") as f:
        json.dump(
            item, f, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        f.write("\n")


def append(path, item):
    with path.open("a", encoding="utf8") as f:
        f.write(
            json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        )
        f.flush()
        os.fsync(f.fileno())


def fixed_new_cases():
    """Freeze positions 20:40; evaluation cases do not supply model targets."""
    out = []
    for i in range(20, 40):
        base = make_case(i)
        matches = [
            (doc, relation[1])
            for doc in base.documents
            if (relation := parse_relation(doc))
            and relation[0] == "device"
            and relation[2] == "token"
            and relation[3] == base.answer
        ]
        if len(matches) != 1:
            raise ValueError("new one-hop truth cannot be uniquely registered")
        doc, device = matches[0]
        question_id = "onehop:" + digest((base.question.identity, device))[:24]
        question = replace(
            base.question,
            identity=question_id,
            family="synthetic-single-hop",
            content=f"Which clearance token is required by device {device}?",
        )
        out.append(
            OneHopCase(
                question,
                base.documents,
                base.answer,
                doc.identity,
                base.question.identity,
            )
        )
    if len(out) != CASE_COUNT or len({c.question.identity for c in out}) != CASE_COUNT:
        raise ValueError("fixed new question cohort drift")
    return tuple(out)


def cohorts():
    old, new = cases(), fixed_new_cases()
    if (
        len(old) != CASE_COUNT
        or len(new) != CASE_COUNT
        or {c.question.identity for c in old} & {c.question.identity for c in new}
    ):
        raise ValueError("new and previously exposed question IDs overlap")
    return dict(zip(COHORTS, (old, new), strict=True))


def selected(case, arm):
    """Only query and eligible source bytes used, never the target answer."""
    if arm not in ARMS:
        raise ValueError("unknown evidence arm")
    if arm in ("single_fact", "no_evidence"):
        return select(case.question, case.documents, arm)
    return choose_onehop(case, arm)


def load_baseline_archives(cardinality_archive, label_archive):
    """Two externally SHA-pinned hosted archives + fully replayed 140-cell audit."""
    files = verified_archive(Path(label_archive), LABEL_PARENT_SHA)
    if (
        files["tested-commit.txt"].decode().strip() != LABEL_PARENT_COMMIT
        or files["tested-tree.txt"].decode().strip() != LABEL_PARENT_TREE
    ):
        raise ValueError("baseline 140-answer generating source drift")
    seal = strict_json(files["trial/raw-seal.json"])
    raw = files["trial/raw-answers.jsonl"]
    if (
        seal != dict(sha256=LABEL_RAW_SHA, rows=140, scoring_started=False)
        or hashlib.sha256(raw).hexdigest() != LABEL_RAW_SHA
    ):
        raise ValueError("baseline original Reader predictions altered")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        # The archive is already SHA-checked; write only a fixed approved list.
        for name in (
            "plan.json",
            "starts.jsonl",
            "raw-answers.jsonl",
            "raw-seal.json",
            "scored.json",
            "summary.json",
        ):
            (root / name).write_bytes(files["trial/" + name])
        audit = validate_old_label_census(
            root, cardinality_archive, generating_commit=LABEL_PARENT_COMMIT
        )
    if audit["original_seal"] != LABEL_RAW_SHA or audit["planned_model_calls"] != 140:
        raise ValueError("baseline provenance audit did not cover all prompts")
    rows = [strict_json(line) for line in raw.splitlines()]
    by_key = {(r["qid"], r["arm"], r["presentation"]): r for r in rows}
    if len(by_key) != 140:
        raise ValueError("duplicate baseline reader cells")
    return dict(
        by_key=by_key,
        raw_sha256=LABEL_RAW_SHA,
        verified_files=len(files) - 1,
        original_audit_schema=audit["schema"],
    )


def study_plan(groups, source_commit, baseline_seal):
    if not isinstance(source_commit, str) or not REV_HASH.fullmatch(source_commit):
        raise ValueError("exact generating commit required")
    return dict(
        schema="hepta.system2.strong-frozen-reader-floor.v1",
        generating_commit=source_commit,
        reference_model=MODEL_ID,
        reference_revision=MODEL_REV,
        existing_135m_reader_id=READER_IDENTITY,
        historical_raw_seal=baseline_seal,
        cohorts={
            name: [case.question.identity for case in group]
            for name, group in groups.items()
        },
        source_manifest={
            case.question.identity: digest(
                [
                    (d.identity, d.root, d.scope, d.observed_at, d.content)
                    for d in case.documents
                ]
            )
            for group in groups.values()
            for case in group
        },
        arms=list(ARMS),
        planned=PLAN_SIZE,
        prompt_system=SYSTEM,
        evidence_presentation="labeled",
        generation=dict(
            max_new_tokens=MAX_NEW_TOKENS, do_sample=False, num_beams=1, use_cache=True
        ),
        input_limit=TOKEN_LIMIT,
        new_model_training=False,
        learning_updates=0,
        same_prompt_text_and_evidence=True,
        tokenizer_and_model_differ=True,
        compute_and_tokenizer_matched=False,
        synthetic_data_not_independent_natural_language=True,
        production_accepted=False,
    )


def outcome(case, arm, answer):
    if arm not in ARMS or type(answer) is not str or not answer.strip():
        raise ValueError("unregistered or empty answer")
    has_support = arm in ("single_fact", "target_decoy_two_first")
    answer_only = answer.strip() == case.answer
    refusal = answer.strip() == ABSTAIN
    return dict(
        sufficient_evidence=has_support,
        exact_answer_only=answer_only,
        correct_token_mentioned=case.answer in answer.upper(),
        correct_refusal=refusal,
        unsupported_token_copy=not has_support
        and bool(TOKEN_RE.findall(answer.upper())),
        label_only_echo=bool(LABEL_ONLY.fullmatch(answer)),
        conditional_success=(answer_only if has_support else refusal),
        model_generated_citations_required=False,
        independent_human_semantic_judgment=False,
    )


def score(rows, groups):
    planned = {
        (case.question.identity, arm)
        for group in groups.values()
        for case in group
        for arm in ARMS
    }
    keys = [(r["qid"], r["arm"]) for r in rows]
    if len(keys) != len(planned) or len(set(keys)) != len(keys) or set(keys) != planned:
        raise ValueError("missing/extra/duplicate Reader conditions")
    cmap = {
        case.question.identity: (cohort, case)
        for cohort, group in groups.items()
        for case in group
    }
    scored = []
    for row in rows:
        cohort, case = cmap[row["qid"]]
        if row["cohort"] != cohort:
            raise ValueError("source cohort altered")
        docs = selected(case, row["arm"])
        if row.get("selected") != [d.identity for d in docs]:
            raise ValueError("delivered evidence drift")
        if row["status"] == "failed":
            scored.append(
                dict(
                    qid=row["qid"],
                    cohort=cohort,
                    arm=row["arm"],
                    status="failed",
                    conditional_success=None,
                )
            )
        elif row["status"] == "succeeded":
            scored.append(
                dict(
                    qid=row["qid"],
                    cohort=cohort,
                    arm=row["arm"],
                    status="succeeded",
                    **outcome(case, row["arm"], row["answer"]),
                )
            )
        else:
            raise ValueError("invalid result status")
    summary = []
    for cohort, cases_ in groups.items():
        for arm in ARMS:
            sample = [r for r in scored if r["cohort"] == cohort and r["arm"] == arm]
            valid = [r for r in sample if r["status"] == "succeeded"]
            if len(sample) != len(cases_):
                raise ValueError("unexpected group denominator")
            summary.append(
                dict(
                    cohort=cohort,
                    arm=arm,
                    planned=len(sample),
                    completed=len(valid),
                    failed=len(sample) - len(valid),
                    exact_answer_only=sum(r["exact_answer_only"] for r in valid),
                    exact_refusals=sum(r["correct_refusal"] for r in valid),
                    target_literal_mentions=sum(
                        r["correct_token_mentioned"] for r in valid
                    ),
                    unsupported_token_copies=sum(
                        r["unsupported_token_copy"] for r in valid
                    ),
                    label_only_echoes=sum(r["label_only_echo"] for r in valid),
                    conditional_success=sum(r["conditional_success"] for r in valid),
                    unknown_failed_attempts_not_zero_scored=True,
                )
            )
    return scored, summary


class PinnedReferenceReader:
    """No trainable parameters or remote code; model/version differs by design."""

    def __init__(self, directory, *, recorded_revision=MODEL_REV):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from pretrained import file_inventory, frozen_digest

        if recorded_revision != MODEL_REV or not REV_HASH.fullmatch(recorded_revision):
            raise ValueError("unpinned reference model revision")
        directory = Path(directory)
        self.model_directory = directory
        self.inventory = file_inventory(directory)
        if any(name not in self.inventory for name in MODEL_FILES):
            raise ValueError("incomplete pinned reference model files")
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
        if not self.tokenizer.chat_template or self.tokenizer.eos_token_id is None:
            raise ValueError("reference requires registered chat template")
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                directory,
                local_files_only=True,
                trust_remote_code=False,
                use_safetensors=True,
                dtype=torch.float32,
            )
            .eval()
            .requires_grad_(False)
        )
        self.base_digest = frozen_digest(self.model)
        self.identity = digest((MODEL_ID, MODEL_REV, self.inventory, self.base_digest))
        self.profile = digest(
            (MODEL_ID, MODEL_REV, SYSTEM, MAX_NEW_TOKENS, self.tokenizer.chat_template)
        )
        self.param_count = sum(p.numel() for p in self.model.parameters())

    def answer(self, case, docs, arm):
        import torch
        from native import digest as native_digest

        bundle, original, frontier = evidence(case, docs, arm)
        bundle.validate(case.question, original, frontier=frontier, revoked=set())
        delivered = bundle.delivered()
        ids = self.tokenizer.apply_chat_template(
            prompt_messages(case.question, delivered, "labeled"),
            tokenize=True,
            add_generation_prompt=True,
        )
        if not ids or len(ids) > TOKEN_LIMIT:
            raise ValueError("reference input exceeds preregistered token cap")
        if len(ids) + MAX_NEW_TOKENS > self.model.config.max_position_embeddings:
            raise ValueError("reference context too small")
        inp = torch.tensor([ids], dtype=torch.long)
        start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
        with torch.inference_mode():
            generated = self.model.generate(
                input_ids=inp,
                attention_mask=torch.ones_like(inp),
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                num_beams=1,
                use_cache=True,
                eos_token_id=self.tokenizer.eos_token_id,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        cost = dict(
            cpu_ns=time.process_time_ns() - start_cpu,
            wall_ns=time.perf_counter_ns() - start_wall,
        )
        tokens = generated[0, len(ids) :].tolist()
        if not 1 <= len(tokens) <= MAX_NEW_TOKENS:
            raise ValueError("invalid frozen reference decoding length")
        answer = self.tokenizer.decode(
            tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        if not answer.strip():
            raise ValueError("blank Reader output")
        bundle.validate(case.question, original, frontier=frontier, revoked=set())
        return answer, dict(
            reader_identity=self.identity,
            reader_profile=self.profile,
            model_id=MODEL_ID,
            model_revision=MODEL_REV,
            generated_ids_digest=native_digest(tokens),
            input_ids_digest=native_digest(ids),
            generated_tokens=len(tokens),
            input_tokens=len(ids),
            bundle_digest=bundle.seal(),
            question_digest=native_digest(asdict(case.question)),
            delivered_evidence=delivered,
            token_limit=TOKEN_LIMIT,
            trainable_parameters=0,
            answer_postprocessed=False,
            cpu_time_ns=cost["cpu_ns"],
            wall_time_ns=cost["wall_ns"],
            production_accepted=False,
        )

    def verify_frozen(self):
        from pretrained import frozen_digest, file_inventory

        if (
            self.model.training
            or any(p.requires_grad for p in self.model.parameters())
            or frozen_digest(self.model) != self.base_digest
        ):
            raise ValueError("reference reader weights changed")
        if file_inventory(self.model_directory) != self.inventory:
            raise ValueError("reference checkpoint files changed")


def run(
    output, reader, *, cardinality_archive, label_archive, source_commit, groups=None
):
    """Models/choices are fixed before target-dependent post-seal scoring."""
    groups = cohorts() if groups is None else groups
    parent = load_baseline_archives(cardinality_archive, label_archive)
    baseline = parent["by_key"]
    all_cases = [
        (cohort, case, arm)
        for cohort, sample in groups.items()
        for case in sample
        for arm in ARMS
    ]
    if len(all_cases) != sum(len(v) for v in groups.values()) * len(ARMS) or len(
        {case.question.identity for _, case, _ in all_cases}
    ) * len(ARMS) != len(all_cases):
        raise ValueError("duplicate planned question identity")
    output.mkdir(parents=True, exist_ok=False)
    plan = study_plan(groups, source_commit, parent["raw_sha256"])
    plan["planned"] = len(all_cases)
    plan["reference_reader_identity"] = reader.identity
    plan["reference_reader_profile"] = reader.profile
    plan["reference_reader_parameters"] = reader.param_count
    plan["reference_reader_inventory"] = reader.inventory
    write(output / "plan.json", plan)
    all_cases.sort(
        key=lambda item: (
            item[1].question.identity,
            (ARMS.index(item[2]) + int(digest(item[1].question.identity)[:8], 16))
            % len(ARMS),
        )
    )
    rows = []
    try:
        for cohort, case, arm in all_cases:
            row = dict(
                qid=case.question.identity, cohort=cohort, arm=arm, status="started"
            )
            append(output / "starts.jsonl", row)
            try:
                docs = selected(case, arm)
                row["selected"] = [d.identity for d in docs]
                ans, rec = reader.answer(case, docs, arm)
                bundle, _, _ = evidence(case, docs, arm)
                if (
                    not isinstance(ans, str)
                    or not ans.strip()
                    or rec["reader_identity"] != reader.identity
                    or rec["reader_profile"] != reader.profile
                    or rec["bundle_digest"] != bundle.seal()
                    or rec["delivered_evidence"] != bundle.delivered()
                    or rec["trainable_parameters"] != 0
                    or rec["answer_postprocessed"] is not False
                    or rec["token_limit"] != TOKEN_LIMIT
                ):
                    raise ValueError("reference identity/evidence/Reader changed")
                row.update(status="succeeded", answer=ans, reader=rec)
            except BaseException as e:
                row.update(
                    status="failed",
                    error_type=type(e).__name__,
                    error=str(e)[:512],
                    unknown_cost=True,
                )
                append(output / "raw-answers.jsonl", row)
                raise
            append(output / "raw-answers.jsonl", row)
            rows.append(row)
        raw = (output / "raw-answers.jsonl").read_bytes()
        seal = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=seal, rows=len(rows), scoring_started=False),
        )
        scored, summary = score(rows, groups)
        baseline_result = []
        for case in groups.get("exposed_20", []):
            for arm in ARMS:
                presentation = "unlabeled" if arm == "no_evidence" else "labeled"
                old = baseline[case.question.identity, arm, presentation]
                if old["status"] != "succeeded":
                    raise ValueError("original 135M baseline incomplete")
                baseline_result.append(
                    dict(
                        qid=case.question.identity,
                        arm=arm,
                        baseline_135m_answer=old["answer"],
                        **outcome(case, arm, old["answer"]),
                    )
                )
        verdict = all(
            any(
                s["cohort"] == cohort
                and s["arm"] == arm
                and s["completed"] == CASE_COUNT
                and s["conditional_success"] >= (15 if arm in ARMS[:2] else 18)
                for s in summary
            )
            for cohort in COHORTS
            for arm in ARMS
        )
        report = dict(
            planned=len(all_cases),
            recorded=len(rows),
            failed=0,
            generating_commit=source_commit,
            source_135m_raw_seal_sha256=parent["raw_sha256"],
            baseline_135m=baseline_result,
            by_arm=summary,
            full_model_inference_cpu_ns=sum(r["reader"]["cpu_time_ns"] for r in rows),
            full_model_inference_output_tokens=sum(
                r["reader"]["generated_tokens"] for r in rows
            ),
            candidate_disposition="independent_natural_reader_confirmation_required"
            if verdict
            else "reader_capacity_reference_not_qualified",
            general_NDU_FBSDE_gain=False,
            production_accepted=False,
            compute_and_tokenizer_matched=False,
        )
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != seal
        ):
            raise ValueError("raw output mutated after scoring")
        if hasattr(reader, "verify_frozen"):
            reader.verify_frozen()
        write(output / "scored.json", scored)
        write(output / "summary.json", report)
        return report
    except BaseException as exc:
        write(
            output / "run-failure.json",
            dict(
                planned=len(all_cases),
                completed=len(rows),
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                unrecorded_work_not_free=True,
                full_results_unavailable=True,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cardinality_archive", type=Path)
    parser.add_argument("label_archive", type=Path)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if not args.development:
        raise ValueError("only registered research diagnostic permitted")
    reader = PinnedReferenceReader(args.model_dir)
    report = run(
        args.output,
        reader,
        cardinality_archive=args.cardinality_archive,
        label_archive=args.label_archive,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("planned", "recorded", "failed", "candidate_disposition")
            }
        )
    )


if __name__ == "__main__":
    main()
