"""Read retained PLIF state and replay frozen ABC inputs; no loss/backward/step."""
import datetime
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import time

import torch

ROOT = Path("/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1")
SOURCE = ROOT / "source-v1/proposals/localization-v2"
FIT = ROOT / "validation-v3/snn_plif"
DATA = ROOT / "validation-v3/data"
OUTPUT = Path("/home/qian-qi/work/plif-readonly-audit-20261108-s1s2/a1")
OUTPUT.mkdir(parents=True, exist_ok=False)
started = time.perf_counter()
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")

result = json.loads((FIT / "result.json").read_text())
plan = json.loads((FIT / "plan.json").read_text())
assert digest(FIT / "result.json") == "f397dc8cc4e4a00ad6ab3709b10172e4d0d528d5a5a035989ccc9be44d74c73f"
assert digest(FIT / "initial.pt") == result["initialization_sha256"]
assert digest(FIT / "events.jsonl") == result["events_sha256"]
events = [json.loads(line) for line in (FIT / "events.jsonl").read_text().splitlines()]
checkpoint_event = [event for event in events if event["event"] == "epoch_checkpoint"][-1]
checkpoint_file = FIT / checkpoint_event["path"]
assert digest(checkpoint_file) == checkpoint_event["sha256"]
assert digest(DATA / "data-manifest.json") == result["data_manifest_sha256"]
for name, expected in plan["source"].items():
    assert digest(SOURCE / name) == expected, name
for name, expected in result["model"]["source_files_sha256"].items():
    assert digest(Path(name)) == expected, name
sys.path.insert(0, str(SOURCE))
from models import build_model
from spikingjelly.activation_based import neuron, surrogate

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
initial = torch.load(FIT / "initial.pt", map_location="cpu", weights_only=True)
checkpoint = torch.load(checkpoint_file, map_location="cpu", weights_only=True)
assert checkpoint["manifest_sha256"] == result["data_manifest_sha256"]
name_to_id = {}
for saved, declared in zip(checkpoint["optimizer"]["param_groups"], result["optimizer_groups"]):
    assert saved["lr"] == declared["lr"] and saved["weight_decay"] == declared["weight_decay"]
    for name, parameter_id in zip(declared["parameter_names"], saved["params"]):
        name_to_id[name] = parameter_id
moments = {}
for name, parameter_id in name_to_id.items():
    state = checkpoint["optimizer"]["state"][parameter_id]
    assert int(state["step"].item()) == 12
    moments[name] = state["exp_avg_sq"]
recurrent_zero = (moments["recurrent.weight"] == 0).all(dim=0)
head_zero = (moments["head.weight"] == 0).all(dim=0)
silent_candidates = torch.where(recurrent_zero & head_zero)[0]
column_audit = {
    "recurrent_zero_columns": torch.where(recurrent_zero)[0].tolist(),
    "head_zero_columns": torch.where(head_zero)[0].tolist(),
    "same_zero_columns": bool(torch.equal(recurrent_zero, head_zero)),
    "recurrent_zero_elements_outside_zero_columns": int((moments["recurrent.weight"][:, ~recurrent_zero] == 0).sum()),
    "head_zero_elements_outside_zero_columns": int((moments["head.weight"][:, ~head_zero] == 0).sum()),
    "zero_moment_scalars": {name: int((moment == 0).sum()) for name, moment in moments.items()},
    "all_first_moments_zero_where_second_zero": all(bool((checkpoint["optimizer"]["state"][name_to_id[name]]["exp_avg"][moment == 0] == 0).all()) for name, moment in moments.items()),
}
decay_factor = 1 - plan["arguments"]["learning_rate"] * plan["arguments"]["weight_decay"]
decay_rows = []
for name in ("recurrent.weight", "head.weight"):
    mask = moments[name] == 0
    decayed = initial[name].clone()
    for _ in range(12):
        decayed.mul_(decay_factor)
    actual = checkpoint["model"][name]
    decay_rows.append({"name": name, "zero_moment_elements": int(mask.sum()),
                       "exact_sequential_decay_match": bool(torch.equal(decayed[mask], actual[mask])),
                       "max_residual": float((decayed[mask] - actual[mask]).abs().max())})
main_ids = [event["episode"] for event in events if event["event"] == "update_started" and event.get("phase") == "main"]
assert len(main_ids) == 12 and len(set(main_ids)) == 12
manifest = json.loads((DATA / "data-manifest.json").read_text())
episodes = {}
input_files = {}
for entry in manifest["episodes"]:
    if entry["partition"] != "train":
        continue
    path = DATA / entry["path"]
    assert path.resolve().is_relative_to(DATA.resolve())
    assert digest(path) == entry["sha256"]
    raw = json.loads(path.read_text())
    assert raw["sequence"][0] in "ABC"
    assert len(raw["x"]) == entry["events"] == len(raw["dt"])
    episodes[entry["id"]] = (torch.tensor(raw["x"], dtype=torch.float64)[None],
                              torch.tensor(raw["dt"], dtype=torch.float64)[None])
    input_files[entry["path"]] = entry["sha256"]
assert set(main_ids).issubset(episodes)
model = build_model("snn_plif", width=82)
model.train()
captures = []
def hook(module, arguments, spikes):
    # Soft reset subtracts spike * threshold, so add it back for charged voltage.
    captures.append({"spikes": spikes.detach().clone(),
                     "charged_voltage": (module.v + spikes * module.v_threshold).detach().clone(),
                     "drive": arguments[0].detach().clone()})
handle = model.node.register_forward_hook(hook)
frozen_replays = {}
with torch.no_grad():
    for label, weights in (("initial", initial), ("epoch_1_after_12_updates", checkpoint["model"])):
        model.load_state_dict(weights, strict=True)
        per_episode = []
        for episode_id in main_ids + [name for name in episodes if name not in main_ids]:
            captures.clear()
            x, dt = episodes[episode_id]
            output = model(x, dt)
            assert output.shape == (1, x.shape[1], 11) and bool(torch.isfinite(output).all())
            spikes = torch.stack([value["spikes"] for value in captures])[:, 0]
            voltages = torch.stack([value["charged_voltage"] for value in captures])[:, 0]
            assert bool(((spikes == 0) | (spikes == 1)).all())
            counts = spikes.sum(dim=0).long()
            positions = torch.arange(1, spikes.shape[0] + 1)[:, None].expand_as(spikes)
            first = torch.where(spikes > 0, positions, x.shape[1] + 1).min(dim=0).values.long()
            first[counts == 0] = -1
            per_episode.append({"id": episode_id, "in_retained_main_updates": episode_id in main_ids,
                                "events": x.shape[1], "spike_count_per_neuron": counts.tolist(),
                                "first_spike_1based": first.tolist(),
                                "max_charged_voltage_per_neuron": voltages.max(dim=0).values.tolist()})
        aggregate = {}
        for group in ("retained_12_main_inputs", "remaining_33_ABC_windows", "all_45_ABC_windows"):
            selected = [row for row in per_episode if group == "all_45_ABC_windows" or row["in_retained_main_updates"] == (group == "retained_12_main_inputs")]
            counts = torch.tensor([row["spike_count_per_neuron"] for row in selected], dtype=torch.int64).sum(0)
            max_voltage = torch.tensor([row["max_charged_voltage_per_neuron"] for row in selected], dtype=torch.float64).max(0).values
            aggregate[group] = {"episodes": len(selected), "events": sum(row["events"] for row in selected),
                                "spikes_total": int(counts.sum()), "spike_count_per_neuron": counts.tolist(),
                                "never_spiked_neurons": torch.where(counts == 0)[0].tolist(),
                                "zero_moment_columns_that_spike": silent_candidates[counts[silent_candidates] > 0].tolist(),
                                "max_charged_voltage_in_zero_moment_columns": {str(index): float(max_voltage[index]) for index in silent_candidates.tolist()}}
        frozen_replays[label] = {"tau": float((1 / model.node.w.sigmoid()).item()),
                                "parameters_unchanged": all(torch.equal(value, model.state_dict()[name]) for name, value in weights.items()),
                                "aggregate": aggregate, "episodes": per_episode}
handle.remove()
assert all(value.grad is None for value in model.parameters())
upstream = []
for name, value in (("ParametricLIFNode.neuronal_charge", neuron.ParametricLIFNode.neuronal_charge),
                    ("BaseNode.neuronal_fire", neuron.BaseNode.neuronal_fire),
                    ("BaseNode.neuronal_reset", neuron.BaseNode.neuronal_reset),
                    ("ATan", surrogate.ATan)):
    upstream.append(name + "\n" + inspect.getsource(value))
(OUTPUT / "UPSTREAM_MECHANISM.txt").write_text("\n\n".join(upstream))
for name, expected in plan["source"].items():
    assert digest(SOURCE / name) == expected, name
for path, expected in input_files.items():
    assert digest(DATA / path) == expected
assert digest(checkpoint_file) == checkpoint_event["sha256"]
assert digest(FIT / "initial.pt") == result["initialization_sha256"]
main_diagnostics = [event for event in events if event["event"] == "optimizer_step_completed" and event.get("phase") == "main"]
report = {"schema": "hepta.plif.readonly-zero-moment-diagnostic.v1", "status": "completed",
          "recorded_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "host": "desktop", "native_source": str(SOURCE),
          "source_sha256": plan["source"], "fit_result_sha256": digest(FIT / "result.json"),
          "initial_sha256": digest(FIT / "initial.pt"), "checkpoint_sha256": digest(checkpoint_file),
          "events_sha256": digest(FIT / "events.jsonl"), "manifest_sha256": result["data_manifest_sha256"],
          "torch_version": torch.__version__, "new_training_runs": 0, "optimizer_steps": 0, "backward_calls": 0,
          "confirmation_access": False, "labels_used_for_replay": False,
          "column_audit": column_audit, "weight_decay_only_check": decay_rows,
          "main_episode_ids": main_ids, "historical_step_diagnostics": main_diagnostics,
          "frozen_replays": frozen_replays, "upstream_mechanism_sha256": digest(OUTPUT / "UPSTREAM_MECHANISM.txt"),
          "source_and_input_files_unchanged": True, "wall_seconds": time.perf_counter() - started,
          "scope": "Post-hoc frozen-state input replay, not a reconstruction of intervening training states or proof of historical per-neuron silence."}
save(OUTPUT / "RESULT.json", report)
print(json.dumps({"output": str(OUTPUT), "result_sha256": digest(OUTPUT / "RESULT.json"),
                  "column_audit": column_audit, "decay_only": decay_rows,
                  "frozen": {label: {group: {key: value for key, value in row.items() if key not in ("spike_count_per_neuron", "max_charged_voltage_in_zero_moment_columns")} for group, row in item["aggregate"].items()} for label, item in frozen_replays.items()},
                  "new_training_runs": 0, "optimizer_steps": 0, "backward_calls": 0,
                  "wall_seconds": report["wall_seconds"]}), flush=True)
