"""Post-confirmation statewise diagnosis; no fitting or new efficacy trial.

Evaluate the unchanged heads against independent known-model finite optima on
the three originally declared parameter shifts. Weight action mistakes by the
actual new-policy states in the frozen confirmation, retaining ordinary arms.
"""

from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import time

import numpy as np

from .. import finite
from ..frozen import FrozenR7
from ..head import CalibratedHead
from ..run import checkpoint, digest, source_manifest, write


def main():
    started, cpu = time.perf_counter(), time.process_time()
    evidence = Path(__file__).resolve().parents[1] / "evidence"
    prepared = evidence / "prepared02"
    frozen = json.loads((prepared / "FREEZE.json").read_text())
    if frozen["source"] != source_manifest():
        raise ValueError("source changed after freeze")
    preparation = json.loads((prepared / "PREPARE.json").read_text())
    counts = defaultdict(Counter)
    with gzip.open(evidence / "confirmation01/RAW.jsonl.gz", "rt") as stream:
        for line in stream:
            raw = json.loads(line)
            if raw["regime"] == "nominal":
                continue
            key = raw["mode"], raw["seed"], raw["regime"]
            for row in raw["runs"]["new"]["steps"]:
                state = finite.canonical(finite.task.State.from_dict(row["state"]))
                counts[key][state, row["latent_after"]] += 1
    rows = []
    for regime in ("drift", "missing", "cost_shift"):
        graph = finite.build_graph(finite.configurations(regime))
        independent = finite.build_graph(finite.configurations(regime), independent=True)
        alignment = np.asarray([independent["ids"][s] for s in graph["states"]])
        for fit in preparation["fits"]:
            mode, seed = fit["mode"], fit["seed"]
            model = FrozenR7(checkpoint(mode, seed))
            head = CalibratedHead.load(prepared / fit["head_file"])
            matrix, events = model.kernels(graph["x"])
            target, optimal = finite.targets(graph, matrix, events)
            q = head.predict(model.inputs(graph["x"]), target[:, :, 3])
            legal = graph["legal"][:, None]
            actions = np.where(legal, q, -np.inf).argmax(-1)
            old_actions = np.where(legal, model.old_q(graph["x"]), -np.inf).argmax(-1)
            _, values = finite.targets(graph, matrix, events, actions)
            _, old_values = finite.targets(graph, matrix, events, old_actions)
            imatrix, ievents = model.kernels(independent["x"])
            independent_optimal = finite.reference(independent, imatrix, ievents)[alignment]
            iactions = np.empty_like(actions)
            iactions[alignment] = actions
            independent_policy = finite.reference(independent, imatrix, ievents, iactions)[alignment]
            error = max(float(np.max(abs(independent_optimal - optimal))),
                float(np.max(abs(independent_policy - values))))
            if error > 1e-10:
                raise AssertionError((regime, mode, seed, error))
            examples = []
            total, regret_sum, mistakes, anchored_error = 0, 0., 0, 0.
            for (state, z), count in counts[mode, seed, regime].items():
                i = graph["ids"][state]
                actual, best = int(actions[i, z]), int(target[i, z].argmax())
                regret = float(target[i, z, best] - target[i, z, actual])
                total += count
                regret_sum += count * regret
                mistakes += count * int(regret > 1e-12)
                anchored_error = max(anchored_error, abs(float(q[i, z, 3] - target[i, z, 3])))
                if regret > 1e-12:
                    examples.append({"visits": count, "local_action_regret": regret,
                        "weighted_regret": count * regret, "state": state.to_dict(),
                        "latent_after": z, "selected": finite.ACTIONS[actual],
                        "optimal": finite.ACTIONS[best],
                        "legal_fitted_q": {a: float(q[i, z, j]) for j, a in enumerate(finite.ACTIONS) if graph["legal"][i, j]},
                        "legal_oracle_q": {a: float(target[i, z, j]) for j, a in enumerate(finite.ACTIONS) if graph["legal"][i, j]}})
            examples.sort(key=lambda x: x["weighted_regret"], reverse=True)
            start = graph["starts"]
            initial = model.n // 2
            rows.append({"mode": mode, "seed": seed, "regime": regime,
                "public_states": len(graph["states"]), "confirmed_new_decisions": total,
                "visited_action_mistake_fraction": mistakes / total,
                "visited_mean_local_regret": regret_sum / total,
                "stop_anchor_max_error": anchored_error,
                "independent_optimum_and_policy_max_error": error,
                "old_exact_return": float(old_values[start, initial].mean()),
                "new_exact_return": float(values[start, initial].mean()),
                "optimal_exact_return": float(optimal[start, initial].mean()),
                "new_minus_old_exact_return": float((values[start, initial] - old_values[start, initial]).mean()),
                "top_five_visited_mistakes": examples[:5]})
    groups = []
    for regime in ("drift", "missing", "cost_shift"):
        for mode in ("first_passage", "clocked", "direct"):
            selected = [r for r in rows if r["regime"] == regime and r["mode"] == mode]
            fields = ("visited_mean_local_regret", "visited_action_mistake_fraction", "old_exact_return",
                "new_exact_return", "optimal_exact_return", "new_minus_old_exact_return")
            groups.append({"regime": regime, "mode": mode,
                **{key: float(np.mean([r[key] for r in selected])) for key in fields}})
    report = {"schema": "hepta.round8.value-shift-posthoc-diagnostic.v1", "passed": True,
        "scope": "Posthoc diagnosis of previously reported shifts; not a new preregistered efficacy test. Finite known-model Q, not a continuum QVI.",
        "training_or_selection_performed": False, "production_activation": False,
        "source_frozen": True, "freeze_sha256": digest(prepared / "FREEZE.json"),
        "raw_confirmation_sha256": digest(evidence / "confirmation01/RAW.jsonl.gz"),
        "diagnostic_source_sha256": digest(Path(__file__)),
        "groups": groups, "fits": rows,
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - started,
        "diagnostic_interpretation": "STOP is anchored exactly; remaining mistakes are fitted continuation-action values on parameters outside the training support. No missing private observation is added by this audit."}
    write(evidence / "RECOVERY_SHIFT_DIAGNOSTIC_20261031.json", report)
    print(json.dumps(groups, indent=2), flush=True)


if __name__ == "__main__":
    main()
