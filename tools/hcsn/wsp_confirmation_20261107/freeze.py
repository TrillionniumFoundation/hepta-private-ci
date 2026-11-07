"""Create a locally frozen next-stage protocol before candidates or new worlds."""
import argparse
import datetime
from pathlib import Path
import subprocess
import sys

from guard import ARMS, FITS, file_identity, model_identity


ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT.parent / "wsp_native_value_20261105/value_edit"
sys.path.insert(0, str(UPSTREAM))
from artifact_io import read, save, verify_manifest


def main(output):
    repo = ROOT.parents[2]
    inputs = read(UPSTREAM / "INPUT_MANIFEST.json")
    verify_manifest(UPSTREAM, inputs["files"])
    paths = list(ROOT.glob("*.py")) + [UPSTREAM / name for name in inputs["files"]]
    paths += list(UPSTREAM.glob("*.py")) + list((UPSTREAM / "execution_r1/run/worlds").glob("*.json.gz"))
    identities = {str(path.relative_to(repo)): file_identity(path) for path in sorted(set(paths))}
    models = {str(fit): model_identity(read(UPSTREAM / f"inputs/fit_{fit}_C.json.gz")) for fit in FITS}
    protocol = {
        "schema": "hepta-wsp-fresh-cohort-v1", "status": "FROZEN_BEFORE_CANDIDATES_AND_CONFIRMATION",
        "frozen_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "source_files": identities, "models": models, "fits": list(FITS), "arms": list(ARMS),
        "upstream_protocol_sha256": file_identity(UPSTREAM / "PROTOCOL_FROZEN.json")["sha256"],
        "fixed_external_objective": {name: file_identity(UPSTREAM / "vendor/frozen_joint" / name)
            for name in ("joint_task.py", "joint_law.py", "joint_protocol.json", "truth_transitions.npz")},
        "target": "one-step incumbent own-law advantages with the existing terminal anchor",
        "excluded_search": "full Bellman-order replication in the fixed 147-parameter class; no repeat fitting of certified infeasible targets",
        "missing_state_status": "not established; 85-to-48 compression alone does not prove an alias; no silent new model class",
        "state_caps": {"full_per_world": 20000, "markov_per_world": 20000, "training_rows_per_fit": 200000},
        "optimization": {"occupancy_mixture": .9, "alphas": [0., .25, .5, .75, 1.],
                         "agent_eigenvalue_fraction": .01, "short_training_steps": 32},
        "arm_contracts": {
            "C": "unchanged checkpoint with checked F64 execution",
            "L": "literal stored-head execution fidelity control; no known layout defect, no fabricated weight change",
            "E": "mechanical exact-quadratic terminal-anchored solution; five TRAIN own-utility doses",
            "R": "one seeded signed permutation of selected effective E delta, matching both L2 and Linf",
            "A": "Agent-proposed spectral restriction: retain unregularized H^TWH modes >=1% of each action maximum; exact quadratic solve in that subspace and original shared ball, same TRAIN dose path",
            "G": "matched PGD, identical loss, data, center, radius and five TRAIN doses",
            "EG": "selected E followed by 32 projected gradient steps on the same objective, zero optimizer state, same five doses",
            "J": "complete checkpoint-own-law Bellman program, including cold planning cost",
            "MYOPIC": "cheap checkpoint-own-law one-step lookahead followed by immediate best terminal action; not the old M/DQ checkpoint"},
        "agent_hypothesis": "Suppressing weakly supported feature modes may reduce continuation ranking distortion. This is a fixed falsifiable proposal informed by the exposed prior audit, not a blind autonomous circuit-discovery trial.",
        "optimizer_state": {"EG": "fresh stateless projected gradient; no inherited momentum, moments or parameter-wise age; center stays original C"},
        "confirmation": {"worlds_per_fit_domain": 32, "domains": ["iid", "ood"],
            "seed": "evaluator secrets.token_hex(32) only after all candidate hashes freeze",
            "collision": "abort complete cohort, no replacement or adaptive resampling",
            "candidate_selection_on_confirmation": False,
            "ledger": "local SQLite FULL synchronous; whole fixed cohort consumed before first score",
            "external_history_unknown": True, "independent_authority_verified": False,
            "statistical_unit": "paired means across five pre-existing fits; worlds do not create new fits"},
        "inference": {"primary": ["E-C iid", "E-C ood"], "alpha_family": .05,
            "minimum_lower_bound_gain": .005,
            "method": "Student t, df=4, two-sided Bonferroni for two primary contrasts; secondary arms descriptive"},
        "resources": {"cpu_seconds": 1200, "wall_seconds": 1800, "numeric_threads": 1,
            "verifier_cpu_seconds": 900, "verifier_wall_seconds": 1200,
            "rss_limit_bytes": 1073741824, "per_fit_per_arm_candidate_cpu_cap": 180,
            "shared_preparation": "physically executed once; report inclusive per-arm alternatives, never sum them as physical cost"},
        "quality": {"primary": "complete expected finite-task utility", "ood": "new schedules from the original OOD domain",
            "calibration": "own-policy visitation-weighted probability MSE, plus C-visitation common-state preservation",
            "retention_limit": "Belief/encoder/core protected; general non-task retained capabilities remain unmeasured",
            "latency": "per-world cold program preparation and policy CPU; evaluator CPU is separate",
            "failure": "all reserved denominators, timeouts, failed construction, verification and recovery retained"},
        "unmeasured_costs": ["agent_input_tokens", "agent_output_tokens", "agent_service_cpu", "energy_joules",
                             "unknown_prior_search", "production_publication_and_recovery"],
        "scope": "fresh finite-task confirmation only; no live Trader gain, new training fits, independent authority or complete-network-training comparison",
    }
    print(save(output, protocol))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
