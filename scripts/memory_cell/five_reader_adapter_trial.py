"""Replay saved response candidates through NativeSession, not a new task study.

Uses already-staged original weights, saved adapters and previously frozen
public inputs. No fitting, semantic judge, production admission or automatic
candidate selection. Replayed work is real additional cost, not new samples.
"""
from __future__ import annotations

import argparse
import gc
from pathlib import Path
import time

from transformers import AutoTokenizer

import five_causal_experiments as c
import five_causal_native as n
from five_reader_adapter import compose
from five_native_historical_smoke import ARCHIVE_SHA256, READER_INVENTORY, snapshot, store_bundle
from experiments.shared_stem_cell.execution import measured

ARMS = ("aligned_lora", "shuffled_positive_lora")
CONDITIONS = ("no_evidence", "oracle_plus_distractors")


def selected_inputs(rows):
    """Select identities before seeing earlier answers or availability; no replacement."""
    c.require(isinstance(rows, list) and rows, "frozen public input census missing")
    qids = sorted({r["question_id"] for r in rows}, key=c.digest)
    selected = [r for r in rows if r["question_id"] == qids[0] and r["condition"] in CONDITIONS]
    c.require(len(selected) == 2 and {r["condition"] for r in selected} == set(CONDITIONS),
              "both preregistered replay conditions required")
    return sorted(selected, key=lambda r: CONDITIONS.index(r["condition"]))


def relative_directory(root, name):
    c.require(isinstance(name, str) and name and not Path(name).is_absolute()
              and ".." not in Path(name).parts, "relative material path required")
    path = Path(root)/name
    c.require(path.is_dir() and not any(p.is_symlink() for p in (path, *path.parents)), "missing/linked material directory")
    return path


def run(root, reader_relative, study_relative, output):
    root, output = Path(root), Path(output)
    reader = relative_directory(root, reader_relative)
    study = relative_directory(root, study_relative)
    plan = c.load(study/"plan.json")
    c.require(plan.get("schema") == "hepta.five-reader.response-learning-diagnostic.v1"
              and plan.get("archive_sha256") == ARCHIVE_SHA256, "wrong historical source study")
    inputs_path = study/"public-evaluation-inputs.json"
    inputs_sha = c.file_sha(inputs_path)
    cases = selected_inputs(c.load(inputs_path))
    old_seal = c.load(study/"raw-seal.json")
    c.require(c.sha(old_seal.get("sha256")), "previous raw seal missing")
    # Verify old bytes now but do NOT read/choose outcomes until new raw seals.
    c.require(c.file_sha(study/"raw-answers.json") == old_seal["sha256"], "previous raw answers changed")
    snap = snapshot(reader, "causal_lm", READER_INVENTORY)
    tokenizer = AutoTokenizer.from_pretrained(reader, local_files_only=True, trust_remote_code=False)
    output.mkdir(parents=True, exist_ok=False)
    registered = {"schema": "hepta.reader.composed-replay.v1", "arms": ARMS, "cases": cases,
                  "previous_raw_sha256": old_seal["sha256"], "public_inputs_sha256": inputs_sha,
                  "source_plan_sha256": c.digest(plan), "source_selection": "first_question_identity_hash_no_replacement",
                  "new_independent_tasks": 0, "production_accepted": False}
    c.write_new(output/"plan.json", registered)
    c.write_new(output/"source.json", {name: c.file_sha(Path(__file__).with_name(name)) for name in
        ("five_reader_adapter_trial.py", "five_reader_adapter.py", "five_causal_native.py")})
    previous, rows, owners, errors = "0"*64, [], {}, []
    with (output/"events.jsonl").open("xb") as stream:
        for arm in ARMS:
            bindings = {k: c.digest("composed-replay-unused-"+k) for k in c.BINDINGS}
            bindings.update(n.reader_bindings(snap, tokenizer.chat_template,
                plan["maximum_input_tokens"], plan["maximum_output_tokens"]))
            base = {"schema": n.SCHEMA, "kind": "reader", "sharing": "shared", "scope": "historical-response-replay",
                    "purpose": "integrity-diagnostic", "generation": c.digest(plan), "cell": arm,
                    "model_path": reader_relative, "snapshot": snap, "bindings": bindings,
                    "maximum_tokens": plan["maximum_input_tokens"], "maximum_new_tokens": plan["maximum_output_tokens"]}
            manifest = compose(root, base, study_relative+"/"+arm+"/adapter",
                               study_relative+"/"+arm+"/training-receipt.json")
            descriptor = store_bundle(root, manifest)
            c.write_new(output/(arm+"-descriptor.json"), manifest)
            owner = n.NativeSession(root, max_models=1)
            try:
                for case in cases:
                    row = {"arm": arm, "question_id": case["question_id"], "condition": case["condition"],
                           "status": "unavailable_oracle_annotation", "answer": None,
                           "descriptor_sha256": descriptor, "additional_work_not_new_task": True}
                    if case["request"] is not None:
                        packet = {"request": case["request"], "checkpoint_sha256": descriptor,
                                  "bindings": manifest["bindings"], "timeout_seconds": plan["per_call_seconds"]}
                        row["request_sha256"] = c.digest(packet)
                        previous = c.journal_append(stream, {"event": "reader_started", **row}, previous)
                        started = time.perf_counter()
                        with measured() as cost:
                            try:
                                result = owner.answer(packet, arm="composed-replay")
                                observation = owner.observations[-1]
                                row.update(status="succeeded", answer=result["answer"],
                                           actual_decoder_forwards=result["resources"]["model_calls"],
                                           input_token_sha256=observation["input_token_sha256"],
                                           output_token_sha256=observation["output_token_sha256"])
                            except Exception as error:
                                row.update(status="failed", error=type(error).__name__+": "+str(error)[:1024],
                                           actual_decoder_forwards=None)
                                errors.append({"arm": arm, "condition": case["condition"], "phase": "reader"})
                        row["cost_including_owner_verification"] = cost
                        if time.perf_counter()-started > plan["per_call_seconds"]:
                            row["status"] = "timeout_with_observed_output"
                            errors.append({"arm": arm, "condition": case["condition"], "phase": "deadline"})
                    previous = c.journal_append(stream, {"event": "reader_recorded", **row}, previous)
                    rows.append(row)
            finally:
                try:
                    owners[arm] = owner.close()
                except Exception as error:
                    errors.append({"arm": arm, "phase": "close", "error": str(error)[:1024]})
                del owner
                gc.collect()
    c.require(len(rows) == len(ARMS)*len(cases), "incomplete replay census")
    c.write_new(output/"raw-answers.json", rows)
    raw_sha = c.file_sha(output/"raw-answers.json")
    c.write_new(output/"raw-seal.json", {"sha256": raw_sha, "event_tail_sha256": previous,
                                        "previous_answers_not_read_yet": True})
    c.require(c.file_sha(inputs_path) == inputs_sha and c.file_sha(study/"raw-answers.json") == old_seal["sha256"],
              "source study changed during replay")
    old = c.load(study/"raw-answers.json")
    index = {}
    for r in old:
        key = (r["arm"], r["question_id"], r["condition"])
        c.require(key not in index, "duplicate source study observation")
        index[key] = r
    comparisons = []
    for r in rows:
        prior = index.get((r["arm"], r["question_id"], r["condition"]))
        c.require(prior is not None, "no original planned observation for replay")
        eligible = r["status"] == prior["status"] == "succeeded"
        match = (all(r[k] == prior[k] for k in ("answer", "input_token_sha256", "output_token_sha256"))
                 if eligible else None)
        comparisons.append({"arm": r["arm"], "condition": r["condition"], "comparable": eligible,
                            "raw_answer_and_token_hashes_equal": match, "status": r["status"]})
    report = {"schema": "hepta.reader.composed-replay-result.v1", "raw_sha256": raw_sha,
              "previous_raw_sha256": old_seal["sha256"], "planned": len(rows),
              "succeeded": sum(r["status"] == "succeeded" for r in rows),
              "comparisons": comparisons, "owners": owners, "errors": errors,
              "new_independent_tasks": 0, "additional_decoder_forwards_known_lower_bound":
                  sum(r.get("actual_decoder_forwards") or 0 for r in rows),
              "decoder_count_complete": all(r["status"] == "unavailable_oracle_annotation"
                  or r.get("actual_decoder_forwards") is not None for r in rows),
              "reader_adequacy_established": False, "production_accepted": False}
    c.write_new(output/"report.json", report)
    c.require(not errors and any(x["comparable"] for x in comparisons)
              and all(x["raw_answer_and_token_hashes_equal"] is True for x in comparisons if x["comparable"]),
              "composed replay incomplete or differs; original observations retained")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--reader-relative", required=True)
    parser.add_argument("--study-relative", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.root, args.reader_relative, args.study_relative, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output/"failure.json").exists():
            c.write_new(args.output/"failure.json", {"error": str(error)[:2048], "completed": False,
                                                    "production_accepted": False})
        raise
