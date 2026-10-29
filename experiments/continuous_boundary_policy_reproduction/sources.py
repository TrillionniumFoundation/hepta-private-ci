"""Source and rebuilt-binary identities for a same-seed policy reproduction."""

from pathlib import Path

from experiments.continuous_boundary_policy.audit_integrity import (
    checked_file,
    read_json,
    strict_json,
    verify_protocol,
)
from experiments.continuous_boundary_policy.audit_math import require
from experiments.continuous_boundary_policy.common import (
    ARMS,
    CONTROLS,
    SEEDS,
    save_json,
    sha,
)
from .build_score import BASE, PRIOR_NATIVE_SHA256, REBUILT_NATIVE_SHA256

PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parent.parent
OLD_PACKAGE = PACKAGE.parent / "continuous_boundary_policy"
OLD_SEAL_SHA = "6b3afbf2af8476730c1260f470bd8f0f68d69652950499388abc3b178f0fd858"
PROTOCOL_SHA = "c55747dd06640b92aca2198dcbfa21a0a5bf53f5890daf6bc51aa257f887865a"
SCORE_SHA = "655b919aca126a33ee2fd54501b024eb80f4b1842b0e3410791958d93a588c47"
BINARY_SHA = {"native": REBUILT_NATIVE_SHA256, "score": SCORE_SHA}
RUNTIME = (
    "__init__.py",
    "build_score.py",
    "sources.py",
    "identity.py",
    "phases.py",
    "study.py",
    "audit.py",
    "smoke.py",
    "test_identity.py",
)
IDENTITY_FILES = ("PROTOCOL.json", "SOURCE_SEAL.json", "REPRODUCTION_PLAN.json")


def verify_plan(raw):
    plan = strict_json(raw)
    required = {
        "schema": "hepta.boundary-policy-reproduction.plan.v1",
        "reproduction_kind": "same_seed_rebuilt_binary_reproduction",
        "original_source_seal_sha256": OLD_SEAL_SHA,
        "original_protocol_sha256": PROTOCOL_SHA,
        "seeds": list(SEEDS),
        "arms": list(ARMS + CONTROLS),
        "independent_new_samples": False,
        "pool_with_original_results": False,
        "original_benefit_gates_passed": 0,
        "original_benefit_gates_total": 4,
        "original_result_replaced": False,
        "original_policy_raw_evidence_recovered": False,
        "original_binaries_recovered": False,
        "new_binary_sha256": BINARY_SHA,
        "new_runtime_costs_required": True,
        "authority": "DENY_ALL",
    }
    require(
        all(plan.get(k) == v for k, v in required.items()),
        "Reproduction interpretation changed",
    )
    return plan


def verify_builds(repository=REPOSITORY):
    package = repository / PACKAGE.relative_to(REPOSITORY)
    preflight = package / "preflight"
    native = read_json(preflight, "NATIVE_BUILD.json")
    score = read_json(preflight, "SCORE_BUILD.json")
    require(
        native["schema"] == "hepta.continuous-boundary.native-build.v1",
        "Native receipt schema",
    )
    require(
        score["schema"] == "hepta.boundary-policy-reproduction.native-score-build.v1",
        "Score receipt schema",
    )
    for key, receipt, name in (
        ("native", native, "NATIVE_SOURCE_MANIFEST.json"),
        ("score", score, "SCORE_SOURCE_MANIFEST.json"),
    ):
        raw = (preflight / name).read_bytes()
        require(
            receipt["base_commit"] == BASE
            and receipt["binary_sha256"] == BINARY_SHA[key],
            "Rebuilt binary identity mismatch",
        )
        require(
            strict_json(raw) == receipt["source_sha256"],
            "Build source manifest differs",
        )
        for relative, identity in receipt["source_sha256"].items():
            if relative.startswith("experiments/"):
                checked_file(repository, relative, identity)
    require(
        sha((preflight / "SCORE_SOURCE_MANIFEST.json").read_bytes())
        == score["source_manifest_digest"],
        "Score source digest mismatch",
    )
    require(
        score["builder_sha256"] == sha((package / "build_score.py").read_bytes()),
        "Score build is not bound to final builder",
    )
    require(
        score["prior_builder_sha256"]
        == sha(
            (
                repository / "experiments/continuous_boundary_policy/native/build.py"
            ).read_bytes()
        ),
        "Original builder changed",
    )
    for key in (
        "compiler_sha256",
        "repository_lock_sha256",
        "resolved_lock_sha256",
        "generated_build_manifests",
    ):
        require(
            native[key] == score[key], "Native/score dependency or compiler mismatch"
        )
    require(
        native["native_rust_sources_unmodified"] is True
        and native["external_dependencies_match_original_lock"] is True,
        "Native build lineage changed",
    )
    require(
        score["rebuilt_native_binary_sha256"] == BINARY_SHA["native"]
        and score["prior_native_binary_sha256"] == PRIOR_NATIVE_SHA256,
        "Score parent identity changed",
    )
    require(
        score["rebuilt_native_binary_unchanged"] is True
        and score["prior_original_binary_recovered"] is False,
        "Rebuilt binary mislabeled",
    )
    require(
        score["original_native_sources_unchanged"] is True
        and score["external_dependencies_match_original_lock"] is True,
        "Score source/dependency lineage changed",
    )
    nt, st = (
        read_json(preflight, "NATIVE_VALIDATION.json"),
        read_json(preflight, "SCORE_TESTS.json"),
    )
    require(
        nt["binary_sha256"] == BINARY_SHA["native"]
        and nt["successful"] is True
        and nt["tests"] == 6
        and nt["errors"] == nt["failures"] == 0,
        "Native behavior tests do not bind rebuilt binary",
    )
    require(
        st["binary_sha256"] == BINARY_SHA["score"]
        and st["success"] is True
        and st["tests_run"] == 5
        and st["errors"] == st["failures"] == 0,
        "Score behavior tests do not bind rebuilt binary",
    )
    return native, score


def verify_source(source, repository=REPOSITORY):
    package = repository / PACKAGE.relative_to(REPOSITORY)
    old_path = repository / "experiments/continuous_boundary_policy/SOURCE_SEAL.json"
    require(
        sha(old_path.read_bytes()) == OLD_SEAL_SHA,
        "Original policy source seal changed",
    )
    inherited = strict_json(old_path.read_bytes())["source_files"]
    require(len(inherited) == 67, "Original source roster changed")
    require(
        source["schema"] == "hepta.continuous-boundary-policy.source-seal.v1",
        "Unsupported source seal",
    )
    require(
        source["reproduction_of_source_seal_sha256"] == OLD_SEAL_SHA,
        "Reproduction source lineage changed",
    )
    required = {str((package / name).relative_to(repository)) for name in RUNTIME}
    required.update(
        str((package / name).relative_to(repository))
        for name in ("PROTOCOL.json", "REPRODUCTION_PLAN.json")
    )
    required.update(
        str(p.relative_to(repository))
        for p in (package / "preflight").iterdir()
        if p.is_file() and p.suffix in {".json", ".log"}
    )
    required.add(str(old_path.relative_to(repository)))
    require(
        required <= set(source["source_files"]),
        "Reproduction source seal omits required implementation or evidence",
    )
    for relative, identity in inherited.items():
        require(
            source["source_files"].get(relative) == identity,
            "Inherited source file missing or rebound",
        )
    for relative, identity in source["source_files"].items():
        checked_file(repository, relative, identity)
    require(
        source["prior_source_seal_sha256"]
        == sha(
            (
                repository / "experiments/continuous_boundary_flow/SOURCE_SEAL.json"
            ).read_bytes()
        ),
        "Prior flow seal changed",
    )
    raw_protocol = (package / "PROTOCOL.json").read_bytes()
    require(sha(raw_protocol) == PROTOCOL_SHA, "Original protocol bytes changed")
    verify_protocol(strict_json(raw_protocol))
    raw_plan = (package / "REPRODUCTION_PLAN.json").read_bytes()
    verify_plan(raw_plan)
    require(
        source["reproduction_plan_sha256"] == sha(raw_plan),
        "Reproduction plan binding mismatch",
    )
    native, score = verify_builds(repository)
    for key, receipt in (("native", native), ("score", score)):
        require(
            source[f"{key}_binary_sha256"] == receipt["binary_sha256"],
            "Source seal binary mismatch",
        )
        relative = str(
            (package / "preflight" / f"{key.upper()}_BUILD.json").relative_to(
                repository
            )
        )
        require(
            source[f"{key}_build_receipt_path"] == relative,
            "Build receipt path changed",
        )
        require(
            source[f"{key}_build_receipt_sha256"]
            == sha((repository / relative).read_bytes()),
            "Build receipt binding changed",
        )
    return source


def freeze_source(repository=REPOSITORY):
    """Run after final formatting/rebuild and before publication or training."""
    repository = Path(repository)
    package = repository / PACKAGE.relative_to(REPOSITORY)
    old_package = repository / OLD_PACKAGE.relative_to(REPOSITORY)
    target = package / "SOURCE_SEAL.json"
    require(not target.exists(), "Reproduction source is already sealed")
    old_raw = (old_package / "SOURCE_SEAL.json").read_bytes()
    require(sha(old_raw) == OLD_SEAL_SHA, "Original source seal changed")
    files = dict(strict_json(old_raw)["source_files"])
    for relative, identity in files.items():
        checked_file(repository, relative, identity)
    for path in package.rglob("*"):
        if path.is_file() and (
            path.suffix == ".py"
            or (
                "preflight" in path.relative_to(package).parts
                and path.suffix in {".json", ".log"}
            )
        ):
            files[str(path.relative_to(repository))] = sha(path.read_bytes())
    for path in (
        old_package / "SOURCE_SEAL.json",
        package / "PROTOCOL.json",
        package / "REPRODUCTION_PLAN.json",
    ):
        files[str(path.relative_to(repository))] = sha(path.read_bytes())
    source = {
        "schema": "hepta.continuous-boundary-policy.source-seal.v1",
        "study_kind": "same_seed_rebuilt_binary_reproduction",
        "source_files": files,
        "reproduction_of_source_seal_sha256": OLD_SEAL_SHA,
        "reproduction_plan_sha256": sha(
            (package / "REPRODUCTION_PLAN.json").read_bytes()
        ),
        "prior_source_seal_sha256": sha(
            (package.parent / "continuous_boundary_flow/SOURCE_SEAL.json").read_bytes()
        ),
    }
    for key in BINARY_SHA:
        path = package / "preflight" / f"{key.upper()}_BUILD.json"
        source[f"{key}_binary_sha256"] = BINARY_SHA[key]
        source[f"{key}_build_receipt_path"] = str(path.relative_to(repository))
        source[f"{key}_build_receipt_sha256"] = sha(path.read_bytes())
    verify_source(source, repository)
    identity = save_json(target, source)
    return {
        "source_seal_sha256": identity,
        "protocol_sha256": PROTOCOL_SHA,
        "files": len(files),
    }
