"""Real, isolated frozen Reader one-vs-two-source development diagnostic.

Pins the completed strict-as-of six-arm experiment, replays its original
retriever/index/frozen pair Encoder on the 16 registered test+transfer tasks,
and appends a DIFFERENT frozen-scored source window E2 without consulting
native answer/support annotations. Compare the same-host original E1-only
answer to E1+E2, with original frozen weights, system prompt and decoder
budget. No original policy answer/Head/Adapter/retriever is modified.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import tempfile
import time

import torch

from index import PersistentIndex, RetrievalPolicy
from native import digest, load
from pretrained import Encoder, file_inventory
from selector_answering import (
    FrozenAnswerGenerator, GENERATION, SYSTEM,
)
from selector_encoder import FrozenPairEncoder
from selector_evaluation import diagnose
from selector_windows import WindowBudget, candidate_windows
from stem_audit_archive import PinnedArchive, require
from stem_two_window_reader_plan import (
    prepare_second_window, compare_capacity_rows,
)

ARCHIVED_SOURCE = "675970bb610c70bb0ec30a2dee05c025440510e6"
ARCHIVED_TREE = "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb"
ARCHIVED_ZIP = "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8"
PHASES = ("test", "transfer")
INPUT_CEILING = 1024


def write(path, obj):
    with path.open("x", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        f.write("\n")


def append(path, obj):
    with path.open("a", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, allow_nan=False, sort_keys=True)
        f.write("\n")


@torch.no_grad()
def answer_two(reader, question, evidence, *, revoked):
    """Copy the original E1 Reader serialization with an additional bound E2.

    The original FrozenAnswerGenerator.answer() intentionally rejects >1;
    do not change that serving/primary-experiment contract.
    """
    from stem_cell_time import source_not_after_question

    if reader.quarantined or len(evidence) != 2 or set(
        item["label"] for item in evidence
    ) != {"E1", "E2"} or evidence[0]["label"] != "E1":
        raise ValueError("isolated two-window Reader requires one E1 and one E2")
    if (
        evidence[0]["root"] == evidence[1]["root"]
        or evidence[0]["original_id"] == evidence[1]["original_id"]
    ):
        raise ValueError("second window not from distinct source root/session")
    for src in evidence:
        if (
            src["root"] in revoked or src["scope"] != question.scope
            or not source_not_after_question(
                src["observed_at"], question.observed_at
            )
        ):
            raise ValueError("withdrawn, future or cross-scope E2 evidence")
    body = dict(
        question=question.content,
        question_time=question.observed_at,
        evidence=[
            dict(label=s["label"], observed_at=s["observed_at"], text=s["excerpt"])
            for s in evidence
        ],
    )
    messages = [
        dict(role="system", content=SYSTEM),
        dict(role="user", content=json.dumps(body, ensure_ascii=False)),
    ]
    ids = reader.tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True
    )
    if not 1 <= len(ids) <= INPUT_CEILING:
        raise ValueError("extra evidence exceeded original Reader input ceiling")
    started = time.perf_counter()
    try:
        x = torch.tensor([ids], dtype=torch.long)
        answer = reader.model.generate(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            **GENERATION,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id,
        )
        emitted = answer[0, len(ids):].tolist()
        raw = reader.tokenizer.decode(
            emitted, skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        if not raw.strip():
            raise ValueError("empty actually generated two-source answer")
        return raw, dict(
            generator_identity=reader.identity,
            generator_profile=reader.profile,
            input_ids_digest=digest(ids),
            generated_ids_digest=digest(emitted),
            question_digest=digest(asdict(question)),
            delivered_evidence=list(evidence),
            input_tokens=len(ids),
            generated_tokens=len(emitted),
            generation_seconds=time.perf_counter() - started,
            reached_token_ceiling=len(emitted) == GENERATION["max_new_tokens"],
            generator_parameter_updates=0,
            answer_postprocessed=False,
            same_original_SYSTEM_and_GENERATION=True,
            E2_nonproduction_research_control=True,
            semantic_citation_precision=None,
            production_accepted=False,
        )
    except Exception:
        reader.quarantined = True
        raise


def run(staged, ranker_dir, zipped, output):
    staged, ranker_dir, zipped, output = map(
        Path, (staged, ranker_dir, zipped, output)
    )
    original = PinnedArchive(zipped, ARCHIVED_ZIP)
    try:
        require(
            original.read("tested-commit.txt").decode().strip() == ARCHIVED_SOURCE
            and original.read("tested-tree.txt").decode().strip() == ARCHIVED_TREE,
            "original completed strict six-arm executable identity mismatch",
        )
        plan = original.json("comparison/preregistered.json")
        require(
            plan["source_commit"] == ARCHIVED_SOURCE
            and plan["source_visibility_policy"]
            == "strict-as-of-before-index-and-every-Encoder-v1"
            and plan["generator_config"] == GENERATION
            and plan["generator_template_digest"] == digest(SYSTEM)
            and plan["window_budget"]["candidates"] == 32
            and len(plan["questions"]["test"]) == 8
            and len(plan["questions"]["transfer"]) == 8,
            "changed preregistered frozen Reader/selection protocol",
        )
        expected = {
            (phase, qid) for phase in PHASES
            for qid in plan["questions"][phase]
        }
        require(len(expected) == 16, "original test/transfer question overlap")
        frozen = {}
        for item in original.jsonl("comparison/policy-predictions.jsonl"):
            if item["stage"] != 48 or item["arm"] != "frozen_rerank":
                continue
            key = item["phase"], item["question_id"]
            if key not in expected:
                continue
            require(key not in frozen, "duplicate original frozen baseline")
            require(item["status"] == "succeeded"
                    and type(item["selected"]) is int,
                    "original frozen answer missing or had no top1 selection")
            frozen[key] = item
        require(set(frozen) == expected, "incomplete original frozen test/transfer")
        meta = json.loads((staged / "staging.json").read_text())
        benchmarks = {
            name: load(
                staged / f"{name}.json", name, meta[name]["sha256"],
                allow_unresolved_evidence=True,
                session_conflicts="retain-versioned",
                invalid_history="quarantine-question",
                empty_turns="preserve",
            )
            for name in ("locomo", "longmemeval")
        }
        require(
            all(benchmarks[k].source_sha256 == plan["dataset_sha256"][k]
                for k in benchmarks),
            "original native corpus file byte hash drift",
        )
        queries = {}
        owners = {}
        for source in benchmarks.values():
            for q in source.questions:
                if any((phase, q.identity) in expected for phase in PHASES):
                    require(q.identity not in queries, "duplicate source-backed question")
                    queries[q.identity], owners[q.identity] = q, source
        require(set(queries) == {qid for _, qid in expected},
                "registered original question unavailable")

        output.mkdir(parents=True, exist_ok=False)
        write(output / "preregistered.json", dict(
            schema="hepta.stem-frozen-top2-reader-research-plan.v1",
            archived_source=ARCHIVED_SOURCE, archived_tree=ARCHIVED_TREE,
            archived_zip_sha256=original.sha256,
            archived_sha256_members=original.manifest_entries,
            registered_test_transfer=[dict(phase=p, question_id=q)
                                      for p,q in sorted(expected)],
            only_E2_selection=(
                "highest-frozen-score-distinct-native-session-in-original-pool"
            ),
            one_E1_unchanged_original_bytes=True,
            native_gold_read_before_generation=False,
            Reader_system_sha256=digest(SYSTEM),
            Reader_generation_config=GENERATION,
            same_input_limit=INPUT_CEILING,
            original_six_arm_mutation=False,
            production_accepted=False,
        ))
        retrieval = Encoder(staged / "encoder")
        require(
            retrieval.identity == plan["retriever_inventory"]
            and digest(file_inventory(staged / "encoder"))
                == plan["retriever_inventory"],
            "frozen retrieval Encoder inventory changed",
        )
        require(
            file_inventory(ranker_dir) == plan["ranker_inventory"],
            "frozen pair ranker inventory changed",
        )
        ranker = FrozenPairEncoder(ranker_dir)
        start = time.perf_counter()
        reader = FrozenAnswerGenerator(
            staged / "reader", expected_inventory=plan["reader_inventory"]
        )
        reader_load_seconds = time.perf_counter() - start
        require(
            all(reader.identity == item["receipt"]["generator_identity"]
                and reader.profile == item["receipt"]["generator_profile"]
                for item in frozen.values()),
            "frozen Reader weight/prompt identity differs from original",
        )
        temporal = original.json("comparison/source-admission.json")
        budget = WindowBudget(**plan["window_budget"])
        one, two = [], []
        with tempfile.TemporaryDirectory() as tmp:
            indices = {}
            try:
                for phase in PHASES:
                    for qid in plan["questions"][phase]:
                        q, source = queries[qid], owners[qid]
                        receipt = frozen[phase, qid]
                        require(
                            receipt["receipt"]["observable_query"] == asdict(q)
                            and receipt["family"] == plan["question_families"][qid],
                            "original Reader/query/source-family identity mismatch",
                        )
                        key = digest((source.source_sha256, q.scope, q.observed_at))
                        if key not in indices:
                            admission = temporal[key]
                            path = Path(tmp) / ("index-" + key + ".sqlite")
                            path.write_bytes(original.read(
                                f"comparison/index-{key}.sqlite"
                            ))
                            indices[key] = PersistentIndex(
                                path, admission["as_of_cut"], set(),
                                expected_file_digest=admission["verified_index_digest"],
                                expected_encoder=retrieval.identity,
                            )
                        admission = temporal[key]
                        docs, _ = indices[key].query(
                            q, retrieval.encode([q.content])[0], RetrievalPolicy(),
                            current_cut=admission["as_of_cut"], revoked=set(),
                        )
                        pool = candidate_windows(
                            tuple(docs), q, revoked=set(), budget=budget,
                            profile="query_windows",
                        )
                        require(pool.seal() == receipt["pool_digest"],
                                "frozen strict-as-of candidate pool changed")
                        features, _ = ranker.encode(
                            q, receipt["family"], pool, revoked=set()
                        )
                        orig_sources = receipt["receipt"]["delivered_evidence"]
                        session_by_source_id = {
                            document.identity: document.session
                            for document in source.history(q)
                        }
                        first, both, bound = prepare_second_window(
                            q, pool, features, receipt["selected"], orig_sources,
                            session_by_source_id,
                        )
                        append(output / "frozen-second-source-plans.jsonl",
                               dict(phase=phase, **bound))
                        budget_receipt = dict(
                            max_new_tokens=GENERATION["max_new_tokens"],
                            input_ceiling=INPUT_CEILING,
                        )
                        base_row = dict(
                            phase=phase, question_id=qid,
                            source_family=receipt["family"],
                            original_E1=digest(first),
                            reader_identity=reader.identity,
                            reader_profile=reader.profile,
                            reader_prompt_budget=budget_receipt,
                            original_strict_policy_sha256=digest(receipt),
                        )
                        one_row = dict(base_row, status="failed")
                        try:
                            output_raw, gen = reader.answer(
                                q, first, revoked=set()
                            )
                            one_row.update(
                                status="succeeded", answer=output_raw,
                                receipt=gen, delivered_sources=list(first),
                                exactly_reproduced_archived_answer=(
                                    output_raw == receipt["answer"]
                                    and gen["input_ids_digest"]
                                    == receipt["receipt"]["input_ids_digest"]
                                    and gen["generated_ids_digest"]
                                    == receipt["receipt"]["generated_ids_digest"]
                                ),
                            )
                        except Exception as error:
                            one_row.update(
                                error_type=type(error).__name__,
                                error=str(error)[:1024],
                            )
                        append(output / "one-window-raw.jsonl", one_row)
                        one.append(one_row)
                        two_row = dict(base_row, status="unavailable")
                        if not both:
                            two_row["reason"] = bound.get("reason")
                        else:
                            try:
                                output_raw, gen = answer_two(
                                    reader, q, both, revoked=set()
                                )
                                two_row.update(
                                    status="succeeded", answer=output_raw,
                                    receipt=gen, delivered_sources=list(both),
                                )
                            except Exception as error:
                                two_row.update(
                                    status="failed", error_type=type(error).__name__,
                                    error=str(error)[:1024],
                                )
                        append(output / "two-window-raw.jsonl", two_row)
                        two.append(two_row)
            finally:
                for index in indices.values():
                    index.close()
        if not reader.quarantined:
            reader.verify_frozen()
        retrieval.verify_frozen()
        ranker.verify_frozen()
        # Gold target strings are first accessed AFTER both raw-output
        # journals are persisted. Each of 16 original questions still counts.
        targets = {qid: owners[qid].targets[qid] for _,qid in expected}
        result = compare_capacity_rows(
            [dict(phase=p, question_id=q) for p,q in sorted(expected)],
            one, two, diagnose=diagnose, targets=targets,
        )
        result.update(
            actual_frozen_reader_executed_here=True,
            true_model_calls_succeeded=dict(
                one=sum(x["status"] == "succeeded" for x in one),
                two=sum(x["status"] == "succeeded" for x in two),
            ),
            one_window_original_answer_byte_matches=sum(
                x.get("exactly_reproduced_archived_answer") is True for x in one
            ),
            reader_input_tokens=dict(
                one=sum(x["receipt"]["input_tokens"] for x in one
                        if x["status"] == "succeeded"),
                two=sum(x["receipt"]["input_tokens"] for x in two
                        if x["status"] == "succeeded"),
            ),
            reader_generated_tokens=dict(
                one=sum(x["receipt"]["generated_tokens"] for x in one
                        if x["status"] == "succeeded"),
                two=sum(x["receipt"]["generated_tokens"] for x in two
                        if x["status"] == "succeeded"),
            ),
            reader_original_model_cold_load_seconds=reader_load_seconds,
            observed_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            original_policy_answers_rewritten=False,
            new_readers_got_no_target_answer_strings=True,
            true_prospective_independent_evaluation=False,
            actual_cost_not_equal_when_two_sources=True,
            semantic_citation_precision=None,
            production_accepted=False,
        )
        write(output / "report.json", result)
        # Always retain the entire raw attempted census before failing.
        if not any(x["status"] == "succeeded" for x in two):
            raise RuntimeError(
                "no real two-window Reader answers; research experiment incomplete"
            )
        return result
    finally:
        original.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", type=Path, required=True)
    parser.add_argument("--ranker", type=Path, required=True)
    parser.add_argument("--original-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(
        run(a.staged, a.ranker, a.original_zip, a.output),
        ensure_ascii=False, sort_keys=True,
    ))


if __name__ == "__main__":
    main()
