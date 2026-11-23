"""Direct sparse readout repair for a one-hidden-layer tanh network.

Usage: python solver.py [directory]
The directory contains checkpoint .npz files with W1, b1, W2, b2, input,
and reference_logits. Only the provided probes and the damaged checkpoint
are used. Every returned checkpoint contains the four complete tensors.
"""
from argparse import ArgumentParser
from itertools import combinations
import json
from pathlib import Path

import numpy as np


PARAMETERS = ("W1", "b1", "W2", "b2")
TOL = 1e-10


def forward(model, inputs):
    hidden = np.tanh(inputs @ model["W1"].T + model["b1"])
    return hidden @ model["W2"].T + model["b2"]


def error_stats(errors):
    return {
        "max_abs": float(np.max(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
    }


def candidate_repairs(features, residual, num_setup, packed):
    """Enumerate supports of size 1 or 2, solving independent small linear systems."""
    candidates = []
    systems = 0
    for width in (1, 2):
        for columns in combinations(range(features.shape[1]), width):
            basis = features[:, columns]
            systems += 1
            delta, _, rank, _ = np.linalg.lstsq(
                basis[:num_setup], residual[:num_setup], rcond=None
            )
            if rank < width:
                continue
            delta[np.abs(delta) < TOL] = 0
            if np.any(np.all(delta == 0, axis=1)):
                continue  # This support has already been evaluated at a smaller width.
            error = basis @ delta - residual
            if np.max(np.abs(error)) > TOL:
                continue
            proposed = packed.copy()
            proposed[:, columns] += delta.T
            name = "sparse additive correction"
            if max(columns) < packed.shape[1] - 1:
                if width == 1 and np.max(np.abs(proposed[:, columns] + packed[:, columns])) < TOL:
                    proposed[:, columns] = -packed[:, columns]
                    name = "negate one outgoing hidden-unit column"
                if width == 2 and np.max(np.abs(proposed[:, columns] - packed[:, columns[::-1]])) < TOL:
                    proposed[:, columns] = packed[:, columns[::-1]]
                    name = "exchange two outgoing hidden-unit columns"
            candidates.append((np.count_nonzero(proposed != packed), columns, name, proposed))
    candidates.sort(key=lambda item: (item[0], len(item[1]), item[1]))
    return candidates, systems


def repair(original, inputs, reference):
    model = {name: values.copy() for name, values in original.items()}
    hidden = np.tanh(inputs @ model["W1"].T + model["b1"])
    initial = forward(model, inputs)
    residual = reference - initial
    setup = min(len(inputs), max(2, 3 * len(inputs) // 4))
    report = {
        "action": "KEEP",
        "setup_probes": setup,
        "verification_probes": len(inputs) - setup,
        "before": error_stats(residual),
        "rank_of_probe_residual_at_1e-10": int(np.linalg.matrix_rank(residual, tol=TOL)),
        "small_support_systems_tested": 0,
        "exact_sparse_supports_found": 0,
        "changed_coordinates": [],
        "identifiability": (
            "Finite probes allow other functions and off-probe effects. "
            "Historical parameter values and the original fault are not uniquely established."
        ),
    }
    if report["before"]["max_abs"] <= TOL:
        report["hypothesis"] = "Existing weights reproduce every trusted logit."
    else:
        basis = np.column_stack((hidden, np.ones(len(inputs))))
        packed = np.column_stack((model["W2"], model["b2"]))
        candidates, systems = candidate_repairs(basis, residual, setup, packed)
        report["small_support_systems_tested"] = systems
        report["exact_sparse_supports_found"] = len(candidates)
        if candidates:
            _, columns, hypothesis, proposal = candidates[0]
            model["W2"][:] = proposal[:, :-1]
            model["b2"][:] = proposal[:, -1]
            report.update(action="REPAIR", hypothesis=hypothesis, support_indices=list(columns))
            if hypothesis == "negate one outgoing hidden-unit column":
                report["equivalent_encoding"] = (
                    "Negating that input weight row and its bias gives exactly the same "
                    "map on all inputs, by oddness of tanh. The outgoing edit touches fewer scalars."
                )
            if hypothesis == "exchange two outgoing hidden-unit columns":
                report["equivalent_encoding"] = (
                    "Exchanging those input weight rows and their biases gives the same "
                    "map on all inputs. The outgoing exchange touches fewer scalars."
                )
        else:
            report["hypothesis"] = "No verified readout repair within the enumerated support family."
    for name in PARAMETERS:
        for coordinate in np.argwhere(model[name] != original[name]):
            index = tuple(coordinate)
            before = float(original[name][index])
            after = float(model[name][index])
            report["changed_coordinates"].append(
                dict(tensor=name, index=coordinate.tolist(), before=before, after=after, delta=after-before)
            )
    report["changed_scalar_count"] = len(report["changed_coordinates"])
    final_error = reference - forward(model, inputs)
    report["after"] = error_stats(final_error)
    if setup < len(inputs):
        report["verification_after"] = error_stats(final_error[setup:])
    if report["action"] == "REPAIR" and report["after"]["max_abs"] > TOL:
        raise ArithmeticError("Proposed edits failed forward verification.")
    return model, report


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    directory = parser.parse_args().directory
    output = directory / "output"
    output.mkdir(exist_ok=True)
    report = {
        "method": (
            "Compute trusted logit residuals. Enumerate one- and two-column supports "
            "in the hidden activation matrix augmented by a bias column. Solve each small "
            "linear system on the first three quarters of probes. Require agreement on all probes. "
            "Choose the exact candidate with the fewest changed scalar weights. Snap exact "
            "sign reversals and permutations to their native operations."
        ),
        "indexing": "Zero-based. W2 has shape (output, hidden).",
        "scope": (
            "Counts and minimality refer to enumerated readout edits, not every possible network "
            "parameterization. Verification probes are supplied examples and no private data was used."
        ),
        "threshold": TOL,
        "models": {},
    }
    for checkpoint in sorted(directory.glob("*.npz")):
        with np.load(checkpoint, allow_pickle=False) as data:
            original = {name: data[name] for name in PARAMETERS}
            model, result = repair(original, data["input"], data["reference_logits"])
        np.savez(output / checkpoint.name, **model)
        report["models"][checkpoint.name] = result
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
