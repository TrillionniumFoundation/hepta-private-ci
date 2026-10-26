"""Freeze one selection-chosen rich paired policy per existing generator seed."""

import argparse
import json
from pathlib import Path
import time

from ...abc_recovery.base_recovery import file_sha, write_json
from ...closure_20261025.control.registry import asset_pins


HERE = Path(__file__).resolve().parent


def freeze(asset, development, allocation, cache, output):
    fitted = json.loads((development / "result.json").read_text())
    if fitted["status"] != "completed" or fitted["fresh_source_outcomes_used"]:
        raise ValueError("A complete historical-only bounded fit must precede registration")
    for path, digest in fitted["source_sha256"].items():
        if file_sha(Path(path)) != digest: raise ValueError("Candidate fitting code changed")
    base = HERE.parents[1]
    files = list(HERE.glob("*.py")) + list((HERE.parent / "control").glob("*.py"))
    for group in ("abc_recovery", "abc_next", "abc_followup/control", "v6", "v7", "closure_20261025/control"):
        files.extend((base / group).glob("*.py"))
    files.extend([HERE.parent / "sources.py", HERE.parent / "xnist_sources.py", HERE.parent / "action_sources.py", allocation, development / "result.json"])
    pins = {str(p.resolve()): file_sha(p) for p in sorted(set(files))}
    pins.update(asset_pins(asset))
    candidates = []
    for row in fitted["records"]:
        selected = row["candidates"][row["selected_index"]]
        path = Path(selected["checkpoint"])
        if file_sha(path) != selected["checkpoint_sha256"]: raise ValueError("Selected checkpoint changed")
        pins[str(path.resolve())] = file_sha(path)
        candidates.append({"seed": row["seed"], "width": selected["width"], "checkpoint": str(path.resolve()),
            "checkpoint_sha256": file_sha(path), "development_admitted": row["development_admitted"]})
    if [c["seed"] for c in candidates] != [17, 29, 43]: raise ValueError("Incomplete fixed seed panel")
    sources = json.loads(allocation.read_text())
    if sources["pair_count"] != 512 or sources["writer_count"] != 256: raise ValueError("Independent writer allocation differs")
    result = {"schema": "hepta.next.rich-action-value-protocol.v1", "study": "action_value",
        "registered_unix_ns": time.time_ns(), "frozen_candidate_sha256": pins,
        "source_allocation_sha256": file_sha(allocation), "fresh_source_outcomes_opened": False,
        "source": {"cache": str(cache.resolve()), "allocation": str(allocation.resolve()), "pairs": 512,
                   "role": "next_action_value", "loader": "experiments.multimodal_output_portfolio.next_20261025.action_sources"},
        "candidates": candidates, "draws": 2, "policies": ["cached_teacher", "rich_paired"],
        "evaluation": {"initial_namespace": "next-rich-value-initial-v1", "future_namespace": "next-rich-value-future-v1",
            "observation_namespace": "next-rich-value-observation-v1", "order_seed": 202610251801},
        "inference": {"gamma": 2., "action_cost": .002, "bootstrap_seed": 202610251802,
            "replicates": 4000, "level": .975, "prices": [0., .001, .002, .005],
            "unit": "256 writers; both source pairs, all views/draws and the fixed three-seed panel remain together",
            "replacement_family": {"raw_CE_lower_at_least": -.005, "exact_success_lower_at_least": -.005, "actual_request_wall_upper_below": 0.},
            "action_value_family": {"same_state_feasible_action_MSE_minus_zero_upper_below": 0.,
                "selected_nonstop_actual_action_minus_stop_moment_upper_below": 0.},
            "teacher_MSE_comparison": "secondary same-state predictor comparison, not a new gate selected after observations",
            "calibration": "Report both all-selected and nonstop-only, by action and fixed predicted bins; prediction-error intervals do not certify uniform conditional calibration",
            "regret": "Finite H1 realized alternative oracle after choice, private diagnostic only, not deployable or global conditional regret",
            "failure_rule": "Any incomplete request or diagnostic census blocks quality inference; no failed/outlier timings removed",
            "cost_scope": "Primary request includes actual generation, public features, selected head, durable decision, terminal persistence/readback, both policies' root-media packing and candidate-only H1 public-vector clone. Counterfactuals, root diagnostic archive fsync, private scoring and resident load are measured separately within exact whole-process receipt.",
            "no_additional_candidate_search_or_sample_extension": True}}
    if output.exists(): raise FileExistsError("Do not overwrite a frozen prospective protocol")
    write_json(output, result)
    print(json.dumps({"protocol_sha256": file_sha(output), "candidates": candidates}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--asset-root", type=Path, required=True); p.add_argument("--development", type=Path, required=True)
    p.add_argument("--allocation", type=Path, required=True); p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); freeze(a.asset_root, a.development, a.allocation, a.cache, a.output)
