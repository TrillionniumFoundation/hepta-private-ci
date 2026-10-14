"""Read-only nonempty-content audit of the exact completed 2/8-epoch artifacts.

Reuse saved candidates: ZERO optimization steps. Original and result archives
have independently fixed SHA256 pins. Artifact Python files are never imported.
No candidate is qualified and the failed projection tolerance is not relaxed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import gc
import hashlib
from pathlib import Path, PurePosixPath
import stat
import zipfile

import five_causal_experiments as c
import reader_content_swap as control

BUDGET_SHA = "ce5178bf4bea0d45d65f22765e29a835b7a99a4b3a4fd1dc4fa0d248a6d5c151"
BUDGET_SOURCE = "00104aaf8eff351359a779ccc034cbbe6e4aa023"
BUDGET_RAW_SHA = "f23a754463619360de226748f1c502a43339703adbb1b1c9284f3d08dd9fac92"
PROJECTION_SHA = "4259beaea0c23cbd80d945b464b83ff23af5c1185d7c2fe469409c0043c6c38d"
ARMS = ("frozen_reader", "aligned_2", "shuffled_2", "aligned_8", "shuffled_8")
PLAN = {"schema": "hepta.reader.saved-content-swap-study.v1", "control_profile": control.PROFILE,
        "budget_artifact_id": 11838105827, "budget_artifact_sha256": BUDGET_SHA,
        "budget_source": BUDGET_SOURCE, "projection_artifact_id": 11837123194,
        "projection_artifact_sha256": PROJECTION_SHA, "arms": ARMS,
        "source_representation": "source-session-time-v1",
        "donor_rule": "same_partition_cross_family_same_source_count_distinct_annotated_body_identity_hash",
        "generation_recipients": "exact_previous_fixed_generation_recipients",
        "annotation_semantics": "weak_benchmark_not_independent_incompatibility_review",
        "likelihood_targets": "exact_uncited_bodies_diagnostic_only",
        "vocabulary_projection": "full-logits-v1", "maximum_input_tokens": 2048,
        "maximum_output_tokens": 64, "per_call_seconds": 120,
        "optimization_steps": 0, "new_independent_tasks": 0,
        "test_readout": False, "automatic_selection": False, "production_accepted": False}


def extract_verified(archive, output, expected):
    """Fixed small result archive, every member checked before any extraction."""
    archive, output = Path(archive), Path(output)
    c.require(c.sha(expected) and archive.is_file() and not archive.is_symlink()
              and archive.stat().st_size <= 64 * 1024**2 and c.file_sha(archive) == expected,
              "result archive pin/size mismatch")
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        c.require(len(infos) <= 4096 and sum(i.file_size for i in infos) <= 128 * 1024**2,
                  "result archive uncompressed bound")
        names, payload = set(), {}
        for i in infos:
            name = i.filename
            p = PurePosixPath(name)
            c.require(p.parts and not p.is_absolute() and ".." not in p.parts and "\\" not in name
                      and p.as_posix() == name.rstrip("/") and name not in names,
                      "unsafe or duplicate archive path")
            names.add(name)
            mode = (i.external_attr >> 16) & 0xFFFF
            c.require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), "linked or special archive member")
            if not i.is_dir():
                payload[name] = z.read(i)
        manifests = [n for n in payload if PurePosixPath(n).name == "SHA256SUMS"]
        c.require(len(manifests) == 1, "unique result hash manifest required")
        manifest = manifests[0]
        prefix = str(PurePosixPath(manifest).parent)
        prefix = "" if prefix == "." else prefix + "/"
        covered = set()
        for line in payload[manifest].decode("utf-8").splitlines():
            h, relative = line.split(maxsplit=1)
            relative = relative.removeprefix("*").removeprefix("./")
            name = prefix + relative
            c.require(c.sha(h) and name in payload and name != manifest and name not in covered,
                      "invalid or duplicate manifest member")
            c.require(hashlib.sha256(payload[name]).hexdigest() == h, "result member hash mismatch")
            covered.add(name)
        c.require(covered == set(payload) - {manifest}, "unlisted result member")
    c.require(c.file_sha(archive) == expected, "result archive changed while reading")
    c.require(not any(p.is_symlink() for p in (output, *output.parents)), "linked extraction destination")
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in payload.items():
        dest = output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("xb") as stream:
            stream.write(raw)
    return output / prefix, {"archive_sha256": expected, "verified_members": len(covered),
                            "files": len(payload), "artifact_code_executed": False}


def validate_budget(root):
    c.require((root / "source/tested-commit.txt").read_text().strip() == BUDGET_SOURCE, "wrong saved study source")
    study = root / "study"
    report = c.load(study / "report.json")
    plan = c.load(study / "plan.json")
    c.require(report.get("schema") == "hepta.reader.fixed-fit-budget-result.v1"
              and report.get("errors") == [] and report.get("plan_sha256") == c.digest(plan),
              "incomplete or reinterpreted saved study")
    c.require(report.get("raw_sha256") == BUDGET_RAW_SHA
              and c.file_sha(study / "raw-answers.json") == BUDGET_RAW_SHA, "saved raw output pin mismatch")
    c.require(set(report["arms"]) == set(ARMS), "saved candidate census differs")
    return study, report


def projection_inventory(root):
    """Enumerate ALL saved-adapter mismatches using the ORIGINAL tolerances.

    No new qualification, no model calls, no refitting, no tolerance inflation.
    The previous comparison stopped at the first failing tensor; this inventory
    records every tensor so one printed error is not mistaken for global scope.
    """
    import torch
    from safetensors.torch import load_file
    study = root / "study"
    plan, previous = c.load(study / "plan.json"), c.load(study / "report.json")
    c.require((root / "source/tested-commit.txt").read_text().strip() == "efe97de488622b14bab1d42bbf90d4c8249734a0",
              "wrong failed projection source")
    c.require(plan["adapter_atol"] == 2e-6 and plan["adapter_rtol"] == 2e-4
              and previous["plan_sha256"] == c.digest(plan) and previous["errors"], "original failed gate was changed")
    left, right = [load_file(str(study / p / "adapter/adapter_model.safetensors")) for p in plan["profiles"]]
    c.require(set(left) == set(right), "projection tensor inventories differ")
    rows = []
    for key in sorted(left):
        a, b = left[key], right[key]
        c.require(a.dtype == b.dtype and a.shape == b.shape and a.numel() > 0
                  and bool(torch.isfinite(a).all()) and bool(torch.isfinite(b).all()), "invalid saved tensor")
        close = torch.isclose(a, b, atol=plan["adapter_atol"], rtol=plan["adapter_rtol"])
        rows.append({"tensor": key, "elements": a.numel(), "mismatched_elements": int((~close).sum()),
                     "max_abs_difference": float((a-b).abs().max())})
    return {"schema": "hepta.projection.saved-drift-inventory.v1", "tensors": rows,
            "mismatched_elements": sum(r["mismatched_elements"] for r in rows),
            "original_atol": plan["adapter_atol"], "original_rtol": plan["adapter_rtol"],
            "original_failure_retained": True, "projection_qualified": False, "new_model_calls": 0}


def run(original_archive, budget_archive, projection_archive, work, output):
    import torch
    from transformers import AutoTokenizer
    import five_reader_response_learning as learning
    import five_reader_response_trial as response
    import five_reader_evidence_pair_trial as parent
    import five_reader_evidence_pairs as pairs
    import reader_fit_audit as fit_audit
    import source_time_evidence as metadata
    from source_time_evidence_trial import project_examples, project_cases
    from five_native_historical_smoke import prepare_materials, snapshot, READER_INVENTORY, LOCOMO_SHA256
    from five_causal_native import SCHEMA, reader_bindings, public_text, generate_exact, count_forwards
    from five_reader_adapter import compose, attach, verify_resident
    from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
    from native import load

    work, output = Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output / "plan.json", PLAN)
    with measured() as preparation:
        budget_root, budget_verification = extract_verified(budget_archive, work / "saved-budget", BUDGET_SHA)
        study, prior = validate_budget(budget_root)
        projection_root, projection_verification = extract_verified(projection_archive, work / "saved-projection", PROJECTION_SHA)
        c.write_new(output / "projection-drift.json", projection_inventory(projection_root))
        original, clean, staging = prepare_materials(Path(original_archive), work / "original-material")
    c.write_new(output / "materials.json", {"cost": preparation, "budget": budget_verification,
        "projection": projection_verification, "original": staging})
    reader = clean / "reader"
    snap = snapshot(reader, "causal_lm", READER_INVENTORY)
    matches = [p for p in original.rglob("*.json") if p.stat().st_size > 50000 and c.file_sha(p) == LOCOMO_SHA256]
    c.require(len(matches) == 1, "exact benchmark missing")
    benchmark = load(matches[0], "locomo", expected_sha256=LOCOMO_SHA256, allow_unresolved_evidence=True)
    chosen, excluded = parent.choose(benchmark)
    tokenizer = AutoTokenizer.from_pretrained(reader, local_files_only=True, trust_remote_code=False)
    capacity = c.load(reader / "config.json")["max_position_embeddings"]
    original_train, train_census = response.training_examples(benchmark, chosen["train"], tokenizer, capacity)
    train, _ = project_examples(original_train, chosen["train"], benchmark.history, metadata.SOURCE_TIME)
    old_cohort = c.load(study / "cohort.json")
    c.require(old_cohort["train_sha256"] == c.digest(train) and old_cohort["excluded_test_families"] == excluded,
              "saved and rebuilt training cohort differ")
    selection, select_census = parent.select_pairs(benchmark, chosen["select"], tokenizer, capacity)
    selection, _ = project_examples(selection, chosen["select"], benchmark.history, metadata.SOURCE_TIME)
    records = [{"question_id": a["question_id"], "family": a["family"], "split": a["split"],
                "request": a["request"], "answer_body": fit_audit.body_example(a)["response"]}
               for a, _ in pairs.paired_examples(train + selection, training=False)]
    comparisons = control.build_comparisons(records)
    previous_cases, _ = project_cases(parent.generation_cases(benchmark, chosen, original_train),
        chosen["train"] + chosen["select"], benchmark.history, metadata.SOURCE_TIME)
    c.require(previous_cases == c.load(study / "public-inputs.json"), "saved public recipient census changed")
    cases = control.generation_plan(previous_cases, comparisons)
    c.write_new(output / "comparison-plan.json", {"comparisons": comparisons, "train_census": train_census,
        "select_census": select_census, "excluded_test_families": excluded})
    c.write_new(output / "public-inputs.json", cases)
    input_seal = c.file_sha(output / "public-inputs.json")
    compiled, compilation_census = {}, []
    for item in comparisons:
        reason = None
        if item["status"] == "available":
            try:
                compiled[item["question_id"]] = control.compile_comparison(tokenizer, item, position_cap=capacity)
            except c.Invalid as error:
                reason = str(error)
        compilation_census.append({"question_id": item["question_id"], "status": item["status"],
            "compiled": item["question_id"] in compiled, "reason": reason, "replacement_selected": False})
    c.write_new(output / "compilation-census.json", compilation_census)
    raw, summaries, errors, tail = [], {}, [], "0" * 64
    with (output / "events.jsonl").open("xb") as journal:
        for arm in ARMS:
            backend, arm_error, load_cost, composition = None, None, None, None
            tail = c.journal_append(journal, {"event": "arm_started", "arm": arm}, tail)
            try:
                with measured() as load_cost:
                    backend = LocalTextGenerator(reader, snap, PLAN["maximum_input_tokens"])
                    if arm != "frozen_reader":
                        bindings = {key: c.digest("content-audit-unused:" + key) for key in c.BINDINGS}
                        bindings.update(reader_bindings(snap, tokenizer.chat_template, PLAN["maximum_input_tokens"], PLAN["maximum_output_tokens"]))
                        base = {"schema": SCHEMA, "kind": "reader", "snapshot": snap, "bindings": bindings}
                        description = compose(study, base, arm + "/adapter", arm + "/training-receipt.json")
                        c.require(description["response_adapter"]["adapter_tensor_sha256"] == prior["arms"][arm]["training"]["adapter_tensor_sha256"],
                                  "selected saved adapter differs from original result")
                        composition = attach(backend, study, description["response_adapter"], snap)
                before = learning.state_digest(backend.loaded.state_dict())
            except Exception as error:
                arm_error = type(error).__name__ + ": " + str(error)[:1024]
                errors.append({"arm": arm, "phase": "load", "error": arm_error})
            arm_raw = []
            for case in cases:
                row = {key: case[key] for key in ("question_id", "family", "split", "condition")}
                row.update(arm=arm, trial_id=c.digest([arm, row]), answer=None, status="not_executed",
                           evidence_ids=[] if case["request"] is None else [e["id"] for e in case["request"]["evidence"]])
                if case["request"] is None:
                    row["status"] = "unavailable_source_or_donor"
                elif arm_error is not None:
                    row.update(status="blocked_model", error=arm_error)
                else:
                    row["public_request_sha256"] = c.digest(case["request"])
                    tail = c.journal_append(journal, {"event": "generation_started", **row}, tail)
                    decoder = learning.training_forward_owner(backend.loaded) if arm != "frozen_reader" else backend.loaded.base_model
                    with measured() as cost, count_forwards(decoder) as calls:
                        try:
                            answer, details = generate_exact(backend, public_text(case["request"]),
                                PLAN["maximum_input_tokens"], PLAN["maximum_output_tokens"])
                            row.update(status="succeeded", answer=answer, **details)
                        except Exception as error:
                            row.update(status="failed", error=type(error).__name__ + ": " + str(error)[:1024])
                    row.update(cost=cost, observed_decoder_forwards=calls["model_calls"], model_attempted=True)
                    if cost["wall_ns"] > PLAN["per_call_seconds"] * 1e9:
                        row["status"] = "timeout_with_observed_output"
                    if row["status"] != "succeeded":
                        errors.append({"arm": arm, "phase": "generation", "trial_id": row["trial_id"]})
                tail = c.journal_append(journal, {"event": "generation_recorded", **row}, tail)
                arm_raw.append(row); raw.append(row)
            c.write_new(output / (arm + "-raw.json"), arm_raw)
            c.write_new(output / (arm + "-raw-seal.json"), {"sha256": c.file_sha(output / (arm + "-raw.json")),
                                                         "before_teacher_forcing": True})
            audits = []
            for comparison in comparisons:
                item = {key: comparison[key] for key in ("question_id", "family", "split", "donor_question_id", "donor_family")}
                item.update(status="unavailable_donor_or_tokens", audit=None, observed_decoder_forwards=0)
                if arm_error is not None:
                    item["status"] = "blocked_model"
                elif comparison["question_id"] in compiled:
                    tail = c.journal_append(journal, {"event": "audit_started", "arm": arm, **item}, tail)
                    decoder = learning.training_forward_owner(backend.loaded) if arm != "frozen_reader" else backend.loaded.base_model
                    with measured() as cost, count_forwards(decoder) as calls:
                        try:
                            result = control.score_comparison(backend.loaded, compiled[comparison["question_id"]])
                            c.require(calls["model_calls"] == 4, "four actual likelihood forwards required")
                            item.update(status="succeeded", audit=result)
                        except Exception as error:
                            item.update(status="failed", error=str(error)[:1024])
                    item.update(cost=cost, observed_decoder_forwards=calls["model_calls"])
                    if item["status"] == "failed": errors.append({"arm": arm, "phase": "audit", "question_id": item["question_id"]})
                tail = c.journal_append(journal, {"event": "audit_recorded", "arm": arm, **item}, tail)
                audits.append(item)
            integrity = False
            if backend is not None and arm_error is None:
                try:
                    c.require(learning.state_digest(backend.loaded.state_dict()) == before, "frozen model changed")
                    if arm != "frozen_reader": verify_resident(backend)
                    backend.close()
                    integrity = True
                except Exception as error: errors.append({"arm": arm, "phase": "integrity", "error": str(error)[:1024]})
            if backend is not None: del backend
            gc.collect()
            scored = response.score_rows(arm_raw, benchmark)
            for score, row in zip(scored, arm_raw): score["split"] = row["split"]
            c.write_new(output / (arm + "-scores.json"), scored)
            c.write_new(output / (arm + "-content-audit.json"), audits)
            summaries[arm] = {"generation": parent.aggregate(scored), "content": control.summarize(audits),
                "load_cost": load_cost, "composition": composition, "model_integrity_verified": integrity,
                "audit_forwards": sum(r["observed_decoder_forwards"] for r in audits), "optimization_steps": 0}
            print(c.canonical({"completed_arm": arm, **summaries[arm]}).decode(), flush=True)
    c.require(len(raw) == len(cases) * len(ARMS) and c.file_sha(output / "public-inputs.json") == input_seal,
              "input or planned census changed")
    c.require(c.file_sha(matches[0]) == LOCOMO_SHA256, "benchmark changed")
    c.write_new(output / "raw-answers.json", raw)
    report = {"schema": "hepta.reader.saved-content-swap-result.v1", "plan_sha256": c.digest(PLAN),
        "raw_sha256": c.file_sha(output / "raw-answers.json"), "planned_rows": len(raw),
        "succeeded": sum(r["status"] == "succeeded" for r in raw), "arms": summaries, "errors": errors,
        "new_optimization_steps": 0, "new_independent_tasks": 0,
        "generation_forward_lower_bound": sum(r.get("observed_decoder_forwards", 0) for r in raw),
        "reader_adequacy_established": False, "projection_qualified": False,
        "independent_confirmation": False, "compute_matched": False, "production_accepted": False}
    c.write_new(output / "report.json", report)
    print("CONTENT_SWAP_RESULT", c.canonical(report).decode(), flush=True)
    c.require(not errors, "read-only content audit has retained failures")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--original-archive", type=Path, required=True)
    p.add_argument("--budget-archive", type=Path, required=True)
    p.add_argument("--projection-archive", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        run(args.original_archive, args.budget_archive, args.projection_archive, args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048], "completed": False})
        raise
