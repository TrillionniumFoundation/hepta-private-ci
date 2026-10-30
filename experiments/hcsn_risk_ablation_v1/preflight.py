"""Training-split-only gradient, causal, streaming and budget preflight."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch
from torch.nn import functional as F

from experiments.hcsn_free_boundary_v1 import training
from .model import MODEL_NAMES, build_model


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent


def run(output, batch_size=32):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Preserve prior preflight evidence")
    torch.set_num_threads(1)
    started = time.process_time()
    protocol = json.loads((ROOT / "experiments/hcsn_distributional_v2/CONTENT002_PROTOCOL.json").read_bytes())
    records, access = [], []
    for task in ("selective_copy", "mqar"):
        data = protocol["data"][task]
        split = training.load_split(ROOT / data["path"], "train", access)
        x, dt, y = (split[key][:batch_size] for key in ("x", "dt", "y"))
        common_initial = None
        for arm in MODEL_NAMES:
            model = build_model(arm, x.shape[-1], int(split["y"].max()) + 1, seed=9470)
            initial = {name: value.detach().clone() for name, value in model.named_parameters()}
            if common_initial is None:
                common_initial = initial
            assert all(torch.equal(value, common_initial[name]) for name, value in initial.items()
                       if name in common_initial), "Common initialization differs between arms"
            optimizer = torch.optim.Adam(model.parameters(), lr=.001)
            elapsed, max_correction, max_mass_error, maximum_risk = [], 0.0, 0.0, None
            for update in range(3):
                start = time.process_time()
                optimizer.zero_grad(set_to_none=True)
                logits, aux = model(x, dt, return_sequence=True)
                loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
                loss.backward()
                gradients = training._gradient_summary(model)
                assert all(row["finite"] and row["missing_elements"] == 0 for row in gradients.values())
                torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
                optimizer.step()
                elapsed.append(time.process_time() - start)
                max_correction = max(max_correction, float(aux["projection_actual_l1_correction"].detach().max()))
                max_mass_error = max(max_mass_error, float((aux["flow_mass"].detach() - 1).abs().max()))
                if "first_event_probability" in aux:
                    risk = aux["first_event_probability"].detach()
                    assert bool(torch.isfinite(risk).all()) and float(risk.min()) >= -1e-9
                    assert float(risk.max()) <= 1 + 2e-6
                    maximum_risk = float(risk.max())
            changed = {name: bool((value.detach() != initial[name]).any())
                       for name, value in model.named_parameters()}
            physical = {name: value for name, value in changed.items() if
                        any(key in name for key in ("mu_bias", "raw_sigma", "raw_rho", "raw_K",
                                                    "raw_reset", "raw_refractory", "raw_boundary"))}
            assert all(physical.values()), "An expected physical parameter did not train"
            records.append(dict(task=task, arm=arm, batch=batch_size, updates=3, counts=model.counts(),
                physical_parameter_changes=physical, last_gradients=gradients,
                training_loss=float(loss.detach()), update_cpu_seconds=elapsed,
                max_projection_l1=max_correction, max_probability_mass_error=max_mass_error,
                max_first_event_probability=maximum_risk, dataset_sha256=data["sha256"]))

    model = build_model("risk_margin_j_risk", 3, 4, width=8, seed=9471).eval()
    generator = torch.Generator().manual_seed(9472)
    x = torch.randn(2, 7, 3, generator=generator)
    dt = torch.tensor([[0, .5, 4, 2, .2, 7, 1], [1, 3, .1, 0, 4, 1, 5.]])
    with torch.no_grad():
        expected, aux = model(x, dt, return_sequence=True)
        changed_x, changed_dt = x.clone(), dt.clone()
        changed_x[:, 4:] += 19
        changed_dt[:, 4:] *= 7
        future = model(changed_x, changed_dt, return_sequence=True, return_aux=False)
        causal_error = float((expected[:, :4] - future[:, :4]).abs().max())
        state, steps = None, []
        for token in range(x.shape[1]):
            logits, state, _ = model.step(x[:, token], dt[:, token], state)
            steps.append(logits)
        streaming_error = float((expected - torch.stack(steps, 1)).abs().max())
        prefix, first = model(x[:, :3], dt[:, :3], return_sequence=True)
        suffix, second = model(x[:, 3:], dt[:, 3:], state=first["state"], return_sequence=True)
        restored_error = float((expected - torch.cat((prefix, suffix), 1)).abs().max())
    assert causal_error <= 1e-6 and max(streaming_error, restored_error) <= 5e-5
    hashes = {str(path.relative_to(ROOT)): training._sha256(path)
              for path in sorted(PACKAGE.glob("*.py"))}
    stable = ROOT / "experiments/hcsn_distributional_v2/stable_probability.py"
    hashes[str(stable.relative_to(ROOT))] = training._sha256(stable)
    result = dict(schema="hcsn-risk-train-only-preflight.v1", passed=True, train_only=True,
        access_log=access, records=records, causal_prefix_max_error=causal_error,
        streaming_max_error=streaming_error, restored_state_max_error=restored_error,
        source_files_sha256=hashes, body_cpu_seconds=time.process_time() - started,
        scope="3 updates per arm/task are gradient and budget diagnostics, not a quality study")
    output.mkdir(parents=True, exist_ok=False)
    training._write_json(output / "RESULTS.json", result)
    print(json.dumps({key: result[key] for key in ("passed", "train_only", "body_cpu_seconds",
        "causal_prefix_max_error", "streaming_max_error", "restored_state_max_error")}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=32)
    arguments = parser.parse_args()
    run(arguments.output, arguments.batch_size)
