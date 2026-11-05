"""Create a self-contained, fixed-input diagnostic package before execution."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path


def identity(path):
    data = Path(path).read_bytes()
    return dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--source-package", type=Path, required=True)
    args = args.parse_args()
    root = Path(__file__).resolve().parent
    source = args.source_package.resolve()
    if (root / "PROTOCOL_FROZEN.json").exists():
        raise FileExistsError("do not replace a frozen diagnostic")
    origin = {}
    source_paths = [f"inputs/fit_{fit}_{suffix}.json.gz" for fit in (11, 23, 37, 53, 71)
                    for suffix in ("C", "TRAIN_PUBLICS")]
    source_paths += ["vendor/frozen_joint/" + name for name in
                     ("legacy_task.py", "joint_task.py", "joint_deploy.py", "checked_replay.py")]
    for relative in source_paths:
        src, dst = source / relative, root / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("xb") as handle:
            handle.write(src.read_bytes())
        if identity(dst) != identity(src):
            raise ArithmeticError("input copy changed bytes")
        origin[relative] = dict(source_relative=relative, **identity(dst))
    sources = {name: identity(root / name) for name in
               ("ctmc_semantics.py", "run_diagnostic.py", "verify_diagnostic.py", "freeze_protocol.py", "measure_process.py")}
    protocol = dict(schema="hepta-wsp-event-semantics-diagnostic-v1",
        frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status="FROZEN_BEFORE_FIRST_NEW_DIAGNOSTIC_EXECUTION",
        purpose="Distinguish existing endpoint bank, first-hit/survival and endogenous reset semantics on actual frozen research checkpoints.",
        fits=[11, 23, 37, 53, 71], worlds_per_fit=64, horizons=[1, 2, 6],
        thresholds=[-.5, 0., .5], source_files=sources, input_files=origin,
        model_source_commit="5b69a046d886cf4c2a73c50e58197360ea15d8f5",
        base_training_commit="36e9ddd099e09688593bccf2c32d1dfabc39ac99",
        input_scope="All original 320 TRAIN public schedules and five unchanged research C checkpoints from the prior value_edit package; no holdout labels or new worlds.",
        actual_live_trader_checkpoint=False, new_training=False, candidate_weight_edit=False,
        first_hit_contract="tau_K=inf{t>=0: coordinate(X_t)>K}; initial mass above K counts at time0; strict endpoint event X_T>K has complement X_T<=K, including threshold equality.",
        outer_boundary_contract="First arrival to either of stored lower_ref/upper_ref states: two competing hit causes plus surviving interior mass; prior is interior.",
        reset_contract="A recovery jump from either reference boundary to interior is an endogenous reset; count all boundary entries and all such departures. REPAIR changes sensor broken/fees only.",
        reference_methods=["SciPy Pade expm of stored finite generator", "positive Poisson uniformization of same generator", "Van Loan jump-count block vs integrated uniformization"],
        matrix_tolerance=2e-10, propagation_tolerance=5e-10,
        semantic_difference_reporting_threshold=2e-8,
        poisson_tail_target=1e-15, largest_uniformization_mean=600, maximum_terms=4096,
        arithmetic="IEEE F64; residual/tail diagnostics are not outward-rounded mathematical certificates.",
        repair_counterfactual="For every TRAIN world: request first READ, advance WAIT if due2, force allowed failure, compare WAIT and REPAIR from resulting reachable broken state at equal next tick; same history and exogenous dynamics.",
        thresholds_not_retuned=True, no_effectiveness_endpoint=True, local_freeze_is_not_external_preregistration=True,
        costs="Whole child process includes imports/copies/checks/final writes where separately metered; nested phase times not added again. Agent/editor, historical training, power and production execution costs unknown.",
        budget=dict(cpu_seconds=120, wall_seconds=180, numeric_threads=1,
                    max_rss_bytes=1073741824, action_on_failure="preserve failure and stop; no reduced sample or changed tolerance rerun"),
        limits=["finite-space CTMC, not continuous-space diffusion proof", "conditioning is known supplied model, not unknown-world truth", "TRAIN diagnostic, not a fresh generalization experiment", "no new model repair or real trading benefit", "no independent Call/Put parameter pair in these checkpoints"])
    with (root / "PROTOCOL_FROZEN.json").open("x") as handle:
        json.dump(protocol, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(dict(protocol=identity(root / "PROTOCOL_FROZEN.json"), inputs=len(origin)), sort_keys=True))


if __name__ == "__main__":
    main()
