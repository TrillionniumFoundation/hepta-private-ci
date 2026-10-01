#!/usr/bin/env python3
"""Emit and verify readiness against retained stages, logs and Git identities.

Self digests protect consistency only. These repository witnesses cannot issue
scientific, operational, promotion or release acceptance.
"""

import argparse
import hashlib
import importlib
import json
import re
import subprocess
from pathlib import Path

MAP = importlib.import_module("hepta-learning-operator-map")
STAGE = importlib.import_module("hepta-learning-operator-stage")
RECEIPT = importlib.import_module("hepta-learning-operator-receipt")
ROOT = Path(__file__).resolve().parents[1]
REQUIRED_STAGES = (
    "source_identity",
    "documentation_schema",
    "default_api_surface",
    "compile",
    "unit_tests",
    "product_integration",
    "mutation",
    "coverage",
    "resource_performance",
    "static_quality",
    "deterministic_merge",
    "exact_source_receipt",
)
SHA_FIELDS = (
    "source_head_sha",
    "frozen_source_sha",
    "observation_head_sha",
    "base_sha",
    "deterministic_merge_sha",
    "github_merge_sha",
    "workflow_sha",
    "source_tree_hash",
)
EXTERNAL_GATES = {
    "independentScientificAcceptance",
    "targetHostCapacityAccepted",
    "operatorAcceptance",
    "canaryAccepted",
    "promotionAuthorized",
    "activation",
    "release",
}
INPUT_PATHS = {
    "toolchain",
    "test_set",
    "implementation_map",
    "stage_directory",
    "workflow",
}
DOCUMENT_PATHS = (
    "docs/modules/learning.operator/STATUS.json",
    "docs/modules/learning.operator/STATUS.schema.json",
    "docs/modules/learning.operator/TECHNICAL.md",
    "docs/modules/learning.operator/DEVELOPER_GUIDE.md",
    "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
    "docs/modules/learning.operator/SCHEMA_COMPATIBILITY.json",
    "docs/modules/learning.operator/IMPLEMENTATION_MAP.json",
    "qualification/module-execution-dossiers/detail/learning.operator.md",
)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def exact_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def repository_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("readiness input path absent")
    path = Path(value)
    result = ROOT / path
    if (
        path.is_absolute()
        or ".." in path.parts
        or not result.resolve().is_relative_to(ROOT.resolve())
    ):
        raise ValueError(f"readiness input path escapes root: {value!r}")
    return result


def canonical_digest(paths: list[Path]) -> str:
    payload = bytearray()
    for path in sorted(paths, key=lambda value: value.as_posix()):
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        raw = path.read_bytes()
        payload.extend(len(relative).to_bytes(4, "big"))
        payload.extend(relative)
        payload.extend(len(raw).to_bytes(8, "big"))
        payload.extend(raw)
    return digest_bytes(bytes(payload))


def load_stages(directory: Path, execution_identity: dict) -> dict[str, dict]:
    result = {}
    for name in REQUIRED_STAGES:
        path = directory / f"{name}.json"
        if not path.is_file():
            result[name] = {
                "stage": name,
                "status": "not_run",
                "reason": "stage receipt missing",
            }
        else:
            result[name] = STAGE.verify_value(
                json.loads(path.read_text(encoding="utf-8")), name, execution_identity
            )
    return result


def stage_projection(directory: Path, stages: dict[str, dict]) -> dict[str, dict]:
    return {
        name: {
            "status": value["status"],
            "reason": value.get("reason", ""),
            "receipt_sha256": digest_file(directory / f"{name}.json")
            if (directory / f"{name}.json").is_file()
            else None,
        }
        for name, value in stages.items()
    }


def execution_identity(value: dict) -> dict:
    return {
        "sourceSha": value["source_head_sha"],
        "sourceTree": value["source_tree_hash"],
        "workflowRunId": value["workflow_run_id"],
        "runAttempt": value["attempt_id"],
    }


def artifact_hashes(evidence: Path, output: Path) -> dict[str, str]:
    result = {}
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.resolve() != output.resolve():
            if not path.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError(f"evidence path resolves outside root: {path}")
            result[path.relative_to(ROOT).as_posix()] = digest_file(path)
    return result


def untracked_compilation_inputs() -> list[str]:
    """Find source/config additions, including ignored Cargo autodiscovery inputs.

    Generated evidence and build outputs remain allowed. Source directories and
    crate-local build/config paths are scanned without Git ignore filtering so
    an info/exclude rule cannot hide a new bin, test or build script.
    """
    tracked = MAP.git("ls-files", "-z", "--", "codex-rs").split("\0")
    crates = {Path(path).parent for path in tracked if path.endswith("/Cargo.toml")}
    source_paths = {
        str(crate / child)
        for crate in crates | {Path("."), Path("codex-rs")}
        for child in (
            "src",
            "tests",
            "examples",
            "benches",
            "build.rs",
            "Cargo.toml",
            "Cargo.lock",
            ".cargo/config",
            ".cargo/config.toml",
            ".config/nextest.toml",
            "rust-toolchain",
            "rust-toolchain.toml",
        )
    }
    additions = {
        path
        for path in MAP.git(
            "ls-files", "--others", "-z", "--", *sorted(source_paths)
        ).split("\0")
        if path
    }
    # Also catch a new nonignored crate/manifest outside the known source roots.
    for raw in MAP.git("ls-files", "--others", "--exclude-standard", "-z").split("\0"):
        path = Path(raw)
        if (
            raw
            and not {"target", ".hepta-evidence"}.intersection(path.parts)
            and (
                path.suffix in {".rs", ".toml", ".bzl", ".bazel"}
                or path.name
                in {"Cargo.lock", "BUILD", "WORKSPACE", "justfile", "rust-toolchain"}
            )
        ):
            additions.add(raw)
    return sorted(additions)


def identity_errors(value: dict) -> list[str]:
    errors = []
    source, base = value["source_head_sha"], value["base_sha"]
    tree, synthetic = value["source_tree_hash"], value["deterministic_merge_sha"]

    def check(label, operation):
        try:
            operation()
        except (
            ValueError,
            OSError,
            subprocess.CalledProcessError,
            KeyError,
            TypeError,
        ) as error:
            errors.append(f"{label}: {type(error).__name__}: {error}")

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def source_identity():
        require(
            MAP.git("rev-parse", f"{source}^{{commit}}") == source,
            "source commit unknown",
        )
        require(
            MAP.git("rev-parse", f"{source}^{{tree}}") == tree, "source tree mismatch"
        )
        require(
            MAP.git("rev-parse", "HEAD") == source, "source is not the checked-out head"
        )
        require(
            not MAP.git("status", "--porcelain", "--untracked-files=no"),
            "tracked checkout differs from the checked-out source",
        )
        # Git otherwise hides edits marked assume-unchanged or skip-worktree.
        # Such a checkout cannot witness the exact source compiled by the gates.
        require(
            not any(
                row[0].islower() or row.startswith("S ")
                for row in MAP.git("ls-files", "-v").splitlines()
                if row
            ),
            "tracked checkout contains hidden worktree/index entries",
        )
        require(
            not untracked_compilation_inputs(),
            "untracked source/config inputs can change the compiled source",
        )
        require(
            MAP.git("rev-parse", f"{base}^{{commit}}") == base, "base commit unknown"
        )
        for key in ("frozen_source_sha", "observation_head_sha"):
            identity = value[key]
            require(
                MAP.git("rev-parse", f"{identity}^{{commit}}") == identity,
                f"{key} unknown",
            )
        MAP.git("merge-base", "--is-ancestor", value["frozen_source_sha"], source)
        require(
            value["observation_head_sha"] == source,
            "observation must name the checked-out candidate",
        )

    check("source_identity", source_identity)

    def merge_identity():
        RECEIPT.verify_synthetic_merge(source, base, synthetic)
        parents = MAP.git("rev-list", "--parents", "-n", "1", synthetic).split()
        require(
            parents == [synthetic, base, source],
            "synthetic parent order or cardinality mismatch",
        )
        github = value["github_merge_sha"]
        require(
            MAP.git("rev-parse", f"{github}^{{commit}}") == github,
            "GitHub commit unknown",
        )
        if github != source:
            require(
                MAP.git("rev-list", "--parents", "-n", "1", github).split()
                == [github, base, source],
                "GitHub merge parents mismatch",
            )
            require(
                MAP.git("rev-parse", f"{github}^{{tree}}")
                == MAP.git("rev-parse", f"{synthetic}^{{tree}}"),
                "GitHub and deterministic merge trees differ",
            )

    check("merge_identity", merge_identity)
    check(
        "workflow_identity",
        lambda: require(
            MAP.git("rev-parse", f"{source}:{value['input_paths']['workflow']}")
            == value["workflow_sha"],
            "workflow blob mismatch",
        ),
    )
    check(
        "implementation_projection",
        lambda: MAP.verify(
            repository_path(value["input_paths"]["implementation_map"]),
            expected_sha=source,
            expected_tree=tree,
        ),
    )
    return errors


def verify_qualification(value: dict, path: Path) -> None:
    """Bind readiness to the same verified qualification and execution inputs."""
    receipt = RECEIPT.verify(
        path.with_name("qualification-manifest.json"),
        expected_sha=value["source_head_sha"],
        expected_tree=value["source_tree_hash"],
    )
    inputs = value["input_paths"]
    expected = {
        "currentMain": {"sha": value["base_sha"]},
        "workflow": {
            "path": inputs["workflow"],
            "blobSha": value["workflow_sha"],
            "runId": value["workflow_run_id"],
            "runAttempt": value["attempt_id"],
        },
    }
    for key, definition in expected.items():
        if receipt.get(key) != definition:
            raise ValueError(f"readiness/qualification identity disagreement: {key}")
    if (
        receipt["syntheticMerge"]["sha"] != value["deterministic_merge_sha"]
        or receipt["compiler"]["target"] != value["target_triple"]
    ):
        raise ValueError("readiness/qualification merge or target disagreement")
    for key, digest_key, path_key, input_key in (
        ("dependencyLock", "Cargo.lock_hash", "path", None),
        ("compiler", "toolchain_hash", "evidencePath", "toolchain"),
        ("testSet", "test_set_hash", "evidencePath", "test_set"),
        ("implementationMap", "implementation_map_hash", "path", "implementation_map"),
    ):
        row = receipt[key]
        expected_path = (
            "codex-rs/Cargo.lock" if input_key is None else inputs[input_key]
        )
        if row.get("sha256") != value[digest_key] or row.get(path_key) != expected_path:
            raise ValueError(
                f"readiness/qualification retained input disagreement: {key}"
            )
    stage_directory = repository_path(inputs["stage_directory"])
    for row in receipt["evidence"]:
        gate = json.loads(repository_path(row["path"]).read_text(encoding="utf-8"))
        expected_stage = stage_directory / f"{RECEIPT.GATE_STAGES[row['name']]}.json"
        if (
            repository_path(gate["stageReceipt"]["path"]).resolve()
            != expected_stage.resolve()
        ):
            raise ValueError(
                "qualification references a different execution stage directory"
            )


def emit(args: argparse.Namespace) -> None:
    output = repository_path(args.output)
    inputs = {
        "toolchain": args.toolchain_file,
        "test_set": args.test_set_file,
        "implementation_map": args.implementation_map,
        "stage_directory": args.stage_directory,
        "workflow": args.workflow_path,
    }
    directory = repository_path(inputs["stage_directory"])
    identity = {
        "sourceSha": args.source_head_sha,
        "sourceTree": args.source_tree_hash,
        "workflowRunId": args.workflow_run_id,
        "runAttempt": args.attempt_id,
    }
    stages = load_stages(directory, identity)
    payload = {
        "schema": "hepta.learning-operator-readiness.v1",
        "schemaVersion": 1,
        "module": "learning.operator",
        "input_paths": inputs,
        **{field: getattr(args, field) for field in SHA_FIELDS},
        **{
            field: getattr(args, field)
            for field in (
                "workflow_run_id",
                "attempt_id",
                "runner_image",
                "target_triple",
            )
        },
        "Cargo.lock_hash": digest_file(ROOT / "codex-rs/Cargo.lock"),
        "toolchain_hash": digest_file(repository_path(inputs["toolchain"])),
        "test_set_hash": digest_file(repository_path(inputs["test_set"])),
        "implementation_map_hash": digest_file(
            repository_path(inputs["implementation_map"])
        ),
        "documentation_hash": canonical_digest(
            [ROOT / path for path in DOCUMENT_PATHS]
        ),
        "stage_statuses": stage_projection(directory, stages),
        "artifact_hashes": {},
        "engineeringQualified": False,
        "mergeReady": False,
        "productionQualified": False,
        "externalGates": {key: False for key in sorted(EXTERNAL_GATES)},
    }
    for field in SHA_FIELDS:
        if not exact_sha(payload[field]):
            raise ValueError(f"{field} must be an exact 40-character SHA")
    payload["identity_errors"] = identity_errors(payload)
    payload["identity_verified"] = not payload["identity_errors"]
    all_passed = all(value["status"] == "passed" for value in stages.values())
    if all_passed and payload["identity_verified"]:
        verify_qualification(payload, output)
    qualified = all_passed and payload["identity_verified"]
    payload["engineeringQualified"] = qualified
    payload["mergeReady"] = qualified
    output.parent.mkdir(parents=True, exist_ok=True)
    payload["artifact_hashes"] = artifact_hashes(output.parent, output)
    payload["manifest_sha256"] = digest_bytes(MAP.canonical_bytes(payload))
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verify_path(output)


def verify_path(path: Path, *, require_qualified: bool = False) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema") != "hepta.learning-operator-readiness.v1"
        or type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != 1
        or value.get("module") != "learning.operator"
    ):
        raise ValueError("readiness schema/module mismatch")
    for field in SHA_FIELDS:
        if not exact_sha(value.get(field)):
            raise ValueError(f"readiness exact identity missing: {field}")
    inputs = value.get("input_paths")
    if not isinstance(inputs, dict) or set(inputs) != INPUT_PATHS:
        raise ValueError("readiness input path inventory mismatch")
    for raw in inputs.values():
        repository_path(raw)
    stages = load_stages(
        repository_path(inputs["stage_directory"]), execution_identity(value)
    )
    if value.get("stage_statuses") != stage_projection(
        repository_path(inputs["stage_directory"]), stages
    ):
        raise ValueError("readiness stage projection differs from retained receipts")
    for field, raw in (
        ("Cargo.lock_hash", "codex-rs/Cargo.lock"),
        ("toolchain_hash", inputs["toolchain"]),
        ("test_set_hash", inputs["test_set"]),
        ("implementation_map_hash", inputs["implementation_map"]),
    ):
        if value.get(field) != digest_file(repository_path(raw)):
            raise ValueError(f"readiness retained input hash drift: {field}")
    if value.get("documentation_hash") != canonical_digest(
        [ROOT / raw for raw in DOCUMENT_PATHS]
    ):
        raise ValueError("readiness documentation hash drift")
    if value.get("artifact_hashes") != artifact_hashes(path.parent, path):
        raise ValueError("readiness evidence artifact inventory/hash drift")
    errors = identity_errors(value)
    if value.get("identity_errors") != errors or value.get("identity_verified") is not (
        not errors
    ):
        raise ValueError(
            "readiness identity claim differs from Git and implementation witnesses"
        )
    all_passed = all(item["status"] == "passed" for item in stages.values())
    if all_passed and not errors:
        verify_qualification(value, path)
    qualified = all_passed and not errors
    if (
        value.get("engineeringQualified") is not qualified
        or value.get("mergeReady") is not qualified
    ):
        raise ValueError(
            "readiness qualification disagrees with execution and identity evidence"
        )
    if value.get("productionQualified") is not False:
        raise ValueError(
            "repository readiness cannot self-issue production qualification"
        )
    external = value.get("externalGates")
    if (
        not isinstance(external, dict)
        or set(external) != EXTERNAL_GATES
        or any(item is not False for item in external.values())
    ):
        raise ValueError(
            "external acceptance/activation gates must remain exactly false"
        )
    manifest_digest = value.pop("manifest_sha256", None)
    if manifest_digest != digest_bytes(MAP.canonical_bytes(value)):
        raise ValueError("readiness manifest digest mismatch")
    if require_qualified and not qualified:
        raise ValueError(
            "readiness is consistent but engineering qualification has not passed"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    write = subparsers.add_parser("emit")
    for name in (
        *SHA_FIELDS,
        "workflow_run_id",
        "attempt_id",
        "runner_image",
        "target_triple",
        "toolchain_file",
        "test_set_file",
        "implementation_map",
        "stage_directory",
        "output",
    ):
        write.add_argument("--" + name.replace("_", "-"), required=True)
    write.add_argument(
        "--workflow-path",
        default=".github/workflows/learning-operator-authoritative.yml",
    )
    check = subparsers.add_parser("verify")
    check.add_argument("--path", required=True)
    check.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    if args.action == "emit":
        emit(args)
    else:
        verify_path(
            repository_path(args.path), require_qualified=args.require_qualified
        )


if __name__ == "__main__":
    main()
