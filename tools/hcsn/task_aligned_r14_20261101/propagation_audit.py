"""Independent finite-CTMC checks of the four propagation requirements.

Uniformization supplies a Poisson-mixture reference without a matrix
exponential. First-event renewal quadrature independently reconstructs full
post-event propagation, including the remaining interval and later events.
No result here establishes the continuum accuracy of the eight active bins.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.linalg import expm
from scipy.stats import poisson

from ..unified_cell_r12_20261031.cell import Cell
from .task import TaskModel


def marked_uniformization(generator, event_edges, prior, duration):
    """Poisson sum for state law, first-event probability and event count.

    `event_edges` marks only real natural event transitions, not dummy jumps.
    Missing Poisson-tail mass is retained in the returned receipt; neither
    probability nor event count is normalized or clipped to a desired result.
    """
    rate = float(np.max(-np.diag(generator)))
    if duration == 0 or rate == 0:
        return dict(state=prior.copy(), first=0., count=0., poisson_mass=1., terms=1)
    transition = np.eye(len(prior)) + generator / rate
    marked = event_edges / rate
    killed = transition - marked
    upper = int(poisson.ppf(1 - 1e-14, rate * duration)) + 1
    weights = poisson.pmf(np.arange(upper + 1), rate * duration)
    state = prior.copy()
    survivor = prior.copy()
    count_mass = np.zeros_like(prior)
    absorbed = 0.
    mixture = np.zeros_like(prior)
    first, count = 0., 0.
    for weight in weights:
        mixture += weight * state
        first += weight * absorbed
        count += weight * count_mass.sum()
        count_mass = count_mass @ transition + state @ marked
        state = state @ transition
        absorbed += float(survivor @ marked.sum(1))
        survivor = survivor @ killed
    return dict(state=mixture, first=float(first), count=float(count),
                poisson_mass=float(weights.sum()), terms=len(weights))


def renewal_reconstruction(generator, event_edges, prior, duration, nodes):
    """First-event quadrature with a full generator over remaining time.

    Q=K+J gives p exp(Qt)=p exp(Kt)+integral p exp(Ks) J exp(Q(t-s)) ds.
    The returned wrong-endpoint model deliberately discards all remaining time;
    it still conserves mass, showing why conservation alone is insufficient.
    """
    killed = generator - event_edges
    abscissae, weights = np.polynomial.legendre.leggauss(nodes)
    survivor = prior @ expm(killed * duration)
    renewed, endpoint_only = survivor.copy(), survivor.copy()
    for coordinate, weight in zip(abscissae, weights):
        event_time = .5 * duration * (coordinate + 1)
        flux = prior @ expm(killed * event_time) @ event_edges
        scale = .5 * duration * weight
        renewed += scale * (flux @ expm(generator * (duration - event_time)))
        endpoint_only += scale * flux
    return renewed, endpoint_only


def run_audit():
    cell = Cell()
    generator = np.array(cell.Q, copy=True)
    event_edges = np.zeros_like(generator)
    for bit in (0, 1):
        event_edges[bit, 2 * cell.n_active + bit] = generator[bit, 2 * cell.n_active + bit]
    repeated = []
    for duration in (.4, 1.4, 8., 25.):
        reference = marked_uniformization(generator, event_edges, cell.prior, duration)
        repeated.append(dict(
            duration=duration, reference_count=reference["count"],
            implementation_count=float(cell.expected_events(cell.prior, duration)),
            reference_first_probability=reference["first"],
            implementation_first_probability=float(cell.first_event_probability(cell.prior, duration)),
            state_error=float(np.max(np.abs(reference["state"] - cell.predict(cell.prior, duration)))),
            poisson_mass=reference["poisson_mass"], poisson_terms=reference["terms"],
        ))

    # Same physical and bit marginals, opposite position/content correlation.
    positive, negative = np.zeros(20), np.zeros(20)
    positive[0], positive[15] = .5, .5
    negative[1], negative[14] = .5, .5
    killed_transition = expm((generator - event_edges) * 1.4)
    posterior_bits = []
    for prior in (positive, negative):
        survived = prior @ killed_transition
        posterior_bits.append(float(survived[1::2].sum() / survived.sum()))
    correlation = dict(
        phase_marginal_error=float(np.max(np.abs(positive.reshape(10, 2).sum(1)
                                                    - negative.reshape(10, 2).sum(1)))),
        bit_marginal_error=float(np.max(np.abs(positive.reshape(10, 2).sum(0)
                                                  - negative.reshape(10, 2).sum(0)))),
        survival_probability_difference=float((positive - negative) @ killed_transition @ np.ones(20)),
        bit_one_given_survival=posterior_bits,
        content_posterior_difference=abs(posterior_bits[0] - posterior_bits[1]),
    )

    known_bit = cell.prior.copy()
    known_bit[1::2] = 0.
    known_bit *= 2
    renewed, endpoint = renewal_reconstruction(generator, event_edges, known_bit, 8., 80)
    refined, _ = renewal_reconstruction(generator, event_edges, known_bit, 8., 112)
    direct = known_bit @ expm(generator * 8.)
    remaining = dict(duration=8., coarse_nodes=80, refined_nodes=112,
                     renewal_max_error=float(np.max(np.abs(renewed - direct))),
                     quadrature_refinement_max_error=float(np.max(np.abs(refined - renewed))),
                     wrong_endpoint_max_error=float(np.max(np.abs(endpoint - direct))),
                     correct_bit_one_probability=float(direct[1::2].sum()),
                     wrong_endpoint_bit_one_probability=float(endpoint[1::2].sum()),
                     wrong_endpoint_mass=float(endpoint.sum()))

    task = TaskModel(cell)
    task_events = np.kron(np.eye(2), event_edges)
    sensor_reference = marked_uniformization(task.Q, task_events, task.prior, 8.)
    physical_successor = sensor_reference["state"].reshape(2, 20).sum(0)
    repaired_reference = marked_uniformization(task.Q, task_events, task.prior @ task.R, 8.)
    sensor = dict(
        joint_vs_base_state_error=float(np.max(np.abs(physical_successor - cell.predict(cell.prior, 8.)))),
        joint_vs_base_count_error=abs(sensor_reference["count"] - repeated[2]["reference_count"]),
        repaired_vs_unrepaired_natural_count_error=abs(repaired_reference["count"] - sensor_reference["count"]),
        after_repair_full_vs_split_error=float(np.max(np.abs(
            task.prior @ task.R @ task.transition(1.9)
            - task.prior @ task.R @ task.transition(.7) @ task.transition(1.2)))),
    )
    semigroup_error = float(np.max(np.abs(cell.transition(1.9)
                                         - cell.transition(.7) @ cell.transition(1.2))))
    result = dict(schema="hcsn-r14-propagation-audit-v1",
                  scope="Fixed finite CTMC only; no new observation or action opportunity at the numerical split.",
                  repeated_events=repeated, position_content_correlation=correlation,
                  natural_reset_remaining_time=remaining, sensor_overlay=sensor,
                  unchanged_input_semigroup_max_error=semigroup_error)
    result["checks"] = dict(
        count_and_first_match_independent_poisson_reference=all(
            abs(row["reference_count"] - row["implementation_count"]) < 1e-10
            and abs(row["reference_first_probability"] - row["implementation_first_probability"]) < 1e-10
            and row["state_error"] < 1e-11 for row in repeated),
        multiple_events_not_clamped_to_one=repeated[-1]["reference_count"] > 4.,
        first_hit_is_not_event_count=repeated[2]["reference_count"] - repeated[2]["reference_first_probability"] > .5,
        same_marginals_different_surviving_content=correlation["content_posterior_difference"] > .5,
        remaining_time_renewal=remaining["renewal_max_error"] < 1e-10,
        independent_quadrature_converged=remaining["quadrature_refinement_max_error"] < 1e-10,
        endpoint_only_reset_is_detectably_wrong=remaining["wrong_endpoint_max_error"] > .05,
        no_spurious_segmentation_effect=semigroup_error < 1e-12,
        sensor_overlay_preserves_natural_dynamics=max(sensor.values()) < 1e-10,
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(run_audit(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
