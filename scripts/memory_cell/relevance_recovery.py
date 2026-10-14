"""Recover a fixed interrupted study without refitting completed candidates.

The original run remains CANCELLED. Restart only its incomplete reverse arm
from the original base/seed; never resume an adapter without optimizer state.
Verified historical outputs stay historical. This module cannot admit a Reader.
"""
from __future__ import annotations
import argparse
import gc
import json
from pathlib import Path
import re
import shutil

import five_causal_experiments as c
import reader_content_swap_trial as saved
import select_question_relevance as protocol

PROFILE = "hepta.reader.relevance-recovery.v1"
CANCELLED_SOURCE = "644799a3ec45e18e77ce4ad772029f67fee55db7"
CANCELLED_RUN = 38512395172
CANCELLED_ARTIFACT = 11872208169
CANCELLED_SHA = "601cd09ae82cc6915121aaf8bb0eac5c1fe7c8b370c9d4a832bc6e5d54b91bac"
REUSE = ("frozen_reader", "repeat_empty", "nonempty_aligned")
RESTART = "nonempty_reversed"
COMMON_FILES = ("plan.json", "train-plan.json", "train-compilation.json", "public-inputs.json")
ARM_SUFFIXES = ("-raw.json", "-raw-seal.json", "-scores.json", "-train-diagnostic.json", "-content-audit.json")


def read_chain(path):
    path = Path(path)
    c.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= c.MAX_FILE_BYTES,
              "missing or oversized recovery journal")
    previous, records = "0" * 64, []
    for line in path.read_bytes().splitlines():
        def unique(pairs):
            out = {}
            for k, v in pairs:
                c.require(k not in out, "duplicate journal key")
                out[k] = v
            return out
        entry = json.loads(line, object_pairs_hook=unique)
        c.require(isinstance(entry, dict) and set(entry) == {"previous_sha256", "record"}
                  and entry["previous_sha256"] == previous and isinstance(entry["record"], dict),
                  "recovery journal chain mismatch")
        previous = c.digest(entry)
        records.append(entry["record"])
    return records


def optimizer_census(records):
    """Completed dispatches are a lower bound; an open update is never zero cost."""
    seen, opened, started, finished, known, failed = set(), None, 0, 0, 0, 0
    for row in records:
        event = row.get("event")
        key = (row.get("epoch"), row.get("index"))
        c.require(all(type(x) is int and x >= 0 for x in key), "invalid optimizer unit")
        if event == "optimizer_started":
            c.require(opened is None and key not in seen, "overlapping or repeated optimizer attempt")
            opened = key; seen.add(key); started += 1
        else:
            c.require(event in ("optimizer_finished", "optimizer_failed_or_unknown") and opened == key,
                      "unmatched optimizer terminal event")
            n = row.get("observed_decoder_forwards")
            c.require(type(n) is int and n >= 0, "invalid observed training work")
            known += n
            finished += event == "optimizer_finished"
            failed += event == "optimizer_failed_or_unknown"
            opened = None
    return {"started_updates": started, "completed_updates": finished, "failed_updates": failed,
            "open_update": list(opened) if opened is not None else None,
            "known_decoder_forward_lower_bound": known,
            "unobserved_tail_cost_unknown": opened is not None,
            "optimizer_state_resumable": False}


def check_receipt(study, arm, expected_units=14, expected_forwards=864):
    from question_relevance_trial import ARMS
    directory = Path(study) / arm
    receipt = c.load(directory / "training-receipt.json")
    plan = c.load(directory / "training-plan.json")
    census = optimizer_census(read_chain(directory / "optimizer-journal.jsonl"))
    c.require(receipt["base_unchanged"] is True and receipt["checkpoint_reload_equal"] is True
              and receipt["optimizer_steps"] == plan["actual_epochs"] * plan["training_units"] == expected_units * 8
              and census["completed_updates"] == receipt["optimizer_steps"]
              and census["open_update"] is None and census["failed_updates"] == 0
              and census["known_decoder_forward_lower_bound"] == receipt["training_forwards"] == expected_forwards,
              "incomplete saved training or measured work")
    c.require(plan["loss_objective"] == receipt["loss_objective"]
              and plan["loss_objective"]["name"] == "paired-evidence-margin-v1",
              "saved training objective drift")
    # The exact original artifact pins the profile and every byte, while the
    # receipt/file checks bind loaded material. No pickle or optimizer restore.
    c.require(arm in dict(ARMS) and c.sha(receipt["initial_adapter_sha256"])
              and c.sha(receipt["adapter_tensor_sha256"]), "saved model identity incomplete")
    for name, sha in receipt["files"].items():
        c.source_file(directory, name, sha)
    c.require("adapter/adapter_model.safetensors" in receipt["files"], "safe adapter weights missing")
    return receipt, census


def check_arm(study, arm, cases, events):
    """Complete raw/diagnostic ledgers only; outcome quality never selects reuse."""
    study = Path(study)
    raw = c.load(study / (arm + "-raw.json"))
    seal = c.load(study / (arm + "-raw-seal.json"))
    c.require(seal == {"sha256": c.file_sha(study / (arm + "-raw.json")), "before_target_scoring": True},
              "historical raw answer seal mismatch")
    protocol.join_previous(cases, raw, arms=(arm,))
    written = [{k: v for k, v in r.items() if k != "event"} for r in events
               if r.get("event") == "generation_recorded" and r.get("arm") == arm]
    c.require(written == raw, "historical answers differ from fsynced journal")
    score = c.load(study / (arm + "-scores.json"))
    train = c.load(study / (arm + "-train-diagnostic.json"))
    audits = c.load(study / (arm + "-content-audit.json"))
    c.require(len(score) == len(raw) and len(train) == 14 and len(audits) == 4
              and len({r["question_id"] for r in train}) == 14
              and len({r["question_id"] for r in audits}) == 4
              and all(r["status"] == "succeeded" for r in train)
              and sum(r["status"] == "succeeded" for r in audits) == 3
              and sum(r["status"] == "unavailable_recipient_annotation" for r in audits) == 1,
              "incomplete original diagnostic census")
    for kind, rows in (("train_diagnostic_recorded", train), ("select_audit_recorded", audits)):
        saved_rows = [{k: v for k, v in r.items() if k not in ("event", "arm")} for r in events
                      if r.get("event") == kind and r.get("arm") == arm]
        c.require(rows == saved_rows, "diagnostic file differs from journal")
    positions = [i for i, r in enumerate(events) if r.get("arm") == arm and r.get("event") == "generation_recorded"]
    first_audit = [i for i, r in enumerate(events) if r.get("arm") == arm and r.get("event") in
                   ("train_diagnostic_started", "select_audit_started")]
    c.require(positions and first_audit and max(positions) < min(first_audit), "targets preceded sealed generations")
    training, work = (None, None) if arm == "frozen_reader" else check_receipt(study, arm)
    return {"raw": raw, "scores": score, "train": train, "audits": audits,
            "training": training, "training_work": work}


def inspect_cancelled(root):
    root = Path(root); study = root / "study"
    c.require((root / "source/tested-commit.txt").read_text().strip() == CANCELLED_SOURCE,
              "different cancelled study source")
    c.require(not (study / "report.json").exists(), "not the registered interrupted execution")
    from question_relevance_trial import PLAN
    plan = c.load(study / "plan.json")
    c.require(c.canonical({k: v for k, v in plan.items() if k != "training"}) == c.canonical(PLAN),
              "original scientific plan changed")
    cases = c.load(study / "public-inputs.json")
    c.require(len(cases) == 28 and sum(x["request"] is not None for x in cases) == 27,
              "original generation inventory differs")
    events = read_chain(study / "events.jsonl")
    arms = {a: check_arm(study, a, cases, events) for a in REUSE}
    c.require(not (study / RESTART / "training-receipt.json").exists()
              and not (study / (RESTART + "-raw.json")).exists(), "reverse arm no longer requires this restart")
    interrupted = optimizer_census(read_chain(study / RESTART / "optimizer-journal.jsonl"))
    c.require(0 < interrupted["started_updates"] <= 112 and interrupted["completed_updates"] < 112,
              "unexpected interruption boundary")
    return study, cases, arms, {"schema": PROFILE + ".inventory", "cancelled_run": CANCELLED_RUN,
        "cancelled_artifact_sha256": CANCELLED_SHA, "original_conclusion": "cancelled",
        "reused_arms": list(REUSE), "restart_from_base": RESTART,
        "interrupted_work": interrupted, "partial_weights_selected": False,
        "new_model_calls": 0, "new_optimizer_updates": 0}


def copy_checked(source, destination):
    source, destination = Path(source), Path(destination)
    c.require(source.is_file() and not source.is_symlink() and not destination.exists(), "invalid recovery copy")
    expected = c.file_sha(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    c.require(c.file_sha(source) == expected == c.file_sha(destination), "copy drift")


def run(cancelled_archive, original_archive, budget_archive, select_archive, work, output, source_commit):
    """One explicit restart; verified complete arms never invoke their optimizer."""
    c.require(isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit), "execution source required")
    work, output = Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    root, verified = saved.extract_verified(cancelled_archive, work / "cancelled", CANCELLED_SHA)
    old, cases, retained, inventory = inspect_cancelled(root)
    c.write_new(output / "cancelled-inventory.json", inventory | {"artifact_verification": verified})
    print("VERIFIED_RECOVERY_BOUNDARY", c.canonical(inventory).decode(), flush=True)
    # Import only checked repository code, never archived Python.
    import question_relevance_trial as trial
    restarted = output / "restarted"
    fresh = trial.run(original_archive, budget_archive, select_archive, work / "restart-materials",
                      restarted, only_arms=(RESTART,))
    c.require(fresh["errors"] == [] and fresh["execution_subset"] == [RESTART]
              and set(fresh["arms"]) == {RESTART}, "restarted arm failed")
    for name in COMMON_FILES:
        c.require(c.file_sha(old / name) == c.file_sha(restarted / name), "restart changed original inputs: " + name)
    new = check_arm(restarted, RESTART, cases, read_chain(restarted / "events.jsonl"))
    all_data = retained | {RESTART: new}
    initial = {r["training"]["initial_adapter_sha256"] for r in all_data.values() if r["training"] is not None}
    c.require(len(initial) == 1, "candidate initialization differs")

    import five_reader_response_learning as learning
    import five_reader_evidence_pair_trial as parent
    import reader_content_swap as control
    from five_native_historical_smoke import prepare_materials, snapshot, READER_INVENTORY
    from five_causal_native import SCHEMA, reader_bindings
    from five_reader_adapter import compose, attach, verify_resident
    from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
    with measured() as staging_cost:
        _, clean, staging = prepare_materials(Path(original_archive), work / "verification-materials")
    reader = clean / "reader"; snap = snapshot(reader, "causal_lm", READER_INVENTORY)
    merged = output / "study"; merged.mkdir()
    for name in COMMON_FILES: copy_checked(old / name, merged / name)
    summaries, raw = {}, []
    for arm in protocol.ARMS:
        src = restarted if arm == RESTART else old
        data = all_data[arm]
        backend = None
        try:
            with measured() as verification_cost:
                backend = LocalTextGenerator(reader, snap, trial.PLAN["maximum_input_tokens"])
                if arm != "frozen_reader":
                    bindings = {k: c.digest("recovery-unused:" + k) for k in c.BINDINGS}
                    bindings.update(reader_bindings(snap, backend.tokenizer.chat_template, 2048, 64))
                    base = {"schema": SCHEMA, "kind": "reader", "snapshot": snap, "bindings": bindings}
                    description = compose(src, base, arm + "/adapter", arm + "/training-receipt.json")
                    attached = attach(backend, src, description["response_adapter"], snap)
                    c.require(attached["saved_tensor_equality"] and attached["base_unchanged"], "saved candidate reload failed")
                    verify_resident(backend)
                c.require(not backend.loaded.training and all(not p.requires_grad for p in backend.loaded.parameters()),
                          "verification candidate is not frozen")
        finally:
            if backend is not None: backend.close(); del backend
            gc.collect()
        for suffix in ARM_SUFFIXES: copy_checked(src / (arm + suffix), merged / (arm + suffix))
        if arm != "frozen_reader":
            for file in sorted((src / arm).rglob("*")):
                if file.is_file(): copy_checked(file, merged / file.relative_to(src))
        raw.extend(data["raw"])
        summaries[arm] = {"training": data["training"], "generation": parent.aggregate(data["scores"]),
            "content": control.summarize(data["audits"]), "model_integrity_verified": True,
            "integrity_basis": "fresh_strict_saved_checkpoint_reload_no_new_generation",
            "historical_in_memory_integrity_receipt_available": arm == RESTART,
            "recovery_verification_cost": verification_cost,
            "original_load_cost": fresh["arms"][arm]["load_cost"] if arm == RESTART else None,
            "original_load_cost_unknown": arm != RESTART,
            "diagnostic_forwards": sum(r["observed_decoder_forwards"] for r in data["train"] + data["audits"]),
            "origin": "restarted_from_base" if arm == RESTART else "verified_cancelled_artifact_completed_arm"}
    protocol.join_previous(cases, raw)
    c.write_new(merged / "raw-answers.json", raw)
    manifest = {"schema": PROFILE, "execution_source": source_commit,
        "original_source": CANCELLED_SOURCE, "original_run": CANCELLED_RUN, "original_status": "cancelled",
        "original_artifact": CANCELLED_ARTIFACT, "original_artifact_sha256": CANCELLED_SHA,
        "reused_arms": list(REUSE), "restarted_arms": [RESTART], "optimizer_state_resumed": False,
        "interrupted_work": inventory["interrupted_work"], "scientific_plan_sha256": c.digest(c.load(merged / "plan.json")),
        "file_hashes": {p.relative_to(merged).as_posix(): c.file_sha(p) for p in sorted(merged.rglob("*")) if p.is_file()},
        "original_failure_relabelled": False, "production_accepted": False}
    c.write_new(output / "recovery-manifest.json", manifest)
    report = {"schema": PROFILE + ".result", "plan_sha256": manifest["scientific_plan_sha256"],
        "recovery_manifest_sha256": c.digest(manifest), "raw_sha256": c.file_sha(merged / "raw-answers.json"),
        "planned_rows": len(raw), "successful_model_calls_across_origins": sum(x["status"] == "succeeded" for x in raw),
        "new_generation_calls": fresh["successful_model_calls"], "reused_generation_calls": sum(x["status"] == "succeeded" for a in REUSE for x in retained[a]["raw"]),
        "new_optimizer_updates": new["training"]["optimizer_steps"], "new_training_forwards": new["training"]["training_forwards"],
        "new_generation_forwards": fresh["generation_forward_lower_bound"],
        "new_diagnostic_forwards": fresh["arms"][RESTART]["diagnostic_forwards"],
        "old_interrupted_cost_is_additional": True, "arms": summaries, "errors": [],
        "staging": staging, "staging_cost": staging_cost, "reader_adequacy_established": False,
        "independent_confirmation": False, "production_accepted": False, "five_experiments_completed": False}
    c.write_new(merged / "report.json", report)
    c.write_new(output / "source-identity.json", {"execution_source": source_commit})
    # Keep original/restart journals as separate histories; no synthetic merged chain.
    copy_checked(old / "events.jsonl", output / "provenance/cancelled-events.jsonl")
    copy_checked(old / RESTART / "optimizer-journal.jsonl", output / "provenance/interrupted-optimizer.jsonl")
    print("RECOVERED_RELEVANCE_RESULT", c.canonical(report).decode(), flush=True)
    return report


def validate_completed(root):
    """Called only after the entire new result archive has an external SHA pin."""
    root = Path(root); study = root / "study"
    m, report = c.load(root / "recovery-manifest.json"), c.load(study / "report.json")
    c.require(m["schema"] == PROFILE and m["original_artifact_sha256"] == CANCELLED_SHA
              and m["original_run"] == CANCELLED_RUN and m["original_status"] == "cancelled"
              and m["original_source"] == CANCELLED_SOURCE and m["original_failure_relabelled"] is False
              and m["reused_arms"] == list(REUSE) and m["restarted_arms"] == [RESTART]
              and m["optimizer_state_resumed"] is False, "unregistered recovery origin")
    c.require((root / "source/tested-commit.txt").read_text().strip() == m["execution_source"]
              and report["schema"] == PROFILE + ".result" and report["errors"] == []
              and report["recovery_manifest_sha256"] == c.digest(m), "incomplete recovery result")
    actual = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()} - {"report.json"}
    c.require(set(m["file_hashes"]) == actual, "recovery material inventory changed")
    for name, sha in m["file_hashes"].items(): c.source_file(study, name, sha)
    c.require(report["plan_sha256"] == m["scientific_plan_sha256"] == c.digest(c.load(study / "plan.json"))
              and report["raw_sha256"] == c.file_sha(study / "raw-answers.json")
              and set(report["arms"]) == set(protocol.ARMS), "recovery plan or arm census changed")
    cases = c.load(study / "public-inputs.json"); raw = c.load(study / "raw-answers.json")
    joined = protocol.join_previous(cases, raw)
    for arm in protocol.ARMS:
        c.require(report["arms"][arm]["model_integrity_verified"] is True
                  and c.load(study / (arm + "-raw.json")) == [x for x in raw if x["arm"] == arm],
                  "recovered model/output identity failed")
        if arm != "frozen_reader":
            receipt, _ = check_receipt(study, arm)
            c.require(report["arms"][arm]["training"] == receipt, "recovered receipt differs")
    return study, report, cases, joined


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("cancelled-archive", "original-archive", "budget-archive", "select-archive", "work", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--source-commit", required=True)
    a = p.parse_args()
    try:
        run(a.cancelled_archive, a.original_archive, a.budget_archive, a.select_archive, a.work, a.output, a.source_commit)
    except Exception as error:
        if a.output.is_dir() and not (a.output / "failure.json").exists():
            c.write_new(a.output / "failure.json", {"error": str(error)[:2048], "completed": False,
                "original_cancelled_status_retained": True, "production_accepted": False})
        raise
