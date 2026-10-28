"""Actual old-source implementation study of the new learned NDU host actor.

All source/scenario/optimizer choices are frozen before new outcomes. This uses
already consumed train/development material and cannot qualify natural ability.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..continuation_20261027.control.client import sha
from ..unified_20261028.natural_model import NaturalPortfolio, SCORE_SPEC
from ..unified_20261028.profile import certainty_equivalent, digest, log_moment
from .control_actor import fit_actor
from .control_adapter import ExistingNaturalAdapter
from .control_episode import execute_episode
from .control_table import fit_table
from .profile_contract import Prices, WorkBudget, continuation_contract, cpu_seconds, make_profile, support_status


TRAIN_SOURCES, DEVELOPMENT_SOURCES, SEED = 16, 8, 28261003
SCENARIOS = ((False, 7, 2), (True, 7, 2), (True, 6, 2), (False, 6, 2),
             (True, 7, 1), (False, 7, 1), (False, 7, 2), (True, 7, 2))


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def select_sources(events, split, count):
    selected, seen = [], set()
    for index, item in enumerate(events):
        if item["split"] == split and item["source_id"] not in seen:
            selected.append({"index": index, **item})
            seen.add(item["source_id"])
            if len(selected) == count:
                return selected
    raise ValueError("The declared old-source study has insufficient source clusters")


def run(*, binary, checkpoint, assets, output, actor_kind="loglink"):
    wall_start, cpu_start = time.perf_counter(), cpu_seconds()
    binary, checkpoint, assets, output = map(Path, (binary, checkpoint, assets, output))
    output.mkdir(parents=True, exist_ok=False)
    package = Path(__file__).resolve().parent
    prior = package.parent / "unified_20261028"
    owner = package.parent / "closure_v2_20261027/control/evidence/development-001"
    owner_freeze = json.loads((owner / "FROZEN.json").read_text())
    if sha(binary) != owner_freeze["binary_sha256"]:
        raise ValueError("The unchanged original-owner binary is required")
    events_doc = json.loads((assets / "EVENTS.json").read_text())
    if sha(assets / "EVENTS.npz") != events_doc["arrays_sha256"]:
        raise ValueError("Old-source arrays no longer match their manifest")
    training = select_sources(events_doc["events"], "train", TRAIN_SOURCES)
    development = select_sources(events_doc["events"], "development", DEVELOPMENT_SOURCES)
    if {r["source_id"] for r in training}.intersection(r["source_id"] for r in development):
        raise ValueError("Actor training and implementation evaluation overlap sources")
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    loaded = torch.load(checkpoint, weights_only=True, map_location="cpu")
    model = NaturalPortfolio(loaded["vocabulary"]).eval().requires_grad_(True)
    model.load_state_dict(loaded["model"])
    code = [package / name for name in ("control_study.py", "control_actor.py", "control_episode.py", "control_table.py",
                                       "control_adapter.py", "profile_contract.py")]
    code += [prior / name for name in ("profile.py", "control.py", "natural_model.py", "native_joint_episode.py")]
    code += [package.parent / "continuation_20261027/control/client.py"]
    source_hashes = {str(path.relative_to(package.parent)): sha(path) for path in code}
    budget, prices = WorkBudget(), Prices()
    emission = {"family": "existing bounded NaturalPortfolio; four fixed-noise Gaussian/categorical emissions",
                "initial_checkpoint_sha256": sha(checkpoint), "initial_parent_profile_sha256": loaded["profile_sha256"],
                "migration": "same inherited tensors/law re-evaluated under this NEW actual host continuation and complete cost profile",
                "dimensions": "4x32x32 RGB frames, 32x32 RGB image, 0.5s/8kHz audio, 16 categorical tokens",
                "retry": "new independent conditional draw from advanced episode RNG; every executed density counted once",
                "fault": "declared initial video payload truncation before its sole metered write; actual readback detects failure"}
    authority = {"binary_sha256": sha(binary), "readout_sha256": sha(owner / "MODEL.json"),
                 "calibration_sha256": sha(owner / "ENCODER_DOMAIN_PROOF.json"),
                 "owner_unchanged": True, "authority": "DENY_ALL"}
    continuation = continuation_contract(authority=authority, emission=emission,
                                         source_hashes=source_hashes, budget=budget, prices=prices)
    if actor_kind not in {"loglink", "source_table"}:
        raise ValueError("Actor estimator must be selected before any outcomes")
    continuation["frozen_actor_estimator"] = actor_kind
    observer = {"source_sha256": sha(prior / "natural_model.py"),
                "gross_score": {k: v for k, v in SCORE_SPEC.items() if k not in {"cost", "fixed_horizon"}},
                "reopen_sha256": sha(prior / "native_joint_episode.py"),
                "scope": "existing bounded reconstruction observer; not adequate open-domain semantics"}
    profile, objective = make_profile(observer=observer, continuation=continuation)
    protocol = {"schema": "hepta.ndu.learned-host-implementation-study.v1", "profile_sha256": profile.digest,
                "source_manifest_sha256": sha(assets / "EVENTS.json"), "source_arrays_sha256": sha(assets / "EVENTS.npz"),
                "training_sources": training, "development_sources": development,
                "source_status": "already consumed historical train/development only; not fresh qualification",
                "scenarios": SCENARIOS, "seed": SEED, "initial_checkpoint_sha256": sha(checkpoint),
                "training_design": "two complete actual action interventions per source; paired initial RNG for comparison",
                "development_arms": ["ndu_host", "always_keep", "always_swap"],
                "actor_fit": ({"kind": "loglink", "steps": 400, "learning_rate": .03, "regularizer": None}
                              if actor_kind == "loglink" else {"kind": "source_table", "fit_role": "train only",
                                  "strata": "feedback, owner abstention, available media slots", "hyperparameter_search": False}),
                "frozen_before_first_new_emission": True, "objective": objective, "observer": observer,
                "continuation": continuation, "work_budget": budget.to_dict(), "prices": asdict(prices),
                "qualification": False, "efficacy_claim": False, "production_gates_passed": False}
    save(output / "PROTOCOL.json", protocol)
    save(output / "PROFILE.json", profile.to_dict())
    save(output / "FROZEN.json", {"protocol_sha256": sha(output / "PROTOCOL.json"),
                                 "profile_sha256": profile.digest, "sources": source_hashes})
    namespace = digest({"output": str(output.resolve()), "profile": profile.digest})[:16]
    rows, training_rows = [], []

    def complete(item, ordinal, phase, arm, actor=None):
        episode_started_cpu = cpu_seconds()
        fault, expires, media_budget = SCENARIOS[ordinal % len(SCENARIOS)]
        # Common random numbers across actual arms are deliberate paired design,
        # not extra independent evidence. Every arm physically executes again.
        seed = SEED + int(phase == "development") * 10000 + ordinal
        case = f"{namespace}-{phase}-{ordinal:02d}-{arm}"
        adapter = ExistingNaturalAdapter(model=model, checkpoint=checkpoint, assets=assets,
                                         item=item, seed=seed, fault=fault)
        forced = {"keep": "keep", "swap": "swap", "always_keep": "keep", "always_swap": "swap"}.get(arm)
        _, _, receipt = execute_episode(profile=profile, actor=actor, prepare=adapter.prepare, emit=adapter.emit,
                                        terminal_score=adapter.terminal_score, binary=binary,
                                        readout=owner / "MODEL.json", calibration=owner / "ENCODER_DOMAIN_PROOF.json",
                                        checkpoint=checkpoint, directory=output / case, case=case,
                                        implementation_paths=code, budget=budget, prices=prices,
                                        episode_started_cpu=episode_started_cpu,
                                        expires=expires, media_budget=media_budget, forced_action=forced)
        receipt.update(arm=arm, seed=seed, scenario={"fault": fault, "expires": expires, "media_budget": media_budget},
                       source_event={k: item[k] for k in ("event_id", "source_id", "split", "index")})
        if phase == "train":
            receipt["sampling_design"] = "paired_complete_actions"
        save(output / case / "EPISODE.json", receipt)
        rows.append(receipt)
        print(json.dumps({"phase": phase, "index": ordinal, "arm": arm,
                          "selected": receipt["selected_action"], "executed": receipt["executed_action"],
                          "net_return": receipt["net_return"], "cpu_seconds": receipt["cpu_seconds"]}), flush=True)
        return receipt

    for index, item in enumerate(training):
        for action in ("keep", "swap"):
            training_rows.append(complete(item, index, "train", action))
    actor, fit = (fit_actor(training_rows, profile) if actor_kind == "loglink" else fit_table(training_rows, profile))
    save(output / "ACTOR.json", actor.to_dict())
    save(output / "ACTOR_FIT.json", fit)
    save(output / "POLICY_FROZEN.json", {"actor_sha256": actor.digest, "actor_file_sha256": sha(output / "ACTOR.json"),
                                        "profile_sha256": profile.digest, "training_records_sha256": digest(training_rows),
                                        "frozen_before_development": True})
    for index, item in enumerate(development):
        for arm in protocol["development_arms"]:
            complete(item, index, "development", arm, actor)
    selected = [r for r in rows if r["arm"] == "ndu_host"]
    measurements = {}
    for arm in protocol["development_arms"]:
        arm_rows = [r for r in rows if r["arm"] == arm]
        values = [r["net_return"] for r in arm_rows]
        measurements[arm] = {"actual_episodes": len(values), "descriptive_ce": certainty_equivalent(values, profile.gamma),
                             "descriptive_log_moment": log_moment(values, profile.gamma),
                             "mean_net_return": float(np.mean(values)),
                             "actual_cpu_seconds": sum(r["cpu_seconds"] for r in arm_rows),
                             "actual_cost": sum(c["amount"] for r in arm_rows for c in r["complete_costs"]),
                             "selected_swaps": sum(r["selected_action"] == "swap" for r in arm_rows),
                             "executed_retries": sum(r["executed_action"] == "swap" for r in arm_rows),
                             "failed_terminal": sum(r["terminal_kind"] == "failed" for r in arm_rows)}
    checks = {"one_profile_training_planning_deployment_scoring": all(r["profile_sha256"] == profile.digest for r in rows),
              "learned_actor_controls_real_path": all(r["policy_sha256"] == actor.digest for r in selected),
              "deployed_selected_action_is_predicted_moment_minimum": all(r["selected_action"] == min(
                  ("keep", "swap"), key=lambda a: r["decision"]["predicted_complete_moments"][a]) for r in selected),
              "original_owner_authority_unchanged": all(r["native_authority"] == "DENY_ALL" for r in rows),
              "all_actual_generations_have_one_density": all(len(r["samples"]) == len(r["emissions"]) for r in rows),
              "every_physical_CPU_charge_once": all(sum(c["kind"] == "complete_self_children_cpu" for c in r["complete_costs"]) == 1 for r in rows),
              "only_observer_after_actual_stop": all(r["private_scoring_started_ns"] >= r["owner_closed_ns"] for r in rows),
              "failure_costs_retained": all(r["net_return"] < 0 for r in rows if r["terminal_kind"] == "failed"),
              "actual_owner_and_work_caps": all(r["native_execution"]["measurements"]["actual_original_kernel_executions"] == 17
                                               and len(r["emissions"]) <= 2 for r in rows),
              "no_qualification_sources_consumed": all(r["split"] in {"train", "development"} for r in rows)}
    if not all(checks.values()):
        raise ValueError(f"Actual host integration failed: {checks}")
    summary = {"schema": "hepta.ndu.learned-host-implementation-result.v1", "checks": checks,
               "profile_sha256": profile.digest, "actor_sha256": actor.digest,
               "actual_training_episodes": len(training_rows), "actual_development_episodes": len(rows) - len(training_rows),
               "actual_emissions": sum(len(r["emissions"]) for r in rows), "actual_native_kernels": 17 * len(rows),
               "actual_failed_terminal_episodes": sum(r["terminal_kind"] == "failed" for r in rows),
               "host_selections_differing_from_legacy_proposal": sum(r["selected_action"] != (
                   "swap" if r["boundary_context"]["native_readout_proposal"] else "keep") for r in selected),
               "development_comparisons_descriptive_only": measurements,
               "total_episode_cpu_seconds": sum(r["cpu_seconds"] for r in rows),
               "outside_episode_training_setup_reporting_cpu_seconds": cpu_seconds() - cpu_start - sum(r["cpu_seconds"] for r in rows),
               "total_wall_seconds": time.perf_counter() - wall_start,
               "resource_support": support_status(budget, prices), "new_qualification": False,
               "efficacy_claim": False, "strict_NDU_tail_certificate": False,
               "remaining_blockers": ["future physical CPU cost has no proved support or tail moment envelope",
                                      "fresh source-disjoint selected-policy calibration required",
                                      "natural semantic observer and generation capability need the separate new study"]}
    save(output / "SUMMARY.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for argument in ("binary", "checkpoint", "assets", "output"):
        parser.add_argument("--" + argument, required=True)
    parser.add_argument("--actor-kind", choices=("loglink", "source_table"), default="loglink")
    run(**vars(parser.parse_args()))
