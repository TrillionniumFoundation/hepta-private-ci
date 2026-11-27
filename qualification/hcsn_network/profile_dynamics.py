"""Frozen-length complete-network state, gradient and approximation profile."""

import argparse
import io
import json
from pathlib import Path
import time

import numpy as np
import torch

from .benchmark_models import make_model
from .benchmark_train import verify_sources
from .checkpoint import state_to_record
from .phase_approximation import phase_state_to_record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["flow", "flow_erlang4"], required=True)
    parser.add_argument("--steps", type=int, choices=[10, 20, 40, 80], required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--protocol", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(Path(args.protocol).read_text())
    verify_sources(protocol)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(101)
    model = make_model(args.arm)
    model.capture_state = True
    generator = torch.Generator().manual_seed(123)
    inputs = torch.randn(1, 80, 2, generator=generator, dtype=torch.float64)[:, :args.steps]*.3
    inputs.requires_grad_()
    saved_bytes = 0
    def pack(tensor):
        nonlocal saved_bytes
        saved_bytes += tensor.numel()*tensor.element_size()
        return tensor.detach()
    started, cpu = time.perf_counter(), time.process_time()
    with torch.autograd.graph.saved_tensors_hooks(pack, lambda tensor: tensor):
        logits = model(inputs)
        forward_wall, forward_cpu = time.perf_counter()-started, time.process_time()-cpu
        state = model.last_state
        parameters = tuple(model.parameters())
        started, cpu = time.perf_counter(), time.process_time()
        gradients = torch.autograd.grad(logits.square().sum(), (*parameters, inputs))
        backward_wall, backward_cpu = time.perf_counter()-started, time.process_time()-cpu
    arrays = {"logits": logits.detach().numpy(), "input_gradient": gradients[-1].detach().numpy(),
              "parameter_gradient": torch.cat([g.flatten() for g in gradients[:-1]]).detach().numpy()}
    arrays.update({f"state_{i:03}": t.detach().numpy() for i,t in enumerate(state.tensors())})
    np.savez_compressed(out/"RAW.npz", **arrays)
    record = state_to_record(state) if args.arm == "flow" else phase_state_to_record(state)
    buffer = io.BytesIO()
    torch.save(record, buffer)
    (out/"state.pt").write_bytes(buffer.getvalue())
    if model.last_balance_error > 2e-9:
        raise ValueError("declared full-state conservation threshold failed")
    result = {"arm": args.arm, "steps": args.steps, "horizon": args.steps*.05,
              "batch": 1, "content_channels": 8, "layers": 2, "spatial_nodes": 4,
              "forward_and_conservation_wall_seconds": forward_wall,
              "forward_and_conservation_cpu_seconds": forward_cpu,
              "backward_wall_seconds": backward_wall, "backward_cpu_seconds": backward_cpu,
              "logical_state_bytes": state.tensor_bytes(), "serialized_state_bytes": len(buffer.getvalue()),
              "physics_tensor_bytes": model.last_physics_bytes,
              "transition_view_bytes": getattr(model, "last_operator_bytes", None),
              "autograd_saved_payload_bytes_with_repeats": saved_bytes,
              "balance_max_abs": model.last_balance_error,
              "exact_forward_exponentials": getattr(model, "last_forward_exponentials", None),
              "exact_forward_largest_dimension": getattr(model, "last_largest_dimension", None),
              "optimizer_calls": 0, "finite_complete_state_test": True,
              "sample_writes_do_not_define_arbitrary_dt_refinement": True}
    verify_sources(protocol)
    (out/"RESULT.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
