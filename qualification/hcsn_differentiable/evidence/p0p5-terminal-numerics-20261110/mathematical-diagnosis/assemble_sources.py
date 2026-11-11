"""Bind read-only source/archived scalar inputs for the short-time note."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import zipfile


ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
REPO = WORK / "hcsn-repo"
V8 = WORK / "v8-local-validation/source"
EXPECTED_CAPSULE = "288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102"


def identify(payload):
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def save(name, value):
    content = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with (ROOT / name).open("xb") as stream:
        stream.write(content)
    return identify(content)


def main():
    started, cpu = time.monotonic(), time.process_time()
    sources = [
        ("S1", "MODEL.md", REPO / "qualification/hcsn_differentiable/MODEL.md", "Sections 2, 4, perpetual continuum/QPR distinction; existing limitations"),
        ("S2", "TRAINING_DOMAIN.md", REPO / "qualification/hcsn_differentiable/TRAINING_DOMAIN.md", "Repeated constant-gap pressure versus finite real-gap continuation"),
        ("S3", "test_operator.py", REPO / "qualification/hcsn_differentiable/tests/test_operator.py", "Declared aligned transport, early-release/refinement, returning-tail and non-semigroup fixtures; tests not rerun"),
        ("S4", "operator.py", V8 / "qualification/hcsn_differentiable/operator.py", "_gauss_legendre_unit, _point_row, _construct, forward duration==0; exact source-node and phase-overlap definitions"),
        ("S5", "contract.py", V8 / "qualification/hcsn_differentiable/contract.py", "GridSpec uniform geometry and allowed fixed quadrature orders"),
        ("S6", "frozen_tables.py", V8 / "proposals/localization-v3/frozen_tables.py", "FrozenTableOperator invokes unchanged super().forward; exact-identity memoization"),
        ("S6", "cores.py", V8 / "proposals/localization-v3/cores.py", "HCSNCore uses the operator/cache and freezes physical parameters"),
        ("S6", "network.py", V8 / "qualification/hcsn_differentiable/network.py", "BoundedPhysics defaults mu=-.12, sigma=.35; source values, not checkpoint tensor reads"),
        ("S7", "campaign-v2-plan.json", REPO / "qualification/hcsn_differentiable/evidence/p0p5-20261110/p2/campaign-v2-plan.json", "Frozen active256/endpoint4.8/phase16/q32/refractory.2 geometry"),
        ("S8", "pressure-summary-RESULT.json", WORK / "terminal-six-model-pressure-summary-v1/RESULT.json", "Previously archived observer-derived scalar summary: 18 pressure checks,12 failed; no new reads of complete domain reports"),
        ("S9", "scalar_geometry_check.py", ROOT / "scalar_geometry_check.py", "Single standard-library q32 node-geometry computation; no probability propagation"),
        ("S9", "SCALAR-GEOMETRY.json", ROOT / "SCALAR-GEOMETRY.json", "Actual scalar geometry output; nominal-parameter scope and unknown outer/manual cost explicit"),
    ]
    context = ROOT / "source-context"
    context.mkdir(exist_ok=False)
    entries, originals = [], {}
    for group, name, path, support in sources:
        payload = path.read_bytes()
        item = {"id": group, "original_path": str(path), "snapshot": f"source-context/{name}", "supports": support, **identify(payload)}
        with (context / name).open("xb") as stream:
            stream.write(payload)
        originals[str(path)] = identify(payload)
        entries.append(item)
    capsule_path = WORK / "training-source-v8.zip"
    capsule = identify(capsule_path.read_bytes())
    assert capsule["sha256"] == EXPECTED_CAPSULE
    member_checks = []
    with zipfile.ZipFile(capsule_path) as archive:
        assert archive.testzip() is None
        for relative in ("qualification/hcsn_differentiable/operator.py", "qualification/hcsn_differentiable/contract.py", "qualification/hcsn_differentiable/network.py", "proposals/localization-v3/cores.py", "proposals/localization-v3/frozen_tables.py"):
            data = archive.read(relative)
            assert data == (V8 / relative).read_bytes()
            member_checks.append({"member": relative, **identify(data), "equals_local_v8_source": True})
    aliases = []
    for name in ("operator.py", "contract.py"):
        canonical = REPO / "qualification/hcsn_differentiable" / name
        reference = V8 / "qualification/hcsn_differentiable" / name
        assert canonical.read_bytes() == reference.read_bytes()
        aliases.append({"canonical": str(canonical), "v8_local": str(reference), **identify(canonical.read_bytes()), "equal": True})
        originals[str(canonical)] = identify(canonical.read_bytes())
    pressure = json.loads((context / "pressure-summary-RESULT.json").read_text())
    assert (pressure["pressure_case_count"], pressure["pressure_failed_count"], pressure["pressure_passed_count"]) == (18, 12, 6)
    index = {
        "schema": "hcsn-fixed-grid-short-time-source-index-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Source text plus an already frozen observer-derived scalar pressure summary; no live audit outputs, production model/probability arrays or E access.",
        "entries": entries,
        "actual_v8_source_capsule": {"path": str(capsule_path), **capsule},
        "capsule_member_checks": member_checks,
        "canonical_v8_aliases": aliases,
        "source_snapshot_markdown_links": "Unchanged historical document bytes retain their original repository link context.",
        "derivations": {
            "D1": {"kind": "analytic derivation in NOTE.md, no operator experiment", "assumptions": ["fixed positive cell width", "sigma>0", "finite fixed drift", "interior equal cells away from absorbing/tail boundaries", "exact uniform source integration"], "claim": "adjacent probability has sqrt(h) leading order; the fixed-mesh matrix generator has no finite entrywise limit"},
            "D2": {"kind": "analytic Gaussian-tail asymptotic, not a measured failure attribution", "assumptions": ["fixed finite strictly interior nodes", "positive finite quadrature weights", "fixed positive nearest-edge distance", "ideal real arithmetic", "undiscounted active interior probability rows"], "claim": "adjacent mass/h tends to zero; scaled asymptotics differ from exact integration; unscaled matrices can both tend to identity"},
            "D3": {"kind": "isolated phase-overlap/Markov-chain derivation", "assumptions": ["fixed phase width omega", "0<h<omega", "release absorbing for this isolated calculation", "one-based phase index j"], "claim": "geometric dwell times converge to j exponential dwell times; original uniform remaining-time law is different; no full coupled-network limit claimed"},
            "D4": {"kind": "information-loss counterexample at fixed tail mass", "assumptions": ["same total tail coefficient", "two positive tail laws differing by translation", "continuum discounted first-hit moment exp(-kappa*x), kappa>0"], "claim": "Q cannot retain the difference in future return moments; fixed exponential R changes shape independently of mass conservation"},
        },
        "pressure_scope": {key: pressure[key] for key in ("scope", "pressure_quantity", "pressure_case_count", "pressure_failed_count", "pressure_passed_count", "pressure_error_definition", "finite_burst_distinction", "groups", "original_observer_result_sha256")},
        "not_established": ["quantitative error shares/signs for the12 pressure failures", "quadrature accuracy at1e-7 or8e-7", "true posterior correctness", "long-run event-rate or escape qualification of the finite chain", "whole training-state numerical qualification", "scientific benefit", "P5 optimization admission"],
        "numerical_qualification": "HOLD",
        "scientific_admission": "HOLD",
        "implementation_changes": 0,
        "training_or_model_oracle_runs": 0,
        "E_reads": 0,
    }
    save("SOURCE-INDEX.json", index)
    followup = {
        "schema": "hcsn-prospective-fixed-grid-toy-diagnosis-v1",
        "status": "design_only_not_executed",
        "execution_authorized": False,
        "purpose": "Isolate local mechanisms without trained models or posterior data; not a qualification sweep or P5 benefit test.",
        "resources": {"whole_hard_wall_seconds": 120, "RSS_bytes": 268435456, "workers": 1, "threads": 1, "retries": 0, "overrun_or_unresolved": "HOLD and retain all planned/unrun cases and known cost"},
        "allowed_runtime": "Python standard library only; exact pinned Gauss-node builder; no Torch, mpmath, scipy, model constructors, archived probability arrays, native training or E",
        "fixed_order": ["free Gaussian adjacent-cell cases", "isolated phase cases", "tail moment counterexample", "hash/cost/roster archive"],
        "active": {"case_pairs": 42, "widths": [4.8 / 128, 4.8 / 256], "node_orders": [16, 32, 64], "sigma": .35, "mu": 0, "h_rule_per_width_order": "h_star=(width*min_node/sigma)^2; five h=h_star*[1e-4,1e-2,1,1e2,1e4], then fixed h=1e-7 and8e-7; all42 pairs retained, even identical numeric h", "reference": "the exact free-Gaussian uniform-cell formula in NOTE D1, evaluated as scalar FP64 with declared cancellation/underflow bounds or inconclusive flags", "comparison": "same event probability summed over fixed Gauss nodes; report p/sqrt(h),p/h,h/h_star and absolute/relative difference when resolvable", "forbidden_claim": "No actual killed/reflected full operator, posterior or perpetual value has been tested by these free-kernel scalars."},
        "phase": {"cases": 4, "m": 16, "delay": .2, "initial_j_one_based": 16, "h_over_phase_width": [.5, .25, .125, .0625], "observation_time": .1, "comparison": "absorbing release from isolated stay/down phase chain versus the same initial physical uniform law on[(j-1)omega,j*omega]; finite-chain release by a binomial tail plus exact geometric mean/variance; no reset/active diffusion", "record": "do not replace initial uniform-law reference by a deterministic point to inflate the error"},
        "tail": {"cases": 2, "law_shifts": [0, 1], "law": "L+shift+Exp(lambda),L4.8,lambda1", "sigma": .35, "mu": -.12, "discount": .15, "moment": "exp(-kappa*(L+shift))*lambda/(lambda+kappa), kappa=(mu+sqrt(mu^2+2*discount*sigma^2))/sigma^2", "claim": "equal Q tail coefficient can hide distinct analytic moments; no actual model tail distribution is inferred"},
        "output": ["all fixed inputs/node identities", "all48 toy case records", "FP64 resolution limits/inconclusive entries", "whole/child named CPU/wall/RSS", "unchanged source hashes", "complete roster including failures/unrun"],
        "decision_rule": "Report whether the local predictions are supported at resolved scalar points; no numeric or scientific qualification status is upgraded. If any case contradicts the derivation, preserve it before changing the design.",
        "further_real_law_attribution": "Requires a separately bounded and source-bound plan after this toy study; not authorized or implemented here.",
    }
    save("FOLLOWUP-PLAN.json", followup)
    save("MATH-CROSSCHECK.json", {
        "schema": "hcsn-collaboration-math-crosscheck-v1",
        "reviewer": "/root/numerics",
        "provenance": "Assistant transcription of collaboration messages during preparation; not a native measurement or independent final-byte note review.",
        "agreed": ["fixed-cell exact-source sqrt(h) term including +/-mu*h/(2*Delta)", "fixed-node active interior probability generator tends to zero; discounted operator retains-rho I", "isolated phase geometric/Erlang limit with1-based j and different uniform-law mean", "only scaled short-time limits are noninterchangeable; raw T can tend to I on both paths"],
        "required_limits": ["no automatic extension to all operator rows", "do not infer observed tiny gaps are in the fixed-node asymptotic regime", "no quantitative attribution of12 pressure failures"],
        "reviewer_new_tool_computations": 0,
        "reviewer_model_or_oracle_runs": 0,
    })
    for path, expected in originals.items():
        assert identify(Path(path).read_bytes()) == expected, path
    assert identify(capsule_path.read_bytes()) == capsule
    save("PREPARATION-RECEIPT.json", {
        "schema": "hcsn-short-time-note-preparation-v1",
        "status": "source_bound_analytic_note_and_unexecuted_toy_design",
        "input_bytes_unchanged": True,
        "unique_source_snapshots": len(entries),
        "v8_capsule_members_byte_checked": len(member_checks),
        "only_scalar_execution": "scalar_geometry_check.py single q32 Gauss rule and geometry ratios; exact output identity inSOURCE-INDEX",
        "outer_manual_review_CPU_wall": None,
        "assembly_prefix_wall_seconds": time.monotonic() - started,
        "assembly_prefix_own_CPU_seconds": time.process_time() - cpu,
        "cost_scope": "After imports through this receipt construction; excludes serialization/ZIP/final exit and manual review. No complete total cost is claimed.",
        "model_probability_E_access": False,
        "implementation_changes": False,
        "qualification_or_P5_credit": False,
    })
    for target in ("SOURCE-INDEX.json", "FOLLOWUP-PLAN.json"):
        assert (ROOT / target).is_file()
    files = {str(path.relative_to(ROOT)): identify(path.read_bytes()) for path in sorted(ROOT.rglob("*")) if path.is_file()}
    save("MANIFEST.json", {"schema": "hcsn-short-time-note-manifest-v1", "files": files})
    archive_path = ROOT.with_suffix(".zip")
    with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(set(archive.namelist())) == len(files) + 1
        for name, expected in files.items():
            assert identify(archive.read(name)) == expected
    print(json.dumps({"directory": str(ROOT), "NOTE": identify((ROOT / "NOTE.md").read_bytes()), "SOURCE_INDEX": identify((ROOT / "SOURCE-INDEX.json").read_bytes()), "MANIFEST": identify((ROOT / "MANIFEST.json").read_bytes()), "zip": {"path": str(archive_path), **identify(archive_path.read_bytes())}, "members": len(files) + 1}, sort_keys=True))


if __name__ == "__main__":
    main()
