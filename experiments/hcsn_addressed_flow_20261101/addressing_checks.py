"""Causal, differentiable addressing checks on development inputs only."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_four_stage_flow_20261031.synthetic_data import batch
from .addressed_models import AddressedModel, CORES


def run():
    torch.set_num_threads(1)
    cases = []

    def check(name, passed, **details):
        cases.append(dict(name=name, passed=bool(passed), **details))

    def close(name, actual, expected, atol=1e-5):
        difference = float((actual - expected).abs().max())
        check(name, bool(torch.isfinite(actual).all()) and difference <= atol,
              max_absolute_error=difference, tolerance=atol)

    source = batch("binding", 4, 901177, split="train")
    x, dt, observed = [torch.from_numpy(source[key]) for key in ("x", "dt", "observed")]
    for index, core in enumerate(CORES):
        torch.manual_seed(900101 + index)
        model = AddressedModel(core).eval()
        with torch.no_grad():
            original = model(x, dt, observed)
            future_x, future_dt = x.clone(), dt.clone()
            future_x[:, -3:] = torch.randn_like(future_x[:, -3:])
            future_dt[:, -3:] *= 7
            future = model(future_x, future_dt, observed)
            close(core + "/future_excluded", original[:, :-3], future[:, :-3])

            missing = observed.clone()
            missing[:, 5] = False
            masked = model(x, dt, missing)
            junk = x.clone()
            junk[:, 5] = 9 * torch.randn_like(junk[:, 5])
            changed = model(junk, dt, missing)
            close(core + "/missing_payload_not_retained", masked[:, 6:], changed[:, 6:])

            shifted = x.clone()
            shifted[1:] = torch.randn_like(shifted[1:])
            changed = model(shifted, dt, observed)
            close(core + "/batch_independence", original[:1], changed[:1])
            close(core + "/batch_one", original[:1], model(x[:1], dt[:1], observed[:1]))

            refined_x = torch.zeros(x.shape[0], 2 * x.shape[1], x.shape[2])
            refined_x[:, 1::2] = x
            refined_dt = dt.repeat_interleave(2, 1) / 2
            refined_observed = torch.zeros(refined_dt.shape, dtype=torch.bool)
            refined_observed[:, 1::2] = observed
            refined = model(refined_x, refined_dt, refined_observed)[:, 1::2]
            close(core + "/unobserved_resampling", original, refined)

            # A current write payload may not affect that token's readout.
            modified = x.clone()
            modified[:, 6, 4:12] = torch.roll(modified[:, 6, 4:12], 1, -1)
            current = model(modified, dt, observed)
            close(core + "/read_before_write", original[:, :7], current[:, :7])

            for invalid in (-1., float("nan"), float("inf")):
                invalid_dt = dt.clone()
                invalid_dt[0, 0] = invalid
                try:
                    model(x, invalid_dt, observed)
                    refused = False
                except ValueError:
                    refused = True
                check(core + "/invalid_duration_" + str(invalid), refused)

            model.normalize_occupancy = False
            unnormalized = model(x, dt, observed)
            check(core + "/normalization_sensitivity_available",
                  bool(torch.isfinite(unnormalized).all())
                  and float((original - unnormalized).abs().max()) > 1e-6)
            model.normalize_occupancy = True

        labels = torch.from_numpy(source["y"])
        logits = model(x, dt, observed)
        loss = F.cross_entropy(logits.flatten(0, 1), labels.flatten(), ignore_index=-100)
        loss.backward()
        for name in ("address_a", "address_b", "roles.weight", "value.weight", "read.2.weight", "physical"):
            gradient = dict(model.named_parameters())[name].grad
            norm = float(gradient.norm()) if gradient is not None else 0.
            check(core + "/gradient/" + name,
                  gradient is not None and bool(torch.isfinite(gradient).all()) and norm > 1e-12,
                  gradient_norm=norm)
    # Selectivity is trainable, not given by an oracle; the two role logits start
    # equal for real writes and distractors, and both receive distinct gradients.
    train = batch("selective", 8, 901178, split="train")
    torch.manual_seed(901102)
    model = AddressedModel("diagonal")
    inputs = [torch.from_numpy(train[key]) for key in ("x", "dt", "observed")]
    logits = model(*inputs)
    labels = torch.from_numpy(train["y"])
    loss = F.cross_entropy(logits.flatten(0, 1), labels.flatten(), ignore_index=-100)
    loss.backward()
    gradient = model.roles.weight.grad[0]
    check("learned_selectivity/role_gradients_distinct",
          float((gradient[0] - gradient[2]).abs()) > 1e-7,
          write_gradient=float(gradient[0]), distractor_gradient=float(gradient[2]))
    probability = logits.softmax(-1).detach().numpy()
    mask = train["y"] != -100
    check("no_installed_class_decoder/untrained_not_solved",
          float((probability.argmax(-1)[mask] == train["y"][mask]).mean()) < .5,
          development_accuracy=float((probability.argmax(-1)[mask] == train["y"][mask]).mean()))
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    files = (Path(__file__).resolve(), Path(__file__).with_name("addressed_models.py").resolve())
    source = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    cases = run()
    cases.append(dict(name="source_unchanged", passed=all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in source.items())))
    summary = dict(scope="Development semantic/gradient tests; no capability confirmation",
                   checks=len(cases), failures=sum(not case["passed"] for case in cases),
                   success=all(case["passed"] for case in cases),
                   wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu)
    for name, payload in (("CASES.json", cases), ("SUMMARY.json", summary), ("SOURCE.json", source)):
        (out / name).write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summary))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
