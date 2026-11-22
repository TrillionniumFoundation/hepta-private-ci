"""Untrained paired physical-resolution mechanism runner, no quality selection.

The parent campaign owns source/namespace freezing, consumption and total costs.
fit_case only records the fixed process; final_case uses one fresh paired set.
The external labels are saved for provenance, not used to fit or certify HCSN.
"""

import time

import torch

from .clock_model import LAWS, WRITE_RATE, execute_sequence, make_clock_model
from .clock_tasks import TASKS, digest, generate_pair


def fit_case(task, seed, cfg):
    if task not in TASKS or seed not in cfg["seeds"]:
        raise ValueError("predeclared external task and seed required")
    model = make_clock_model()
    return {
        "task": task,
        "seed": seed,
        "namespace": cfg["namespace"],
        "count": cfg["final"],
        "segments": cfg["segments"],
        "refinement": cfg["refinement"],
        "write_rate": WRITE_RATE,
        "laws": list(LAWS),
        "learned_parameters": 0,
        "selection": "none; fixed process mechanism test, not a predictive quality comparison",
        "model_state": {
            name: value.detach().tolist() for name, value in model.state_dict().items()
        },
    }


def _execute(model, data, law):
    chunks = []
    width = min(32, 2048 // data["x"].shape[1])
    with torch.no_grad():
        for start in range(0, len(data["x"]), width):
            chunk = {name: value[start : start + width] for name, value in data.items()}
            chunks.append(execute_sequence(model, chunk, law))
    result = {
        name: torch.cat([chunk[name] for chunk in chunks])
        for name in (
            "density",
            "counts",
            "occupation_integral",
            "boundary",
            "time_micros",
        )
    }
    result["invariants"] = {
        name: (min if name == "min_probability" else max)(
            chunk["invariants"][name] for chunk in chunks
        )
        for name in ("max_mass_error", "max_content_excess", "min_probability")
    }
    return result


def final_case(record, task, seed, cfg):
    started = time.perf_counter()
    if record != fit_case(task, seed, cfg):
        raise ValueError("frozen mechanism identity/state changed")
    pair = generate_pair(
        cfg["namespace"],
        seed,
        task,
        "final",
        cfg["final"],
        cfg["segments"],
        cfg["refinement"],
    )
    model = make_clock_model()
    result = {
        "case": f"{task}/{seed}",
        "metadata": pair["metadata"],
        "results": [],
        "coarse_sha256": digest(pair["coarse"]),
        "refined_sha256": digest(pair["refined"]),
        "ids": pair["coarse"]["ids"].tolist(),
        "external_target": pair["coarse"]["y"][:, 0].tolist(),
        "physical_horizon": pair["coarse"]["dt"].sum(1).tolist(),
        "physical_writes": pair["coarse"]["write_mask"].sum(1).tolist(),
    }
    for law in LAWS:
        begin = time.perf_counter()
        a, b = (
            _execute(model, pair["coarse"], law),
            _execute(model, pair["refined"], law),
        )
        differences = {
            "probability_linf": (a["density"][:, 0] - b["density"][:, 0]).abs().amax(1),
            "content_linf": (a["density"][:, 1:] - b["density"][:, 1:])
            .abs()
            .amax((1, 2)),
            "marked_event_linf": (a["counts"] - b["counts"]).abs().amax(1),
            "population_event_abs": (a["counts"][:, 0] - b["counts"][:, 0]).abs(),
            "occupation_integral_abs": (
                a["occupation_integral"] - b["occupation_integral"]
            ).abs(),
        }
        maximum = max(float(value.max()) for value in differences.values())
        expected = law != "legacy_observation"
        result["results"].append(
            {
                "method": law,
                "status": "failed" if expected and maximum > 1e-9 else "success",
                "semigroup_expected": expected,
                "semigroup_tolerance": 1e-9,
                "semigroup_within_tolerance": maximum <= 1e-9,
                "sample_difference": {
                    name: value.tolist() for name, value in differences.items()
                },
                "mean_difference": {
                    name: float(value.mean()) for name, value in differences.items()
                },
                "max_difference": {
                    name: float(value.max()) for name, value in differences.items()
                },
                "coarse": {
                    name: value.tolist() if isinstance(value, torch.Tensor) else value
                    for name, value in a.items()
                },
                "refined": {
                    name: value.tolist() if isinstance(value, torch.Tensor) else value
                    for name, value in b.items()
                },
                "wall_before_serialization": time.perf_counter() - begin,
                "claim_scope": "same held finite process resolution; continuous write is a distinct candidate law",
            }
        )
    result["case_wall_before_serialization"] = time.perf_counter() - started
    return result
