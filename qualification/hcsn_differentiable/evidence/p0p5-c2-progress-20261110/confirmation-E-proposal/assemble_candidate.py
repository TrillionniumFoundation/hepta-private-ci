"""Create source-only E proposal evidence; never import model/data loaders."""

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import zipfile


ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
REPO = WORK / "hcsn-repo"


def identity_bytes(payload):
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def save(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
    return identity_bytes(payload)


def main():
    start, cpu = time.monotonic(), time.process_time()
    source = ROOT / "source-context"
    source.mkdir(exist_ok=False)
    paths = {
        "formal_protocol.json": REPO / "proposals/localization-v2/formal_protocol.json",
        "localization-v2-PROTOCOL.md": REPO / "proposals/localization-v2/PROTOCOL.md",
        "development_episodes.py": REPO / "proposals/localization-v2/episodes.py",
        "legacy_data_loader.py": REPO / "proposals/localization-v2/data.py",
        "localization-v3-README.md": REPO / "proposals/localization-v3/README.md",
        "campaign-v2-plan.json": REPO / "qualification/hcsn_differentiable/evidence/p0p5-20261110/p2/campaign-v2-plan.json",
        "initial_research_protocol.json": REPO / "qualification/hcsn_differentiable/research_protocol.json",
        "resource_analysis.py": WORK / "resource-analysis-v1/analyze_resources.py",
        "c2_auditor_checks.py": WORK / "c2-terminal-independent-auditor-v1/checks.py",
        "c2_terminal_audit_PLAN.json": WORK / "c2-terminal-independent-auditor-v1/PLAN.json",
        "full-d-replay-SUMMARY.json": REPO / "qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/full-d-replay/SUMMARY.json",
    }
    inputs = {}
    for name, original in paths.items():
        payload = original.read_bytes()
        with (source / name).open("xb") as stream:
            stream.write(payload)
        inputs[name] = {"original_path": str(original), "snapshot_path": f"source-context/{name}", **identity_bytes(payload)}
    formal = json.loads((source / "formal_protocol.json").read_text())
    campaign = json.loads((source / "campaign-v2-plan.json").read_text())
    assert formal["formal_fits_started"] == 0
    assert formal["confirmation"]["training_seeds"] == [11, 23, 37, 53, 71]
    constants = {}
    for statement in ast.parse((source / "legacy_data_loader.py").read_text()).body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name) and target.id in {"ARCHIVE_SHA", "DATA_SHA", "DESCRIPTION_SHA", "TAGS", "LABELS"}:
                constants[target.id] = ast.literal_eval(statement.value)
    assert len(constants["LABELS"]) == 11 and len(constants["TAGS"]) == 4
    prior = json.loads((source / "full-d-replay-SUMMARY.json").read_text())
    assert inputs["full-d-replay-SUMMARY.json"]["sha256"] == "04cc502f1bb2b7714982dd1e458c278cd78c48dbd0e8be9a34d513c848f82d16"
    cost_fields = ["name", "whole_child_wall_seconds", "waited_child_CPU_seconds", "sampled_peak_rss_bytes", "self_peak_rss_bytes"]
    basis = {
        "schema": "hcsn-prospective-E-budget-basis-v1",
        "source": inputs["full-d-replay-SUMMARY.json"],
        "scope": "Existing full-D replay JSON timings only. No checkpoint/logits/data read or model execution by this assembly.",
        "fits": [{key: row[key] for key in cost_fields} for row in prior["fits"]],
        "limitations": ["D timings are not an E runtime bound", "E event and episode counts are unread and unknown", "Current co-tenancy may increase time", "The proposed 7200/240 budgets are not allocated or execution authorization"],
    }
    save(ROOT / "BUDGET-BASIS.json", basis)
    arms = ["gru", "cfc", "snn_plif", "event_time_lif", "ssm_s4d", "attention", "hcsn"]
    seeds = [101, 211, 307]
    plan = {
        "schema": "hcsn-prospective-confirmation-E-candidate-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "candidate_only_preserve_E",
        "execution_authorized": False,
        "automatic_trigger": False,
        "E_data_read_in_preparation": False,
        "production_models_read_in_preparation": False,
        "E_evaluation_started": False,
        "new_model_training_authorized": False,
        "formal_confirmation_completed": False,
        "default_action": "Do not consume E. Parent separately decides after all six C2 chains terminate and independent audit/cost review.",
        "chronology": "Prospective only with respect to E. The current three-seed development study, C1 and C2 decisions already exist; this does not preregister them retrospectively.",
        "separate_from_C2_auditor": {"whole_seconds": 1800, "proposal_uses_this_allowance": False, "source": inputs["c2_terminal_audit_PLAN.json"]},
        "formal_protocol": {
            "identity": inputs["formal_protocol.json"],
            "current_status": formal["status"],
            "formal_fits_started": formal["formal_fits_started"],
            "max_configurations_per_arm": formal["tuning"]["max_configurations_per_arm"],
            "tuning_seeds": formal["tuning"]["seed_ids"],
            "candidate_learning_rates": formal["tuning"]["candidate_learning_rates"],
            "candidate_weight_decays": formal["tuning"]["candidate_weight_decays"],
            "candidate_gradient_norm_caps": formal["tuning"]["candidate_gradient_norm_caps"],
            "fresh_confirmation_seeds": formal["confirmation"]["training_seeds"],
            "original_batch_size": formal["training"]["batch_size"],
            "not_completed_by_this_candidate": ["12-config three-seed tuning", "five fresh confirmation-seed refits", "admitted capacity matching", "required mechanism ablations", "whole training-state numerical qualification", "energy and hardware-optimized comparison"],
            "candidate_name": "one independent-subject check of existing three-seed v3 systems",
            "after_E_disclosure": "Later five-seed refits cannot call the same E previously unseen; disclose prior use or acquire new independent confirmation data.",
        },
        "inherited_rules": ["ABC training and frozen frontend", "D-only selection and temperature calibration", "E subject partition", "all 256-event nonoverlapping windows with reset and original artificial-boundary first gap", "11-class metrics and 15-bin ECE", "all attempts, failed and discarded work charged", "one held-out subject limits population inference"],
        "current_development_study": {
            "plan_identity": inputs["campaign-v2-plan.json"],
            "arms": arms,
            "learning_rates": [0.001, 0.003],
            "seeds": seeds,
            "original_fit_opportunities": 42,
            "effective_batch": 32,
            "HCSN_training_microbatch": 8,
            "evaluation_batch": 32,
            "width": 16,
            "training_recipe_equals_formal_protocol": False,
            "C1_C2_are_additional_adaptive_phases": True,
            "old_300_900_1800_curves_unchanged": True,
            "source_capsule_sha256": "288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102",
            "development_manifest_sha256": "0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb",
            "recorded_selection_rule": campaign["selection_rule"],
        },
        "necessary_not_sufficient_gates": [
            "All six original HCSN and C2 opportunities have immutable authentic terminal receipts; no live writer, unknown launch or missing terminal identity.",
            "The separately authorized 1800-second independent C2 auditor has completed chain, strict-best full-D replay, original partial-work and cost checks inside its caps; missing, failed or source-changed checks withhold credit.",
            "Both learning rates and all three seeds retain independently verified D checkpoint quality; no omitted failures or per-seed LR selection.",
            "The higher-mean-D common LR's three seeds all pass the declared memorization/minimum-30/.002-patience10/finite-gradient/source heuristic; no replacement by a lower-scoring adequate LR to unlock E.",
            "All selected baseline three-seed sets meet the same training-adequacy rule; preserve the earlier C1 resume-start-witness limitation.",
            "Parent makes a separate explicit decision after reviewing quality increment, full costs and unresolved numerical/causal issues; binds final plan/program/runtime/checkpoints/D-selection/budget before any E interpretation.",
        ],
        "selection": {
            "quality": "macro_f1_11_classes on full D",
            "within_fit": "first strict maximum over all authentic complete-epoch D observations in the chosen phase chain",
            "per_arm": "maximum arithmetic mean of the same three seeds at a common LR",
            "exact_LR_tie": "0.001 (lower LR); matches frozen current resource/C2 auditor helpers, not the original formal capacity/compute tie rule",
            "missing_seed": "HOLD; do not drop it or replace it with another seed/LR",
            "selection_sources": [inputs["resource_analysis.py"], inputs["c2_auditor_checks.py"]],
            "selected_learning_rates": {arm: None for arm in arms},
            "selection_manifest_sha256": None,
            "all_42_and_C1_C2_costs_retained": True,
        },
        "fixed_E_roster": [{"arm": arm, "seed": seed, "common_learning_rate": None, "checkpoint_sha256": None, "model_configuration_sha256": None, "D_logits_sha256": None, "temperature": None} for arm in arms for seed in seeds],
        "temperature": {
            "scope": "each already-selected model; independently verified D logits only; freeze 21 temperature results before any E read",
            "new_algorithm_choices_not_in_old_protocol": True,
            "objective": "unweighted mean multiclass D NLL; stable logsumexp with per-event max-logit centering",
            "parameter": "inverse temperature beta; T=1/beta",
            "bounds": [0.01, 100.0],
            "gradient": "mean_i(sum_c softmax(beta*z_i)[c]*z_i[c] - z_i[y_i])",
            "hessian": "mean softmax-weighted logit variance; nonnegative",
            "flat_exception": "If every event has exactly equal logits across all 11 classes, beta=1.",
            "endpoints": "If derivative at lower endpoint >=0 choose lower; otherwise if derivative at upper endpoint <=0 choose upper; record boundary optimum.",
            "interior_solver": "Bisection on derivative sign; at most 100 iterations; stop when bracket width <=1e-12*max(1,abs(midpoint)) or no representable strict interior point; choose final bracket midpoint.",
            "receipt": "raw input hashes, finite checks, endpoint gradients, final bracket/beta/NLL and exact argmax agreement",
            "failure_policy": "HOLD before E; no bounds expansion, restarts or post-E recalibration",
        },
        "E_input": {
            "archive_sha256": constants["ARCHIVE_SHA"],
            "raw_text_sha256": constants["DATA_SHA"],
            "description_sha256": constants["DESCRIPTION_SHA"],
            "sequences": [f"E0{i}" for i in range(1, 6)],
            "events": None,
            "episodes": None,
            "new_E_manifest_sha256": None,
            "prior_exposure": "Legacy whole-file schema/clock/gap integrity audit included E; no E feature fitting, model selection, calibration or scoring. Do not claim feature/schema blindness.",
            "featurizer": "new isolated E-only preparation, using the exact previously frozen ABC frontend and original tag/label order; existing ABC/D manifest cannot stand in for E",
            "order": "sequence E01..E05, then integer tick, then original source line",
            "window_size_stride": [256, 256],
            "first_gap": "natural sequence start dt=0; every artificial window retains its original previous-source-event gap",
            "tail": "retain all incomplete final windows and events",
            "features": "12 ABC-normalized observed coordinates +12 observation masks +log1p(delta_ticks/10000000)",
            "forbidden": ["fit/re-estimate frontend on E", "label-based selection", "clip or resample gaps", "delete repeated ticks", "change reset/history", "search windows or thresholds"],
            "label_separation": "preparer saves features/order and labels as separately hashed artifacts; prediction workers receive only features/dt/length/valid mask, not activity labels; all 21 prediction artifacts must be immutable before the independent scorer opens labels",
        },
        "evaluation": {
            "models": 21,
            "workers": 1,
            "CPU_threads": 1,
            "device": "cpu",
            "dtype": "float64",
            "batch_size": 32,
            "cache": "cold per model, inside its charged process time",
            "source": "exact existing v8 forward/runtime/config and frozen shared tensors; no updated training implementation substituted",
            "training_updates": 0,
            "backward_calls": 0,
            "optimizer_construct_restore_step_operations": 0,
            "checkpoint_metadata_deserialization": "allowed for safe original-file loading; unused optimizer/RNG metadata discarded in memory; no checkpoint writes",
            "one_full_pass_per_selected_model": True,
            "unselected_LR_E_evaluation": False,
            "selected_best_not_last": True,
            "failure": "retain fixed roster and all known costs; no retries, seed/checkpoint substitution or partial comparative conclusion; global source failure aborts remaining opportunities",
            "artifacts": ["before/after input/model/source hashes", "full ordered logits", "separate labels and exact source-row/episode/position order", "all batch/process/whole logs and terminal rusage", "raw and calibrated metrics", "complete cost and missingness ledger"],
        },
        "reporting": {
            "primary_quality": "11-class macro-F1, zero_division=0 for any absent class",
            "primary_paired_comparator": "HCSN minus GRU at matched seed; report all three raw differences and their mean/sample SD",
            "other_comparators": ["cfc", "snn_plif", "event_time_lif", "ssm_s4d", "attention"],
            "secondary": ["accuracy", "11x11 confusion matrix", "present-class balanced accuracy", "present-class macro-F1", "raw/calibrated NLL", "raw/calibrated 15-equal-width-bin ECE", "raw/calibrated half-sum Brier", "raw/calibrated mean-class Brier"],
            "ECE_bin_definition": "[k/15,(k+1)/15) for k<14; final bin includes confidence=1",
            "Brier_definitions": {"half_sum": "mean_i(sum_c (p_ic-y_ic)^2)/2", "mean_class": "mean_i(sum_c (p_ic-y_ic)^2)/11"},
            "tables": "overall plus E01..E05; each seed, three-seed arithmetic mean and sample SD; no best-seed expected-quality claim",
            "bootstrap": {"replicates": 5000, "rng": "Python random.Random(20261110), pinned runtime", "draw": "five independent randrange(5) indices per replicate, shared by all models and seeds", "unit": "whole E sequence; pool each selected sequence confusion matrix with multiplicity", "statistic": "mean over three seed-paired macro-F1 differences", "percentiles": [0.025, 0.975], "quantile": "sort 5000 values; linear interpolation at q*(5000-1)", "claim": "descriptive single-subject sequence-cluster uncertainty only"},
            "inferential_claim": "No confirmatory population superiority or causal mechanism claim; three-seed two-sided sign-flip space has only 8 possibilities (minimum attainable p=.25).",
            "incomplete_21_roster": "HOLD; preserve artifacts/failed costs but withhold complete comparative conclusion",
        },
        "candidate_budget": {
            "allocated": False,
            "authorization": None,
            "whole_hard_seconds": 7200,
            "workers": 1,
            "CPU_threads": 1,
            "RSS_bytes": 2 * 1024**3,
            "address_space_bytes": 8 * 1024**3,
            "context_and_data_total_seconds": 600,
            "D_calibration_total_seconds": 600,
            "per_model_full_E_seconds": 240,
            "scoring_statistics_total_seconds": 600,
            "internal_finalization_reserve_seconds": 120,
            "declared_stage_maxima_plus_reserve_seconds": 6960,
            "remaining_budget_rule": "admit each stage only within min(stage grant, actual whole remaining minus internal reserve); reserve is not extra time or a completion guarantee; final archive verification and exit must remain within whole cap",
            "retry_limit": 0,
            "extension_after_E_observation": False,
            "basis": "BUDGET-BASIS.json; original D timings are not a runtime guarantee for unread E",
        },
        "costs": {
            "include": ["all original 42 opportunities", "all C1/C2 phases and discarded partial work", "PLIF tuning and failures", "HCSN qualification/probes and failures", "independent audit/replay", "data/frontend", "D calibration", "E prediction/scoring", "transfer and publication where measured"],
            "nested_costs": "record named scopes; do not add an inner fit or calibration timer again to its containing full process cost",
            "parallel_wall": "retain calendar interval and individual attempt wall; do not sum concurrent walls and call it end-to-end elapsed time",
            "missing_historical_CPU_energy_VRAM_money": None,
            "complete_lifetime_accounting_claim": False,
        },
        "remaining_implementation_before_separate_decision": ["source-bound E-only feature/label isolation and semantic fixtures", "temperature optimizer finite/convex/boundary/synthetic checks", "metric/order/hash/cap/missing-artifact negative tests", "exclusive read-only model forward and archive admission", "complete selected-checkpoint and D-calibration manifest", "independent review of final program and precise authorization"],
        "scientific_status": "HOLD; any eventual E result would be a supplementary independent-subject check of existing systems, not completion of the formal recipe or numerical/causal/energy gates",
    }
    assert len(plan["fixed_E_roster"]) == 21
    assert set(campaign["arms"]) == set(arms)
    save(ROOT / "PLAN.json", plan)
    for name, original in paths.items():
        assert identity_bytes(original.read_bytes()) == {k: inputs[name][k] for k in ("bytes", "sha256")}, name
    save(ROOT / "INPUTS.json", {"schema": "hcsn-source-only-E-proposal-inputs-v1", "files": inputs, "source_before_equals_after": True, "read_scope": "source/protocol text and previously archived D timing summary only; no raw E, checkpoints, logits or active C2 outputs"})
    links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", (ROOT / "PROPOSAL.md").read_text())
    for link in links:
        assert (ROOT / link).resolve().is_relative_to(ROOT) and (ROOT / link).is_file(), link
    save(ROOT / "ASSEMBLY-RECEIPT.json", {
        "schema": "hcsn-source-only-proposal-assembly-v1",
        "status": "candidate_text_and_JSON_integrity_only",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshots": len(inputs),
        "proposal_links_checked": links,
        "JSON_serialization_allow_nan": False,
        "execution_authorized": False,
        "E_reads": 0,
        "model_reads": 0,
        "model_executions": 0,
        "wall_seconds_through_receipt_assembly": time.monotonic() - start,
        "own_CPU_seconds_through_receipt_assembly": time.process_time() - cpu,
        "cost_scope": "Assembly prefix after Python imports; excludes original manual source review, final receipt serialization, manifest/ZIP writing and tool outer process. These fields are not a complete execution cost.",
        "prior_manual_review_exact_CPU_wall": None,
    })
    files = {str(path.relative_to(ROOT)): identity_bytes(path.read_bytes()) for path in sorted(ROOT.rglob("*")) if path.is_file()}
    manifest_identity = save(ROOT / "MANIFEST.json", {"schema": "hcsn-prospective-E-candidate-manifest-v1", "execution_authorized": False, "files": files})
    destination = ROOT.with_suffix(".zip")
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(set(archive.namelist())) == len(files) + 1
        for name, expected in files.items():
            assert identity_bytes(archive.read(name)) == expected
        assert identity_bytes(archive.read("MANIFEST.json")) == manifest_identity
    print(json.dumps({"directory": str(ROOT), "manifest": manifest_identity, "zip": {"path": str(destination), **identity_bytes(destination.read_bytes())}, "PLAN": identity_bytes((ROOT / "PLAN.json").read_bytes()), "members": len(files) + 1, "model_or_E_access": False}, sort_keys=True))


if __name__ == "__main__":
    main()
