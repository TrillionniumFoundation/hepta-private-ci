"""Source-bound finite diagnostics on every exposed original v2 law.

This executes no neural model, training or full DDE trajectory. The actual
graded generator and actual conservative migration weights supply the finite
kernels. Eight separately executed DDE fixtures are cross-checked as distinct
evidence. Meshes, laws and diagnostics were selected after previous failures.
"""

import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path
import platform
import sys
import time
import zipfile

import numpy as np
import scipy

# Bundled helpers are deliberately retained with their executing source bytes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from actual_candidate_kernels import ActualCandidateFiniteKernels
from audit_short_gap import continuum_basis
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_initial_law.migration import MigrationBasis
from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator


SUMMARY_SHA = "12fa561e6b5e6f710d1239d2a00bcf596da9d0060bf4691473ff337b7b5d0822"
PILOT_SHA = "c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715"
SOURCE_HEAD = "62f392a0ed953f2d04e9c62b4b243f5cceed2a98"
GAPS = (.001, .003, .02, .04, .08, .16)
METRICS = ("M_expected_events", "H_discounted_events", "R_refractory_probability",
           "A_discounted_active_occupation")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_checked(path, expected, identities):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"regular retained input required: {path}")
    raw = path.read_bytes()
    value = digest(raw)
    if expected is not None and value != expected:
        raise ValueError(f"input SHA mismatch: {path}")
    identities[str(path.resolve())] = value
    return raw


def source_paths():
    result = {
        "qualification/hcsn_graded/model.py": Path(inspect.getfile(GradedJointModel)),
        "qualification/hcsn_graded/spatial.py": Path(inspect.getfile(GradedSpatialGenerator)),
        "qualification/hcsn_initial_law/migration.py": Path(inspect.getfile(MigrationBasis)),
        "qualification/hcsn_joint_dde/model.py": Path(inspect.getfile(JointModel)),
        "qualification/hcsn_boundary_audit/refractory_transport.py": Path(inspect.getfile(Packet)),
        "qualification/hcsn_boundary_audit/spatial_generator.py": Path(inspect.getfile(KilledSpatialGenerator)),
    }
    graded = result["qualification/hcsn_graded/model.py"].parent
    result.update({"qualification/hcsn_graded/" + name: graded / name
                   for name in ("probe_migration.py", "reference.py")})
    for name in ("run.py", "actual_candidate_kernels.py", "audit_short_gap.py", "PINNED_SOURCE.json"):
        result["qualification/hcsn_finite_review/" + name] = Path(__file__).with_name(name)
    return result


def four_quantities(mha, t, delay=.2):
    """At T<=delay at most one hit; R=M+unreleased initial phase mass."""
    if not 0 <= t <= delay or mha.shape != (25, 3):
        raise ValueError("declared single-hit basis required")
    refractory = mha[:, 0].copy()
    phase_edges = np.linspace(0, delay, 9)
    for k, (left, right) in enumerate(zip(phase_edges[:-1], phase_edges[1:])):
        refractory[17+k] += max(0., right-max(t, left))/(right-left)
    return np.c_[mha[:, 0], mha[:, 1], refractory, mha[:, 2]]


def compare_sources_to_dde(dde, sources, format_witness):
    """Retain byte identity versus previously declared formatting equivalence."""
    relations = []
    for old_path, old_digest in dde["source_sha256_before"].items():
        logical = old_path[old_path.index("qualification/"):]
        current = sources[logical]
        if current == old_digest:
            relation = "same_bytes"
        else:
            match = [entry for name, entry in format_witness["files"].items()
                     if name.endswith(logical)]
            if (len(match) != 1 or not match[0]["ast_equal"]
                    or match[0]["tested_sha256"] != old_digest
                    or match[0]["formatted_sha256"] != current):
                raise ValueError("DDE source has no matching retained byte/format witness")
            relation = "retained_AST_equivalence_witness_not_same_bytes"
        relations.append({"logical_source": logical, "DDE_executing_sha256": old_digest,
                          "current_sha256": current, "relation": relation})
    if dde["source_sha256_before"] != dde["source_sha256_after"]:
        raise ValueError("DDE evidence changed executing source")
    return relations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--pilot-root", required=True, type=Path)
    parser.add_argument("--dde-evidence", required=True, type=Path)
    parser.add_argument("--format-witness", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    wall, cpu = time.perf_counter(), time.process_time()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    sources = source_paths()
    source_before = {name: digest(path.read_bytes()) for name, path in sources.items()}
    pin = json.loads(Path(__file__).with_name("PINNED_SOURCE.json").read_bytes())
    if pin["source_head"] != SOURCE_HEAD:
        raise ValueError("unexpected published candidate identity")
    for name, expected in pin["files"].items():
        if source_before[name] != expected["sha256"]:
            raise ValueError(f"published candidate bytes changed: {name}")
    with zipfile.ZipFile(args.output_dir / "SOURCE_SNAPSHOT.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sources.items():
            archive.writestr(name, path.read_bytes())
    identities = {}
    summary = json.loads(read_checked(args.input_root / "SUMMARY.json", SUMMARY_SHA, identities))
    pilot = json.loads(read_checked(args.pilot_root / "SUMMARY.json", PILOT_SHA, identities))
    read_checked(args.pilot_root / "DATA.json", pilot["data_sha256"], identities)
    read_checked(args.pilot_root / "PLAN.json", None, identities)
    roster = {(seed, arm) for seed in (11, 23, 37) for arm in ("c0_b0", "c0_b1", "c1_b0", "c1_b1")}
    if len(summary["arms"]) != 12 or {(a["seed"], a["arm"]) for a in summary["arms"]} != roster:
        raise ValueError("full original roster required")
    visits, arm_names, identifiers = [], [], []
    selected, largest_first = None, -1.
    for arm_index, arm in enumerate(summary["arms"]):
        arm_name = f"seed{arm['seed']}-{arm['arm']}"
        arm_names.append(arm_name)
        read_checked(args.pilot_root / arm_name / "training.jsonl",
                     arm["original_training_trace_sha256"], identities)
        raw = read_checked(args.input_root / arm["derived_trace_file"], arm["derived_trace_sha256"], identities)
        parsed = [json.loads(line) for line in raw.splitlines()]
        header, current, footer = parsed[0], parsed[1:-1], parsed[-1]
        audit = json.loads(read_checked(args.input_root / arm["raw_audit_file"], arm["raw_audit_sha256"], identities))
        if (header["kind"] != "header" or footer["kind"] != "end" or footer["truncated"]
                or footer["dropped_records"] != 0 or footer["retained_records"] != arm["expected_visits"]
                or len(current) != arm["expected_visits"] or len(audit["visits"]) != len(current)):
            raise ValueError("partial original coverage")
        for visit, old in zip(current, audit["visits"]):
            if (visit["index"] != old["index"] or visit["model_sha256"] != old["model_sha256"]
                    or visit["update_index"] != old["update_index"]):
                raise ValueError("original visit/old audit identity differs")
            if (visit["grid"] != pilot["configuration"]["grid"] or visit["dt"][0] not in GAPS
                    or len(visit["dt"]) != 1 or visit["operator"]["reset_enabled"] is not True):
                raise ValueError("original reconstruction/gap changed")
            for name in ("prior", "posterior"):
                law = np.asarray(visit[name], dtype=float)
                if law.shape != (1, 25) or not np.isfinite(law).all() or law.min() < 0 or abs(law.sum()-1) > 5e-11:
                    raise ValueError("unresolved original law")
            visits.append(visit)
            identifiers.append((arm_index, visit["index"], visit["update_index"], visit["position"],
                                visit["origin_line"], visit["episode_id"], visit["model_sha256"],
                                visit["origin_line_sha256"]))
            if visit["posterior"][0][0] > largest_first:
                selected, largest_first = visit, visit["posterior"][0][0]
    if len(visits) != 14336:
        raise ValueError("14336 original positions required")
    physics = {(v["parameters"]["mu"], v["parameters"]["sigma"], v["parameters"]["discount"]) for v in visits}
    if physics != {(-.11999999999999998, .35, .15)}:
        raise ValueError("independent continuum evaluator is pinned to original physical domain")
    params = selected["parameters"]
    selected_reset = math.log(params["absolute_reset"])-params["log_boundary"]
    kernels, models, lift_reports = {}, {}, {}
    for n in (256, 512):
        spatial = GradedSpatialGenerator(n, 8., params["mu"], params["sigma"])
        model = GradedJointModel(spatial, selected_reset, .2, params["discount"])
        basis = MigrationBasis(4.8, 16, 1., .2, 8, 8., n, actual_nodes=tuple(spatial.nodes))
        lift = basis.lift()
        kernels[n] = ActualCandidateFiniteKernels(model, lift.weights)
        models[n] = spatial
        lift_reports[n] = {"weight_sha256_float64": digest(kernels[n].weights.tobytes()),
                           "nodes_sha256_float64": digest(spatial.nodes.tobytes()),
                           "maximum_row_mass_error": float(np.max(abs(kernels[n].weights.sum(1)-1))),
                           "lower_mass": float(kernels[n].weights[:, 0].sum())}
    references, candidates = {}, {n: {} for n in kernels}
    quadrature_error, old_event_difference = np.zeros(4), 0.
    reference_rows = {law: [] for law in ("prior", "posterior")}
    candidate_rows = {(n, law): [] for n in kernels for law in reference_rows}
    extra_rows = {(n, law): [] for n in kernels for law in reference_rows}
    validated_resets, reset_identities = set(), []
    for visit in visits:
        t, p = visit["dt"][0], visit["parameters"]
        reset = math.log(p["absolute_reset"])-p["log_boundary"]
        key = (t, reset)
        if reset not in validated_resets:
            for n, spatial in models.items():
                actual_model = GradedJointModel(spatial, reset, .2, p["discount"])
                reset_law = actual_model.ingredients()[3]
                nodes = spatial.nodes
                j = min(int(np.searchsorted(nodes, reset, side="right"))-1, len(nodes)-2)
                expected = np.zeros(len(nodes)); weight = (reset-nodes[j])/(nodes[j+1]-nodes[j])
                expected[j], expected[j+1] = 1-weight, weight
                if not np.array_equal(reset_law, expected[1:-1]):
                    raise ValueError("actual candidate reset law differs")
                reset_identities.append({"intervals": n, "reset": reset,
                                         "actual_reset_weights_sha256": digest(reset_law.tobytes())})
            validated_resets.add(reset)
        if key not in references:
            ref_mha = continuum_basis(t, reset, order=128)
            ref64 = continuum_basis(t, reset, order=64)
            references[key] = four_quantities(ref_mha, t)
            quadrature_error = np.maximum(quadrature_error,
                np.max(abs(references[key]-four_quantities(ref64, t)), axis=0))
            for n, kernel in kernels.items():
                candidates[n][key] = four_quantities(kernel.basis(t, reset), t)
        for law in reference_rows:
            weights = np.asarray(visit[law])[0]
            ref = weights @ references[key]
            reference_rows[law].append(ref)
            baseline = weights.sum()*-math.expm1(-.15*t)/.15
            for n in kernels:
                actual = weights @ candidates[n][key]
                candidate_rows[n, law].append(actual)
                extra_rows[n, law].append((baseline-actual[3], baseline-ref[3]))
            if law == "prior":
                old_event_difference = max(old_event_difference, abs(ref[0]-visit["expected_events"][0]))
    files, reports = [], []
    for n in kernels:
        for law in reference_rows:
            actual, reference = np.asarray(candidate_rows[n, law]), np.asarray(reference_rows[law])
            arrays = {
                "candidate_M_H_R_A": actual, "continuum_M_H_R_A": reference,
                "discounted_refractory_occupation_candidate_reference": np.asarray(extra_rows[n, law]),
                "metrics": np.asarray(METRICS), "arm_names": np.asarray(arm_names),
                "arm_index": np.asarray([x[0] for x in identifiers], dtype=np.uint8),
                "visit_index": np.asarray([x[1] for x in identifiers], dtype=np.uint16),
                "update_index": np.asarray([x[2] for x in identifiers], dtype=np.uint16),
                "position": np.asarray([x[3] for x in identifiers], dtype=np.uint16),
                "origin_line": np.asarray([x[4] for x in identifiers], dtype=np.uint16),
                "episode_id": np.asarray([x[5] for x in identifiers]),
                "model_sha256": np.asarray([x[6] for x in identifiers], dtype="S64"),
                "origin_line_sha256": np.asarray([x[7] for x in identifiers], dtype="S64"),
                "dt": np.asarray([v["dt"][0] for v in visits]),
                "reset": np.asarray([math.log(v["parameters"]["absolute_reset"])-v["parameters"]["log_boundary"] for v in visits]),
            }
            path = args.output_dir / f"ALL_VISITS_n{n}_{law}.npz"
            np.savez_compressed(path, **arrays)
            if path.stat().st_size >= 2**20:
                raise ValueError("full-row archive exceeds requested 1MiB bound")
            with np.load(path, allow_pickle=False) as saved:
                for name, original in arrays.items():
                    if not np.array_equal(saved[name], original):
                        raise ValueError("retained array readback differs")
            files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": digest(path.read_bytes()), "rows": len(visits)})
            error = abs(actual-reference)
            relative = []
            for j in range(4):
                mask = reference[:, j] >= 1e-12
                relative.append(float(np.max(error[mask, j]/reference[mask, j])) if mask.any() else None)
            reports.append({"intervals": n, "law": law, "rows": len(visits),
                            "maximum_absolute_error_M_H_R_A": np.max(error, axis=0).tolist(),
                            "mean_absolute_error_M_H_R_A": np.mean(error, axis=0).tolist(),
                            "maximum_relative_error_where_reference_at_least_1e-12": relative})
    dde_summary = json.loads(read_checked(args.dde_evidence / "SUMMARY.json", None, identities))
    read_checked(args.dde_evidence / "RAW_ROLLOUTS.npz", dde_summary["raw_array_sha256"], identities)
    format_witness = json.loads(read_checked(args.format_witness, None, identities))
    relations = compare_sources_to_dde(dde_summary, source_before, format_witness)
    selection = dde_summary["selection"]
    if (selected["index"] != selection["visit_index"] or selected["position"] != selection["position"]
            or selected["update_index"] != selection["update_index"] or largest_first != selection["first_cell_mass"]):
        raise ValueError("actual DDE selected-law identity differs")
    law_cases = {"original_maximum_first_cell_posterior": np.asarray(selected["posterior"])[0]}
    for name, index in (("isolated_first_uniform", 0), ("isolated_first_phase", 17), ("isolated_exponential_tail", 16)):
        law = np.zeros(25); law[index] = 1.; law_cases[name] = law
    dde_checks = []
    with np.load(args.dde_evidence / "RAW_ROLLOUTS.npz", allow_pickle=False) as raw:
        for case in dde_summary["cases"]:
            name, n = case["case"], case["intervals"]
            evaluated = np.asarray([law_cases[name] @ kernels[n].basis(t, selected_reset) for t in GAPS])
            actual = raw[f"{name}_n{n}_MHA"]
            if not np.array_equal(actual, np.asarray(case["actual_M_H_A"])):
                raise ValueError("actual DDE raw/summary mismatch")
            dde_checks.append({"case": name, "intervals": n,
                               "kernel_M_H_A": evaluated.tolist(), "retained_actual_DDE_M_H_A": actual.tolist(),
                               "maximum_absolute_kernel_DDE_difference_M_H_A": np.max(abs(evaluated-actual), axis=0).tolist()})
    if len(dde_checks) != 8:
        raise ValueError("all eight DDE fixtures required")
    source_after = {name: digest(path.read_bytes()) for name, path in sources.items()}
    inputs_after = {name: digest(Path(name).read_bytes()) for name in identities}
    if source_before != source_after or identities != inputs_after:
        raise ValueError("source or original evidence changed during full execution")
    result = {
        "schema": "hcsn-v2-actual-source-all-original-laws-finite-diagnostic-v1",
        "status": "EXPOSED_POST_FAILURE_DIAGNOSTIC_COMPLETE_HOLD_NO_GO",
        "candidate_source_head": SOURCE_HEAD, "original_positions": 14336, "files": files,
        "metrics": list(METRICS), "reports": reports,
        "R_definition": "ordinary refractory occupancy at T, not a discounted integral; at T<=delay equals expected new hits plus unreleased initial phase mass",
        "discounted_refractory_occupation": "also retained separately as total discounted initial mass-time minus A; this is an algebraic complement, not independent evidence",
        "continuum_64_128_maximum_absolute_difference_M_H_R_A": quadrature_error.tolist(),
        "prior_M_continuum_vs_original_discrete_event_receipt_maximum_difference": old_event_difference,
        "relative_reference_floor": 1e-12, "minimum_observed_gap": .001, "observed_gaps": list(GAPS),
        "new_prospective_gate_created": False, "finite_domain_qualified": False,
        "rare_phase_relative_precision_qualified": False,
        "scope": "actual graded generator and actual migrated laws; fixed-law finite kernel evaluation on exposed visits; not all-visit DDE or filtered trajectory replay",
        "unique_gap_reset_laws": len(references), "unique_reset_models_per_grid": len(validated_resets),
        "actual_lift_checks": lift_reports, "actual_reset_checks": reset_identities,
        "eight_retained_actual_DDE_crosschecks": dde_checks,
        "retained_DDE_source_relation": relations,
        "DDE_R_crosscheck": "prior eight-case archive records M/H/A, so no independently measured R field is claimed",
        "source_sha256_before": source_before, "source_sha256_after": source_after,
        "input_sha256_before": identities, "input_sha256_after": inputs_after,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
        "cost_scope": "full driver after imports, source/input guards, actual lift construction, spectral kernels, continuum quadratures, all rows, array write/readback, eight-case comparison; shared CPU; excludes original DDE experiments and model/training/energy",
        "new_neural_model_executions": 0, "new_training_executions": 0,
        "wall_seconds": time.perf_counter()-wall, "cpu_seconds": time.process_time()-cpu,
    }
    (args.output_dir / "SUMMARY.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps({"status": result["status"], "candidate_source_head": SOURCE_HEAD,
                      "positions": len(visits), "files": files, "reports": reports,
                      "maximum_DDE_crosscheck_M_H_A": np.max([c["maximum_absolute_kernel_DDE_difference_M_H_A"] for c in dde_checks], axis=0).tolist(),
                      "wall_seconds": result["wall_seconds"], "cpu_seconds": result["cpu_seconds"]}))


if __name__ == "__main__":
    main()
