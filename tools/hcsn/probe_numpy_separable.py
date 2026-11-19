"""External, frozen-source NumPy diagnostics for B space/time discretization.

Run from a repository root, or pass --repo-root. This never trains or changes
the model; it does not replace saved-checkpoint, full-budget, or CUDA evidence.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np


def probe(Population, PopulationConfig, bins, factor, drive=3., leak=3.,
          sigma=.15, recovery=.2, T=6.4):
    dt = .1/factor
    config = PopulationConfig(bins=bins, dt=dt, refractory=.3, leak=leak,
                              sigma=sigma, recovery_strength=recovery)
    model = Population(config)
    state, trace = model.initial_state(), 0.
    output, rates, errors, escapes = [], [], [], []
    for i in range(round(T/dt)):
        step = model.step(state, drive)
        state = step.state
        trace = math.exp(-dt/.5)*trace+(1-math.exp(-dt/.5))*float(step.rate)
        errors.append(abs(float(state.total_mass())-1))
        escapes.append(float(state.escaped))
        rates.append(float(step.rate))
        if (i+1) % factor == 0:
            output.append(trace)
    return dict(bins=bins, dt=dt, time_factor=factor, output=np.array(output),
                maximum_mass_error=max(errors), maximum_escape=max(escapes),
                mean_rate=np.mean(rates), tail_rate=np.mean(rates[len(rates)//2:]),
                integrated_absorption=float(np.sum(rates)*dt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    source = root/"qualification/hcsn/population.py"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    sys.path.insert(0, str(root))
    from qualification.hcsn.population import Population, PopulationConfig

    result = dict(scope="untrained constant-drive NumPy FP64 diagnostic; does not replace saved-weight or CUDA qualification",
                  source_sha256=source_hash,
                  diagnostic_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  records=[])
    started = time.perf_counter()
    for condition in [dict(drive=3., leak=3., recovery=.2),
                      dict(drive=3., leak=0., recovery=0.)]:
        original = None
        for bins, factor in [(32, 1), (64, 1), (128, 1), (32, 2), (32, 4),
                             (64, 2), (128, 4), (256, 8)]:
            row = probe(Population, PopulationConfig, bins, factor, **condition)
            output = row.pop("output")
            if original is None:
                original = output
            row.update(condition=condition,
                       hidden_trace_rms_change=float(np.sqrt(np.mean((output-original)**2))),
                       output=output.tolist())
            result["records"].append(row)
            print(json.dumps({key: value for key, value in row.items() if key != "output"}), flush=True)
    result["elapsed_seconds"] = time.perf_counter()-started
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("population source changed during the diagnostic")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
