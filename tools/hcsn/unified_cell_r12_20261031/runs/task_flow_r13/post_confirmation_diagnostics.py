"""Descriptive audit of frozen outcomes; no selection, retuning or new holdout.

Run from the repository root. Sequence replays must match the already recorded
confirmation-data hash. These diagnostics cannot change the primary result.
"""
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from threadpoolctl import threadpool_limits

from tools.hcsn.unified_cell_r12_20261031.campaign import verify_freeze
from tools.hcsn.unified_cell_r12_20261031.cell import Cell
from tools.hcsn.unified_cell_r12_20261031.data import generate_sequences, TRAIN_INTERVALS, OOD_INTERVALS
from tools.hcsn.unified_cell_r12_20261031.estimators import restore_model
from tools.hcsn.unified_cell_r12_20261031.evaluate import generic_hmm
from tools.hcsn.unified_cell_r12_20261031.fit import array_hash, atomic_json


def run():
    started = time.process_time()
    folder = Path(__file__).resolve().parent
    frozen, identity = verify_freeze(folder)
    truth = Cell()
    result = {"status": "post-confirmation descriptive diagnostics only",
              "freeze_sha256": identity, "primary_outcomes_unchanged": True,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "domains": {}, "physical_identifiability": []}
    for seed in sorted(map(int, frozen["selection"])):
        fit = json.loads((folder / str(seed) / "hx_distribution.json").read_text())
        cell = restore_model(fit["selected_model"]).build_cell()
        jacobian = np.concatenate([cell.dQ.reshape(3, -1), cell.dprior], axis=1)
        result["physical_identifiability"].append({
            "seed": seed, "physical_parameters": cell.theta.tolist(), "boundary": cell.boundary,
            "Q_and_prior_derivative_singular_values": np.linalg.svd(jacobian, compute_uv=False).tolist(),
            "scope": "The content-flow likelihood identifies sigma and boundary combinations, not all three physical parameters separately.",
            "phase_coordinate_read_fee_mae": float(np.mean(np.abs(cell.read_cost - truth.read_cost)))})
    for domain, intervals in (("iid", TRAIN_INTERVALS), ("ood", OOD_INTERVALS)):
        per_seed = []
        for seed in sorted(map(int, frozen["selection"])):
            row = json.loads((folder / str(seed) / ("confirmation_" + domain + ".json")).read_text())
            b, d = row["arms"]["B"]["episodes"], row["arms"]["D"]["episodes"]
            fit = json.loads((folder / str(seed) / "hx_distribution.json").read_text())
            model = restore_model(fit["selected_model"])
            cell = model.build_cell()
            data = generate_sequences(truth, row["sequence_seed"], 192, intervals=intervals)
            if array_hash(data) != row["confirmation_data_hash"]:
                raise AssertionError("Replay does not match existing confirmation data")
            hx = model.forward(data["inputs"])
            hmm = generic_hmm(cell, data["inputs"])
            hx_bit, hmm_bit = hx[..., 1::2].sum(-1), hmm[..., 1::2].sum(-1)
            different = (hx_bit >= .5) != (hmm_bit >= .5)
            distance = np.maximum(abs(hx_bit - .5), abs(hmm_bit - .5))
            accuracy_delta = float(np.mean([x["correct"] - y["correct"] for x, y in zip(d, b)]))
            bonus_delta = float(np.mean([(x["reward"] - x["correct"]) - (y["reward"] - y["correct"]) for x, y in zip(d, b)]))
            fee_delta = float(np.mean([x["cost"] - y["cost"] for x, y in zip(d, b)]))
            utility_delta = float(np.mean([x["utility"] - y["utility"] for x, y in zip(d, b)]))
            per_seed.append({"seed": seed, "D_minus_B_utility": utility_delta,
                             "accuracy_delta": accuracy_delta, "equity_bonus_delta": bonus_delta,
                             "actual_task_cost_delta": fee_delta,
                             "decomposition_error": utility_delta - (accuracy_delta + bonus_delta - fee_delta),
                             "action_path_disagreements": sum(x["actions"] != y["actions"] for x, y in zip(d, b)),
                             "D_more_reads_episodes": sum(x["counts"]["READ"] > y["counts"]["READ"] for x, y in zip(d, b)),
                             "D_fewer_reads_episodes": sum(x["counts"]["READ"] < y["counts"]["READ"] for x, y in zip(d, b)),
                             "counts": {arm: {a: sum(x["counts"][a] for x in episodes) for a in ("READ", "WAIT", "RESET")} for arm, episodes in (("B", b), ("D", d))},
                             "hmm_tie_audit": {"max_posterior_difference": float(np.max(np.abs(hx - hmm))),
                                               "classification_disagreements": int(different.sum()),
                                               "max_distance_from_half_on_disagreement": float(distance[different].max()) if different.any() else 0.,
                                               "all_disagreements_within_1e_12": bool(np.all(distance[different] < 1e-12))}})
        result["domains"][domain] = per_seed
    verify_freeze(folder)
    result["cpu_seconds"] = time.process_time() - started
    atomic_json(folder / "POST_CONFIRMATION_DIAGNOSTICS.json", result)
    print(json.dumps({"record": "POST_CONFIRMATION_DIAGNOSTICS.json", "cpu_seconds": result["cpu_seconds"],
                      "tie_counts": {d: sum(r["hmm_tie_audit"]["classification_disagreements"] for r in rows) for d, rows in result["domains"].items()}}))


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        run()
