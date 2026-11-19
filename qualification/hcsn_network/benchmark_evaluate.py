"""One post-seal test evaluation and measured cost profile, with no optimizer."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from .benchmark_data import testing_data, training_data
from .benchmark_models import make_model
from .benchmark_train import evaluate, verify_sources
from .checkpoint import state_to_record
from .phase_approximation import PhaseState, phase_state_to_record


def main():
    parser = argparse.ArgumentParser()
    for name in ("seal", "fit", "data", "protocol", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(Path(args.protocol).read_text())
    verify_sources(protocol)
    seal = json.loads(Path(args.seal).read_text())
    expected_roster = {(a, s) for a in protocol["arms"] for s in protocol["seeds"]}
    if {(r["arm"], r["seed"]) for r in seal["fits"]} != expected_roster or len(seal["fits"]) != len(expected_roster):
        raise ValueError("all fixed model selections must be sealed before any test evaluation")
    seal_root = Path(args.seal).parent
    for entry in seal["fits"]:
        terminal_path = seal_root/"fit-processes"/entry["directory"]/"COST.json"
        if (entry.get("eligible_for_test") is not True or entry.get("terminal_exit_code") != 0
                or hashlib.sha256(terminal_path.read_bytes()).hexdigest() != entry["terminal_cost_sha256"]
                or json.loads(terminal_path.read_text())["exit_code"] != 0):
            raise ValueError("every roster fit must have a successful collected terminal before test access")
    if seal["protocol_sha256"] != hashlib.sha256(Path(args.protocol).read_bytes()).hexdigest():
        raise ValueError("protocol changed after selection seal")
    fit = Path(args.fit)
    matches = [r for r in seal["fits"] if r["directory"] == fit.name]
    if len(matches) != 1 or matches[0]["selected_sha256"] is None:
        raise ValueError("fit is absent, failed or unselected in seal")
    row = matches[0]
    for name, key in (("selected.pt", "selected_sha256"), ("RESULT.json", "result_sha256")):
        if hashlib.sha256((fit/name).read_bytes()).hexdigest() != row[key]:
            raise ValueError("selected checkpoint or result changed after seal")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    selected = torch.load(fit/"selected.pt", map_location="cpu", weights_only=True)
    model = make_model(row["arm"])
    model.load_state_dict(selected["model"], strict=True)
    # Training/validation replay verifies that the sealed selected model is the
    # one whose validation logits were recorded, before the first test read.
    tx, ty, vx, vy, _, _ = training_data(args.data)
    val_metrics, validation_logits = evaluate(model, vx, vy)
    recorded = np.load(fit/f"validation-{selected['validation_index']:03}.npz", allow_pickle=False)
    if (selected["validation_index"] != row["selected_validation_index"]
            or hashlib.sha256((fit/f"validation-{selected['validation_index']:03}.npz").read_bytes()).hexdigest()
            != row["selected_validation_sha256"]):
        raise ValueError("selected validation original changed after sealing")
    validation_max_difference = float(np.max(np.abs(validation_logits.numpy()-recorded["logits"])))
    if validation_max_difference > 1e-12:
        raise ValueError("sealed selected checkpoint fails its recorded validation replay")
    x, y = testing_data(args.data)
    start, cpu = time.perf_counter(), time.process_time()
    test_metrics, logits = evaluate(model, x, y)
    inference_wall, inference_cpu = time.perf_counter()-start, time.process_time()-cpu
    np.savez_compressed(out/"predictions.npz", logits=logits.numpy(), labels=y.numpy())
    # Actual B=64 retained-state probe, outside the training budget, before
    # the separately measured autograd-save probe. No optimizer is called.
    if hasattr(model, "capture_state"):
        model.capture_state = True
    with torch.no_grad():
        model(tx[:64])
    state_bytes = getattr(model, "last_state_bytes", None)
    physics_bytes = getattr(model, "last_physics_bytes", None)
    balance_error = getattr(model, "last_balance_error", None)
    serialized_state_bytes, serialized_state_sha256 = None, None
    if hasattr(model, "capture_state"):
        saved_state = (phase_state_to_record(model.last_state) if isinstance(model.last_state, PhaseState)
                       else state_to_record(model.last_state))
        torch.save(saved_state, out/"probe_state.pt")
        serialized_state_bytes = (out/"probe_state.pt").stat().st_size
        serialized_state_sha256 = hashlib.sha256((out/"probe_state.pt").read_bytes()).hexdigest()
        model.capture_state, model.last_state = False, None
    saved_bytes, saved_count = 0, 0
    def pack(tensor):
        nonlocal saved_bytes, saved_count
        saved_bytes += tensor.numel()*tensor.element_size()
        saved_count += 1
        return tensor.detach()
    model.train()
    model.zero_grad(set_to_none=True)
    profile_start, profile_cpu = time.perf_counter(), time.process_time()
    with torch.autograd.graph.saved_tensors_hooks(pack, lambda tensor: tensor):
        loss = torch.nn.functional.cross_entropy(model(tx[:64]), ty[:64])
        loss.backward()
    profile_wall, profile_cpu = time.perf_counter()-profile_start, time.process_time()-profile_cpu
    result = {"arm": row["arm"], "seed": row["seed"], "test": test_metrics,
              "test_examples": len(y), "validation": val_metrics,
              "validation_saved_logit_max_abs": validation_max_difference,
              "selected_checkpoint_sha256": row["selected_sha256"],
              "inference_wall_seconds": inference_wall, "inference_cpu_seconds": inference_cpu,
              "profile_batch": 64, "profile_forward_backward_wall_seconds": profile_wall,
              "profile_forward_backward_cpu_seconds": profile_cpu,
              "logical_forward_state_bytes": state_bytes, "physics_tensor_payload_bytes": physics_bytes,
              "serialized_full_forward_state_bytes": serialized_state_bytes,
              "serialized_full_forward_state_sha256": serialized_state_sha256,
              "cached_transition_view_payload_bytes": getattr(model, "last_operator_bytes", None),
              "full_content_balance_max_abs": balance_error,
              "autograd_saved_tensor_payload_bytes_with_repeats": saved_bytes,
              "autograd_saved_tensor_count_with_repeats": saved_count,
              "autograd_payload_is_not_peak_allocator_memory": True,
              "streaming_state_status": ("not_implemented_full_window_encoder" if row["arm"] == "transformer"
                                         else "actual_forward_state_payload"),
              "process_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "optimizer_calls": 0, "new_training": False, "energy_measurement": None}
    verify_sources(protocol)
    (out/"RESULT.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"arm": row["arm"], "seed": row["seed"], "test_accuracy": test_metrics["accuracy"]}), flush=True)


if __name__ == "__main__":
    main()
