"""Same-weight full-model cost check; opt-in adapter, no default model edits."""

import argparse
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import time
from unittest.mock import patch

import torch
from torch.nn import functional as F

from experiments.hcsn_addressed_flow_20261101 import addressed_models, data, operator_fastpath


def run(out):
    torch.set_num_threads(1)
    out.mkdir(parents=True, exist_ok=False)
    sources = [Path(__file__), Path(addressed_models.__file__), Path(data.__file__),
               Path(operator_fastpath.__file__)]
    experiments = Path(addressed_models.__file__).parent.parent
    sources.extend([experiments / "hcsn_four_stage_flow_20261031" / name
                    for name in ("models.py", "marked_flow.py", "synthetic_data.py")])
    sources.append(experiments / "hcsn_distributional_v2/distribution_kernel.py")
    snapshot = out / "sources"
    snapshot.mkdir()
    hashes = {}
    for source in sources:
        hashes[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copyfile(source, snapshot / source.name)
    original = torch.matrix_exp
    backend_execution = dict(calls=0, matrices=0, methods={}, maximum_polynomial_degree=0)

    def bounded_exp(scaled_generator):
        # Only this process is patched. Restore dense matrix_exp inside the
        # optional backend so its declared dense fallback remains valid.
        with patch.object(torch, "matrix_exp", original):
            result = operator_fastpath.propagate(scaled_generator, 1.0)
        diagnostics = result["diagnostics"]
        backend_execution["calls"] += 1
        backend_execution["matrices"] += scaled_generator.numel() // scaled_generator.shape[-1] ** 2
        method = diagnostics["method"]
        backend_execution["methods"][method] = backend_execution["methods"].get(method, 0) + 1
        backend_execution["maximum_polynomial_degree"] = max(
            backend_execution["maximum_polynomial_degree"], diagnostics["degree"] or 0)
        return result["transition"]

    def backend(name):
        return patch.object(torch, "matrix_exp", bounded_exp) if name == "bounded" else contextlib.nullcontext()

    rows, checkpoint_hashes = [], {}
    for task in ("mqar", "binding"):
        for batch_size in (24, 64):
            torch.manual_seed(861113)
            model = addressed_models.AddressedModel("flow")
            checkpoint = Path(addressed_models.__file__).parent / "dev/addressing_train001" / (task + "_flow.pt")
            model.load_state_dict(torch.load(checkpoint, weights_only=True))
            checkpoint_hashes[str(checkpoint)] = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            batch = data.batch(task, batch_size, 861113, "dev")
            x, dt, seen = [torch.from_numpy(batch[k]) for k in ("x", "dt", "observed")]
            labels = torch.from_numpy(batch["y"])
            model_state = copy.deepcopy(model.state_dict())
            results, gradients = {}, {}
            for name in ("dense", "bounded"):
                model.load_state_dict(model_state)
                model.zero_grad(set_to_none=True)
                with backend(name):
                    output = model(x, dt, seen)
                    loss = F.cross_entropy(output.flatten(0, 1), labels.flatten())
                    loss.backward()
                results[name] = output.detach().clone()
                gradients[name] = {key: p.grad.detach().clone() for key, p in model.named_parameters() if p.grad is not None}
            output_error = float((results["dense"] - results["bounded"]).abs().max())
            gradient_error = max(float((gradients["dense"][key] - gradients["bounded"][key]).abs().max())
                                 for key in gradients["dense"])
            for backward in (False, True):
                samples = {"dense": [], "bounded": []}
                for iteration in range(13):
                    for name in (("dense", "bounded") if iteration % 2 else ("bounded", "dense")):
                        model.zero_grad(set_to_none=True)
                        started = time.perf_counter_ns()
                        with backend(name), torch.set_grad_enabled(backward):
                            output = model(x, dt, seen)
                            if backward:
                                F.cross_entropy(output.flatten(0, 1), labels.flatten()).backward()
                        elapsed = (time.perf_counter_ns() - started) / 1e9
                        if iteration >= 4:
                            samples[name].append(elapsed)
                medians = {key: statistics.median(value) for key, value in samples.items()}
                rows.append(dict(task=task, batch=batch_size, steps=x.shape[1], backward=backward,
                                 max_output_error=output_error, max_parameter_gradient_error=gradient_error,
                                 numerical_pass=output_error <= 1e-5 and gradient_error <= 1e-5,
                                 raw_seconds=samples, median_seconds=medians,
                                 dense_over_bounded=medians["dense"] / medians["bounded"]))
    unchanged = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    report = dict(scope="Development, same trained development weights, full model forward/backward; not full training or heldout quality",
                  torch=torch.__version__, threads=torch.get_num_threads(), warmups=4, repeats=9,
                  source_sha256=hashes, checkpoint_sha256=checkpoint_hashes,
                  sources_unchanged=unchanged, results=rows,
                  backend_execution=backend_execution,
                  passed=unchanged and all(r["numerical_pass"] for r in rows)
                  and backend_execution["methods"].get("poisson_scaling_squaring", 0) == backend_execution["calls"]
                  and backend_execution["calls"] > 0,
                  permanently_enabled_backend=False)
    (out / "SUMMARY.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "sources_unchanged": unchanged,
                      "backend_execution": backend_execution,
                      "rows": [{k: v for k, v in r.items() if k != "raw_seconds"} for r in rows]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args().out)
