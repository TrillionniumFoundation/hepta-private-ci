"""Read-only crossed evidence followthrough for the exact saved small-Head run.

No optimizer, new donor selection, Reader, pretrained update or outcome-based
checkpoint selection. Recompute the original feature cache once because the
first study did not export feature tensors; account for that repeated work.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re

import five_causal_experiments as c
import shared_question_gate as gate
import shared_gate_crossed_evidence as crossed

SELECT_SOURCE = "1672d4b3debb65bf0d7198464d9dc0c55811f08e"
SELECT_SHA = "aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa"


def dependency(run, artifacts):
    c.require(isinstance(run, dict) and isinstance(artifacts, dict), "authenticated metadata required")
    c.require(type(run.get("id")) is int and run["id"] == crossed.GATE_RUN
              and run.get("head_sha") == crossed.GATE_SOURCE
              and run.get("path") == ".github/workflows/hepta-shared-question-gate.yml"
              and run.get("repository", {}).get("full_name") == "TrillionniumFoundation/hepta-private-ci"
              and run.get("head_repository", {}).get("full_name") == "TrillionniumFoundation/hepta-private-ci",
              "wrong saved gate origin")
    c.require(type(run.get("run_attempt")) is int and run["run_attempt"] >= 1, "run attempt missing")
    common = {"run": crossed.GATE_RUN, "source": crossed.GATE_SOURCE,
              "run_attempt": run["run_attempt"], "observed_status": run.get("status"),
              "observed_conclusion": run.get("conclusion"),
              "metadata_sha256": c.digest([run, artifacts]), "model_execution_completed": False}
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return common | {"ready": False, "status": "deferred_no_successful_head_study"}
    entries = artifacts.get("artifacts")
    c.require(isinstance(entries, list) and type(artifacts.get("total_count")) is int
              and artifacts["total_count"] == len(entries) <= 100
              and all(isinstance(x, dict) for x in entries), "incomplete artifact page")
    matches = [x for x in entries if x.get("name") == crossed.GATE_ARTIFACT]
    c.require(len(matches) == 1, "one exact gate artifact required")
    a = matches[0]
    c.require(type(a.get("id")) is int and a["id"] > 0 and a.get("expired") is False
              and type(a.get("size_in_bytes")) is int and a["size_in_bytes"] > 0
              and re.fullmatch(r"sha256:[0-9a-f]{64}", str(a.get("digest")))
              and a.get("workflow_run", {}).get("id") == crossed.GATE_RUN
              and a.get("workflow_run", {}).get("head_sha") == crossed.GATE_SOURCE, "invalid artifact identity")
    return common | {"ready": True, "status": "ready_for_read_only_audit",
                     "artifact_id": a["id"], "artifact_sha256": a["digest"].split(":")[1]}


def validate_saved(root):
    from shared_question_gate_trial import PLAN
    root = Path(root); study = root / "study"
    c.require((root / "source/tested-commit.txt").read_text().strip() == crossed.GATE_SOURCE
              and not (study / "failure.json").exists(), "wrong or failed original Head execution")
    report, public, raw = (c.load(study / name) for name in ("report.json", "public-feature-plan.json", "raw-logits.json"))
    c.require(c.load(study / "plan.json") == c.load(study / "plan.json")
              and c.canonical(c.load(study / "plan.json")) == c.canonical(PLAN)
              and report["schema"] == gate.PROFILE + ".result" and report["errors"] == []
              and report["plan_sha256"] == c.digest(PLAN)
              and report["public_plan_sha256"] == c.file_sha(study / "public-feature-plan.json")
              and report["raw_sha256"] == c.file_sha(study / "raw-logits.json")
              and c.load(study / "prediction-seal.json") == {"sha256": report["raw_sha256"], "before_summary": True},
              "saved study/plan/raw identity mismatch")
    names = {a + "-" + str(s) for a in gate.ARMS for s in gate.SEEDS}
    c.require(set(raw) == set(report["head_parameters"]) == set(report["summaries"]) == names, "incomplete five-arm three-seed census")
    for name in sorted(names):
        folder = study / "heads" / name
        receipt = c.load(folder / "training-receipt.json")
        c.require(c.load(folder / "raw-logits.json") == raw[name]
                  and c.file_sha(folder / "raw-logits.json") == receipt["raw_prediction_sha256"]
                  and c.file_sha(folder / "head.safetensors") == receipt["checkpoint_file_sha256"]
                  and receipt["checkpoint_reload_equal"] is True
                  and receipt["saved_model"] == report["head_parameters"][name]
                  and gate.summarize(public["units"], raw[name]) == report["summaries"][name], "saved Head receipt mismatch")
    return study, report, public, raw


def run(original_archive, cancelled_archive, select_archive, head_archive, head_sha256, work, output):
    import torch
    from safetensors.torch import load_file, save_file
    from transformers import AutoTokenizer
    import relevance_recovery as recovery
    import select_question_relevance as protocol
    from reader_content_swap_trial import extract_verified
    from five_native_historical_smoke import prepare_materials, snapshot, ENCODER_INVENTORY
    from five_causal_native import count_forwards
    from experiments.shared_stem_cell.execution import LocalEncoder, measured, parameters, tensor_digest

    work, output = Path(work), Path(output)
    c.require(c.sha(head_sha256), "external saved-Head artifact SHA required")
    output.mkdir(parents=True, exist_ok=False); torch.set_num_threads(2)
    config = {"schema": crossed.PROFILE, "head_source": crossed.GATE_SOURCE, "head_run": crossed.GATE_RUN,
              "head_archive_sha256": head_sha256, "seeds": gate.SEEDS, "arms": gate.ARMS,
              "replay_atol": crossed.REPLAY_ATOL, "replay_rtol": crossed.REPLAY_RTOL,
              "new_optimizer_updates": 0, "new_reader_calls": 0, "new_donor_selection": False}
    c.write_new(output / "plan.json", config)
    with measured() as acquisition:
        hr, hv = extract_verified(head_archive, work / "heads", head_sha256)
        study, prior, old_public, old_raw = validate_saved(hr)
        cr, cv = extract_verified(cancelled_archive, work / "cancelled", recovery.CANCELLED_SHA)
        sr, sv = extract_verified(select_archive, work / "select", SELECT_SHA)
        c.require((cr / "source/tested-commit.txt").read_text().strip() == recovery.CANCELLED_SOURCE
                  and (sr / "source/tested-commit.txt").read_text().strip() == SELECT_SOURCE, "wrong pair provenance")
        inventory = c.load(sr / "study/inventory-plan.json")
        selected = protocol.build_plan(inventory, c.load(cr / "study/public-inputs.json"))
        rebuilt = gate.public_plan(c.load(cr / "study/train-plan.json"), selected)
        c.require(rebuilt == old_public, "original feature plan cannot be reproduced")
        plan = crossed.build_plan(old_public, selected, inventory)
        _, clean, staged = prepare_materials(Path(original_archive), work / "original")
    c.write_new(output / "materials.json", {"heads": hv, "cancelled": cv, "select": sv, "original": staged, "cost": acquisition})
    c.write_new(output / "crossed-inputs.json", plan); plan_seal = c.file_sha(output / "crossed-inputs.json")
    folder = clean / "encoder"; snap = snapshot(folder, "encoder", ENCODER_INVENTORY)
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True, trust_remote_code=False)
    cap = min(gate.MAXIMUM_TOKENS, c.load(folder / "config.json")["max_position_embeddings"])
    old_pre = gate.token_preflight(tokenizer, old_public, cap)
    extra_public = {"features": plan["additional_features"], "units": plan["units"]}
    extra_pre = gate.token_preflight(tokenizer, extra_public, cap) if plan["additional_features"] else None
    c.write_new(output / "preflight.json", {"original": old_pre, "additional": extra_pre})
    c.require(old_pre == c.load(study / "token-preflight.json") and old_pre["all_within_cap"]
              and (extra_pre is None or extra_pre["all_within_cap"]), "token drift or over-cap original source; no replacement")
    tail, backend, raw, replays = "0" * 64, None, {}, {}
    with (output / "events.jsonl").open("xb") as journal:
        tail = c.journal_append(journal, {"event": "encoder_started"}, tail)
        try:
            with measured() as encoder_cost:
                backend = LocalEncoder(folder, snap, cap)
                with count_forwards(backend.model) as counter:
                    features, base_receipt = gate.encode_once(backend, old_public, old_pre)
                    c.require(base_receipt["encoder"] == prior["encoder"]["encoder"], "different Encoder weights")
                    extra_receipt = None
                    if extra_pre is not None:
                        extra, extra_receipt = gate.encode_once(backend, extra_public, extra_pre)
                        c.require(not set(extra) & set(features), "additional cache overwrites original")
                        features.update(extra)
        except Exception as error:
            tail = c.journal_append(journal, {"event": "encoder_failed", "error": str(error)[:1024],
                "known_dispatches": counter["model_calls"] if "counter" in locals() else 0,
                "unobserved_tail_unknown": True}, tail)
            raise
        finally:
            if backend is not None: backend.close()
        feature_identity = c.digest({k: tensor_digest(v) for k, v in sorted(features.items())})
        save_file(features, str(output / "frozen-features.safetensors"))
        c.write_new(output / "encoder-receipt.json", {"original_recomputation": base_receipt,
            "additional": extra_receipt, "actual_forwards": counter["model_calls"], "cost": encoder_cost,
            "feature_tensor_sha256": feature_identity, "feature_file_sha256": c.file_sha(output / "frozen-features.safetensors"),
            "recomputed_original_features_are_paid_work": True, "new_reader_calls": 0})
        for seed in gate.SEEDS:
            for arm in gate.ARMS:
                name = arm + "-" + str(seed); folder = study / "heads" / name
                tail = c.journal_append(journal, {"event": "head_reload_started", "name": name}, tail)
                kind = "linear" if arm == "linear_aligned" else "evidence" if arm == "evidence_only" else "gated"
                model = gate.QuestionGate(next(iter(features.values())).numel(), kind=kind)
                model.load_state_dict(load_file(str(folder / "head.safetensors")), strict=True)
                model.eval().requires_grad_(False); before = parameters(model)
                c.require(before == prior["head_parameters"][name], "saved Head identity mismatch")
                old_index = crossed.index(old_raw[name], "pair_id"); checks = []; rows = []
                def score(variants):
                    q = torch.stack([features[v["question_key"]] for v in variants])
                    e = torch.stack([features[v["evidence_key"]] for v in variants])
                    return model(q, e)
                with torch.no_grad(), measured() as head_cost, count_forwards(model) as head_calls:
                    for unit in old_public["units"]:
                        if unit["status"] != "available": continue
                        values = score(unit["variants"])
                        target = torch.tensor(old_index[unit["pair_id"]]["logits"], dtype=values.dtype)
                        ok = bool(torch.allclose(values, target, atol=crossed.REPLAY_ATOL, rtol=crossed.REPLAY_RTOL))
                        checks.append({"pair_id": unit["pair_id"], "max_abs_difference": float((values-target).abs().max()), "passed": ok})
                    c.write_new(output / (name + "-replay.json"), checks)
                    c.require(all(x["passed"] for x in checks), "original logits not reproduced; no tolerance adaptation")
                    for unit in plan["units"]:
                        row = {"pair_id": unit["pair_id"], "status": "unavailable", "logits": None}
                        if unit["status"] == "available":
                            # Only the two missing own-evidence corners are new Head predictions.
                            fresh = score([unit["variants"][0], unit["variants"][2]]).tolist()
                            bb, ab = old_index[unit["pair_id"]]["logits"]
                            row.update(status="succeeded", logits=[fresh[0], ab, fresh[1], bb])
                        rows.append(row)
                c.require(before == parameters(model), "read-only Head changed")
                c.write_new(output / (name + "-raw.json"), rows)
                raw[name] = rows
                replays[name] = {"checked_pairs": len(checks), "all_passed": True,
                                 "actual_head_forwards": head_calls["model_calls"], "cost": head_cost}
                tail = c.journal_append(journal, {"event": "head_predictions_sealed", "name": name,
                    "raw_sha256": c.file_sha(output / (name + "-raw.json")), "model_unchanged": True}, tail)
        c.write_new(output / "raw-logits.json", raw)
        c.write_new(output / "prediction-seal.json", {"sha256": c.file_sha(output / "raw-logits.json"), "before_summary": True})
        c.require(feature_identity == c.digest({k: tensor_digest(v) for k,v in sorted(features.items())})
                  and plan_seal == c.file_sha(output / "crossed-inputs.json"), "input changed")
    result = {"schema": crossed.PROFILE + ".result", "errors": [], "plan_sha256": c.digest(config),
              "raw_sha256": c.file_sha(output / "raw-logits.json"), "replays": replays,
              "summaries": {name: crossed.summarize(plan["units"], rows) for name, rows in raw.items()},
              "new_optimizer_updates": 0, "new_reader_calls": 0, "semantic_accuracy": None,
              "independent_confirmation": False, "compute_matched": False, "production_accepted": False}
    c.write_new(output / "report.json", result)
    print("CROSSED_GATE_RESULT", c.canonical(result).decode(), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dependency", "run"))
    for name in ("run-json", "artifacts-json", "original-archive", "cancelled-archive", "select-archive", "head-archive", "work", "output"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--head-sha256")
    args = parser.parse_args()
    c.require(args.output is not None, "output required")
    if args.mode == "dependency":
        result = dependency(c.load(args.run_json), c.load(args.artifacts_json))
        c.write_new(args.output, result)
        print(c.canonical(result).decode(), flush=True)
        raise SystemExit(0 if result["ready"] else 3)
    try:
        run(args.original_archive, args.cancelled_archive, args.select_archive, args.head_archive,
            args.head_sha256, args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048], "model_execution_completed": False, "production_accepted": False})
        raise
