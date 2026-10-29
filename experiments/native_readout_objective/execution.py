"""Original native sparse/NDU action execution with a distinct study identity."""

from experiments.continuous_boundary_policy.execution import (
    run_context as policy_context,
)

from .common import ALL_ARMS


def run_context(
    context, *, seed, phase, paths, arm, checkpoint_sha256, checkpoint=None, bridge=None
):
    if arm not in ALL_ARMS:
        raise ValueError("Unknown native-readout study arm")
    native = arm != "finite_grid_dp"
    if native and (checkpoint is None or bridge is None):
        raise ValueError("Learned readouts require original native execution")
    result = policy_context(
        context,
        seed=seed,
        phase=phase,
        paths=paths,
        arm="native_sparse" if native else "dp",
        checkpoint_sha256=checkpoint_sha256,
        checkpoint=checkpoint,
        bridge=bridge,
        retain=True,
    )
    for record in result["records"]:
        record["schema"] = "hepta.native-readout-objective.episode.v1"
        record["arm"] = arm
    expected = sum(len(r["steps"]) for r in result["records"]) if native else 0
    if (
        result["counts"]["actual_kernel_calls"] != expected
        or result["counts"]["actual_ndu_calls"] != expected
        or result["counts"]["semantic_message_bytes"] != 160 * expected
    ):
        raise ValueError("Original native execution/input budget contract changed")
    return result
