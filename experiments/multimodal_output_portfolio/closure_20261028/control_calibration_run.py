"""Execute one frozen learned host policy on separately reserved new sources."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import torch

from ..continuation_20261027.control.client import sha
from ..unified_20261028.natural_model import NaturalPortfolio
from ..unified_20261028.profile import NduProfile, digest
from .control_adapter import ExistingNaturalAdapter
from .control_episode import execute_episode
from .control_study import save
from .control_table import TableActor
from .profile_contract import Prices, WorkBudget, cpu_seconds
from .tail_calibration import CalibrationPlan, calibrate_actual


def run(*, assets, parent, checkpoint, binary, output):
    started, cpu_start = time.perf_counter(), cpu_seconds()
    assets, parent, checkpoint, binary, output = map(Path, (assets, parent, checkpoint, binary, output))
    output.mkdir(parents=True, exist_ok=False)
    package = Path(__file__).resolve().parent
    source = json.loads((assets / "SOURCE_PROTOCOL.json").read_text())
    if (sha(Path(__file__)) != source["execution_source_sha256"]
            or sha(package / "tail_calibration.py") != source["tail_source_sha256"]):
        raise ValueError("Calibration executor/tail semantics changed after source reservation")
    if digest({k: v for k, v in source.items() if k != "protocol_sha256"}) != source["protocol_sha256"]:
        raise ValueError("Frozen fresh source protocol changed")
    source_events = json.loads((assets / "EVENTS.json").read_text())
    if (source_events["source_protocol_sha256"] != source["protocol_sha256"]
            or source_events["arrays_sha256"] != sha(assets / "EVENTS.npz")):
        raise ValueError("Prepared source pixels no longer match the prior source freeze")
    actor = TableActor.from_dict(json.loads((parent / "ACTOR.json").read_text()))
    profile = NduProfile.from_dict(json.loads((parent / "PROFILE.json").read_text()))
    protocol = json.loads((parent / "PROTOCOL.json").read_text())
    frozen = json.loads((parent / "FROZEN.json").read_text())
    policy_frozen = json.loads((parent / "POLICY_FROZEN.json").read_text())
    if (actor.digest != source["policy_sha256"] or actor.digest != policy_frozen["actor_sha256"]
            or profile.digest != source["profile_sha256"] or profile.digest != policy_frozen["profile_sha256"]
            or sha(parent / "ACTOR.json") != policy_frozen["actor_file_sha256"]
            or sha(parent / "PROTOCOL.json") != frozen["protocol_sha256"]
            or sha(checkpoint) != protocol["initial_checkpoint_sha256"]):
        raise ValueError("Policy/profile/checkpoint drifted after source calibration was reserved")
    code = [package.parent / name for name in frozen["sources"]]
    if {str(path.relative_to(package.parent)): sha(path) for path in code} != frozen["sources"]:
        raise ValueError("The exact trained host continuation implementation changed")
    owner = package.parent / "closure_v2_20261027/control/evidence/development-001"
    authority = protocol["continuation"]["authority"]
    if (sha(binary) != authority["binary_sha256"] or sha(owner / "MODEL.json") != authority["readout_sha256"]
            or sha(owner / "ENCODER_DOMAIN_PROOF.json") != authority["calibration_sha256"]):
        raise ValueError("Original native owner authority artifacts changed")
    events = source_events["events"]
    expected = tuple(row["source_id"] for row in source["selected"])
    if len(events) != len(expected) or tuple(row["source_id"] for row in events) != expected:
        raise ValueError("Every newly frozen source must appear exactly once, in frozen order")
    plan = CalibrationPlan(profile.digest, actor.digest, sha(assets / "SOURCE_PROTOCOL.json"),
                           expected, tuple(source["excluded_source_ids"]),
                           source["return_threshold"], source["alpha"], source["family_size"])
    if set(actor.training_source_ids).intersection(expected):
        raise ValueError("Actual actor-fitting sources entered calibration")
    # All thresholds and the selected policy were already pinned in the source
    # freeze before decoding any fresh media; this records their API form.
    save(output / "CALIBRATION_PLAN.json", {"plan": asdict(plan), "plan_sha256": plan.digest,
        "source_protocol_sha256": source["protocol_sha256"], "execution_source_sha256": sha(Path(__file__)),
        "tail_implementation_sha256": sha(package / "tail_calibration.py"),
        "selected_policy_fixed_before_new_source_pixels": True,
        "new_source_access_does_not_change_policy_or_thresholds": True})
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    loaded = torch.load(checkpoint, weights_only=True, map_location="cpu")
    if loaded["vocabulary"] != source["vocabulary"]:
        raise ValueError("Fresh source token mapping differs from actual deployed model")
    model = NaturalPortfolio(loaded["vocabulary"]).eval().requires_grad_(True)
    model.load_state_dict(loaded["model"])
    budget_args = {key: protocol["work_budget"][key] for key in WorkBudget.__dataclass_fields__}
    budget, prices = WorkBudget(**budget_args), Prices(**protocol["prices"])
    namespace = digest({"run": str(output.resolve()), "plan": plan.digest})[:16]
    rows = []
    for index, event in enumerate(events):
        episode_started_cpu = cpu_seconds()
        item = {"index": index, **event}
        seed = source["emission_seed_base"] + index
        case = f"{namespace}-fresh-calibration-{index:02d}"
        adapter = ExistingNaturalAdapter(model=model, checkpoint=checkpoint, assets=assets,
                                         item=item, seed=seed, fault=False)
        _, _, record = execute_episode(profile=profile, actor=actor, prepare=adapter.prepare, emit=adapter.emit,
                                        terminal_score=adapter.terminal_score, binary=binary,
                                        readout=owner / "MODEL.json", calibration=owner / "ENCODER_DOMAIN_PROOF.json",
                                        checkpoint=checkpoint, directory=output / case, case=case,
                                        implementation_paths=code, episode_started_cpu=episode_started_cpu,
                                        budget=budget, prices=prices, expires=7, media_budget=2)
        record.update(calibration_plan_sha256=plan.digest, emission_seed=seed,
                      source_event_sha256=digest(item), new_original_source=True)
        save(output / case / "EPISODE.json", record)
        rows.append(record)
        print(json.dumps({"source": event["source_id"], "selected": record["selected_action"],
                          "executed": record["executed_action"], "net_return": record["net_return"]}), flush=True)
    result = calibrate_actual(rows, profile, plan)
    result.update(actual_native_kernels=17 * len(rows), actual_emissions=sum(len(r["emissions"]) for r in rows),
                  all_selected_actions_match_actual_minimum=all(r["selected_action"] == min(
                      ("keep", "swap"), key=lambda a: r["decision"]["predicted_complete_moments"][a]) for r in rows),
                  actual_episode_CPU_seconds=sum(r["cpu_seconds"] for r in rows),
                  outside_episode_setup_reporting_cpu_seconds=cpu_seconds() - cpu_start - sum(r["cpu_seconds"] for r in rows),
                  actual_wall_seconds=time.perf_counter() - started,
                  new_natural_capability_qualification=False, policy_changed_after_calibration=False,
                  source_scope=source["task_scope"], participant_independence_proven=False)
    save(output / "RESULT.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "parent", "checkpoint", "binary", "output"):
        parser.add_argument("--" + name, required=True)
    run(**vars(parser.parse_args()))
