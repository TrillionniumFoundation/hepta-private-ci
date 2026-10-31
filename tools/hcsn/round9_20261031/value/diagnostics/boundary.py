"""Fixed-action boundary intervention: does the current task reward firing?"""

import gzip
import json
from pathlib import Path
import time

import numpy as np
from scipy.linalg import expm_frechet
from scipy.special import expit

from tools.hcsn.round8_20261031.value_calibration import finite
from tools.hcsn.round8_20261031.value_calibration.frozen import FrozenR7
from tools.hcsn.round8_20261031.value_calibration.run import checkpoint, digest, episode_run, write
from ..protocol import SEEDS
from ..run import EVIDENCE, occupancy


HERE = Path(__file__).resolve().parent
CONFIRMATION = EVIDENCE / "confirmation02"


def perturb(model, raw):
    model.w["core.raw_boundary"] = np.asarray(raw)
    model.boundary = .35 + 1.65 * expit(raw)
    model.grid = model.boundary * model.w["core.normalised_grid"]
    model.basis[:, 0] = np.r_[model.grid, model.reset @ model.grid]
    model.basis[:, 1] = np.r_[model.grid ** 2, model.reset @ model.grid ** 2]


def derivatives(model, public):
    """Frechet derivative of the actual finite upwind/expm kernel, away from drift kinks."""
    matrices, events, dm, de = [], [], [], []
    b, n = model.boundary, model.n
    spacing = 2 * b / (n + 1)
    diffusion = .5 * model.sigma ** 2 / spacing ** 2
    z = expit(model.w["core.raw_boundary"])
    slope = 1.65 * z * (1 - z)
    for drive in model.encode(public)[1]:
        drift = drive - model.leak * model.grid
        plus = diffusion + np.maximum(drift, 0) / spacing
        minus = diffusion + np.maximum(-drift, 0) / spacing
        dp = -2 * diffusion / b - (drift > 0) * model.leak * model.w["core.normalised_grid"] / spacing - np.maximum(drift, 0) / (spacing * b)
        dn = -2 * diffusion / b + (drift < 0) * model.leak * model.w["core.normalised_grid"] / spacing - np.maximum(-drift, 0) / (spacing * b)
        generator = np.zeros((model.states, model.states)); tangent = generator.copy()
        generator[:n] = plus[:, None] * model.w["core.plus_generator_basis"] + minus[:, None] * model.w["core.minus_generator_basis"]
        tangent[:n] = slope * (dp[:, None] * model.w["core.plus_generator_basis"] + dn[:, None] * model.w["core.minus_generator_basis"])
        _, derivative = expm_frechet(generator, tangent)
        derivative[n:] = 0.
        matrix, event = model.transition(drive)
        matrices.append(matrix); events.append(event); dm.append(derivative)
        de.append(np.r_[derivative[:n, n:].sum(-1), 0., 0.])
    return tuple(np.asarray(a) for a in (matrices, events, dm, de))


def counts(graph, matrix, events, public_actions, dm=None, de=None):
    value, gradient = np.zeros(matrix.shape[:2]), np.zeros(matrix.shape[:2])
    for i in graph["order"]:
        edges = graph["edges"][i, public_actions[i]]
        after = sum(p * value[j] for p, j, _ in edges if j >= 0)
        value[i] = events[i] + matrix[i] @ np.broadcast_to(after, (matrix.shape[1],))
        if dm is not None:
            future = sum(p * gradient[j] for p, j, _ in edges if j >= 0)
            gradient[i] = de[i] + dm[i] @ np.broadcast_to(after, (matrix.shape[1],)) + matrix[i] @ np.broadcast_to(future, (matrix.shape[1],))
    return value, gradient


class FixedPublicPolicy:
    def __init__(self, public, target):
        self.table = {}
        for x, q in zip(public, target):
            if tuple(x) in self.table:
                np.testing.assert_allclose(self.table[tuple(x)], q, atol=1e-12)
            self.table[tuple(x)] = q

    def predict(self, joined, _stop):
        return self.table[tuple(joined[:18])]


def run():
    assert (CONFIRMATION / "RESULTS.json").exists(), "supplement follows immutable primary confirmation"
    protocol = {"schema": "hepta.r9.boundary-diagnostic.v1", "source_sha256": digest(__file__),
        "main_results_sha256": digest(CONFIRMATION / "RESULTS.json"), "mode": "first_passage", "seeds": list(SEEDS),
        "regime": "eight original nominal contracts", "raw_boundary_offsets": [-2., -1., 0., 1., 2., 5.],
        "gradient_centers": [0., 1.], "finite_difference_steps": [.02, .01, .005],
        "paired_execution": {"episodes_per_contract_fit": 128, "seed_start": 95100000, "offset": 1.},
        "policy": "one fixed public-state task+compute-cost optimal DP action, identical across latent states and interventions",
        "ordinary_control": "same public policy with identity latent transition and zero events; same task and per-decision fee",
        "gradients": "expm_frechet derivative of the 17-state CTMC; not a continuum QVI derivative",
        "claim_test": "quality/task costs/calls fixed; any utility change must equal minus event fee times event-count change",
        "not_a_primary_trial_or_trained_policy": True}
    with (HERE / "PROTOCOL.json").open("x") as stream:
        json.dump(protocol, stream, indent=2); stream.write("\n")
    cpu, wall = time.process_time(), time.perf_counter()
    graph = finite.build_graph(finite.configurations(), independent=True)
    ident = np.broadcast_to(np.eye(17), (len(graph["states"]), 17, 17))
    target, _ = finite.targets(graph, ident, np.zeros((len(graph["states"]), 17)))
    public_actions = target[:, 0].argmax(-1)
    actions = np.broadcast_to(public_actions[:, None], target.shape[:2])
    policy = FixedPublicPolicy(graph["x"], target[:, 0])
    no_cell = occupancy(graph, ident, np.zeros((len(graph["states"]), 17)), actions, target, 7)
    records, paired_summary = [], []
    with gzip.open(HERE / "PAIRED.jsonl.gz", "wt", compresslevel=6) as stream:
        for seed in SEEDS:
            model = FrozenR7(checkpoint("first_passage", seed)); original = float(model.w["core.raw_boundary"])
            interventions, gradients = [], []
            for offset in protocol["raw_boundary_offsets"]:
                perturb(model, original + offset)
                matrix, events = model.kernels(graph["x"])
                flow = occupancy(graph, matrix, events, actions, target, model.n // 2)
                event_values, _ = counts(graph, matrix, events, public_actions)
                assert abs(flow["events"] - event_values[graph["starts"], model.n // 2].mean()) < 1e-11
                interventions.append({"raw_offset": offset, "raw_boundary": original + offset,
                                      "boundary": float(model.boundary), **flow})
            for offset in protocol["gradient_centers"]:
                perturb(model, original + offset)
                matrix, events, dm, de = derivatives(model, graph["x"])
                _, gradient = counts(graph, matrix, events, public_actions, dm, de)
                analytic = float(gradient[graph["starts"], model.n // 2].mean())
                comparisons = []
                for h in protocol["finite_difference_steps"]:
                    means = []
                    for sign in (-1, 1):
                        perturb(model, original + offset + sign * h)
                        m, e = model.kernels(graph["x"])
                        v, _ = counts(graph, m, e, public_actions)
                        means.append(float(v[graph["starts"], model.n // 2].mean()))
                    fd = (means[1] - means[0]) / (2 * h)
                    comparisons.append({"step": h, "event_count_derivative": fd, "absolute_error": abs(fd - analytic)})
                gradients.append({"raw_offset": offset, "event_count_derivative": analytic,
                                  "net_utility_derivative": -finite.EVENT * analytic, "finite_difference": comparisons})
            deltas = []
            for c, config in enumerate(finite.configurations()):
                for n in range(protocol["paired_execution"]["episodes_per_contract_fit"]):
                    key = protocol["paired_execution"]["seed_start"] + (seed - 11) * 100000 + c * 1000 + n
                    episode = finite.task.generate_episode(key, config); pair = {}
                    for offset, name in ((0., "baseline"), (1., "raised_boundary"), (0., "ordinary_no_cell")):
                        model.mode = "direct" if name == "ordinary_no_cell" else "first_passage"
                        perturb(model, original + offset)
                        result = episode_run(model, policy, episode, key + 20000000)
                        pair[name] = {k: v for k, v in result.items() if k != "steps"}
                    before, after = pair["baseline"], pair["raised_boundary"]
                    assert before["correct"] == after["correct"] and before["decisions"] == after["decisions"]
                    assert before["task_return"] == after["task_return"]
                    ordinary = pair["ordinary_no_cell"]
                    assert ordinary["events"] == 0 and ordinary["decisions"] == before["decisions"]
                    assert ordinary["correct"] == before["correct"] and ordinary["task_return"] == before["task_return"]
                    delta = after["utility"] - before["utility"]
                    assert abs(delta + finite.EVENT * (after["events"] - before["events"])) < 1e-12
                    deltas.append(delta)
                    stream.write(json.dumps({"seed": seed, "contract": c, "episode_seed": key, "runs": pair}, separators=(",", ":")) + "\n")
            baseline = next(r for r in interventions if r["raw_offset"] == 0.)
            for row in interventions:
                for field in ("quality", "task_cost", "decisions"):
                    assert abs(row[field] - baseline[field]) < 1e-11
                assert abs(row["utility"] - baseline["utility"] + finite.EVENT * (row["events"] - baseline["events"])) < 1e-11
            records.append({"seed": seed, "interventions": interventions, "gradients": gradients})
            paired_summary.append({"seed": seed, "pairs": len(deltas), "mean_utility_delta": float(np.mean(deltas)),
                                   "quality_task_return_calls_identical": True})
    write(HERE / "RESULTS.json", {"protocol_sha256": digest(HERE / "PROTOCOL.json"), "records": records,
        "paired": paired_summary, "ordinary_no_cell": no_cell,
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall,
        "conclusion_scope": "Fixed public-optimal actions in this task; no statement about all learned policies or physical energy."})
    print(json.dumps({"records": records, "paired": paired_summary}), flush=True)


if __name__ == "__main__":
    run()
