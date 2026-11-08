"""Check one Cell experiment's exact source and immutable input bindings.

This offline integrity check does not execute training, authenticate a CI
provider, grant owner authority, or qualify learning/production adoption.
"""

import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess


SCHEMA = "hepta.cell-joint-config.v1"
SCHEMA_V2 = "hepta.cell-joint-config.v2"
ROLES = frozenset(
    (
        "runtime",
        "incumbent_model",
        "candidate_model",
        "trainer",
        "data",
        "evaluator",
        "budget",
        "adoption_rules",
    )
)
CONTRACT_AXES = ("state_schema", "encoder", "backend")
MODEL_ROLES = ("incumbent_model", "candidate_model")
ROLES_V2 = ROLES | set(CONTRACT_AXES) | {"incumbent_" + axis for axis in CONTRACT_AXES}
SHA256 = re.compile(r"[0-9a-f]{64}")
GIT_OID = re.compile(r"[0-9a-f]{40}")


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"non-finite JSON value: {value}")

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite JSON number")
        return result

    return json.loads(
        raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number
    )


def git(root: Path, *args: str) -> str:
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        .decode("utf-8")
        .strip()
    )


def source_identity(root: Path) -> dict:
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("source checkout has staged, modified or untracked files")
    identity = {
        "commit": git(root, "rev-parse", "HEAD"),
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
        "index_tree": git(root, "write-tree"),
    }
    entries = subprocess.check_output(
        ["git", "-C", str(root), "ls-tree", "-rz", identity["tree"]]
    )
    versions = []
    with directory_root(root) as root_fd:
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            header, name = entry.split(b"\t", 1)
            mode, kind, oid = header.split()
            if kind != b"blob" or mode not in (b"100644", b"100755", b"120000"):
                raise ValueError("source requires tracked blobs, no submodules")
            if mode == b"120000":
                with parent_directory(root_fd, os.fsdecode(name)) as (parent, leaf):
                    before = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                    target = os.fsencode(os.readlink(leaf, dir_fd=parent))
                    digest = hashlib.sha1(
                        b"blob " + str(len(target)).encode() + b"\0" + target
                    )
                    after = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                    if (
                        not stat.S_ISLNK(before.st_mode)
                        or file_fingerprint(before) != file_fingerprint(after)
                        or digest.hexdigest().encode() != oid
                    ):
                        raise ValueError("tracked source symlink differs from Git tree")
                    versions.append((os.fsdecode(name), file_fingerprint(before)))
                continue
            with regular_file(root_fd, os.fsdecode(name)) as stream:
                before = os.fstat(stream.fileno())
                actual_mode = b"100755" if before.st_mode & 0o111 else b"100644"
                digest = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
                total = 0
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > before.st_size:
                        raise ValueError("tracked source grew during verification")
                    digest.update(chunk)
                if (
                    actual_mode != mode
                    or digest.hexdigest().encode() != oid
                    or file_fingerprint(before)
                    != file_fingerprint(os.fstat(stream.fileno()))
                ):
                    raise ValueError(
                        "tracked source bytes or mode differ from Git tree"
                    )
                versions.append((os.fsdecode(name), file_fingerprint(before)))
        for name, version in versions:
            with parent_directory(root_fd, name) as (parent, leaf):
                current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                if file_fingerprint(current) != version:
                    raise ValueError("tracked source path changed during verification")
    return identity


@contextmanager
def directory_root(root: Path):
    if (
        os.open not in os.supports_dir_fd
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
    ):
        raise ValueError(
            "verification requires POSIX descriptor-relative nofollow opens"
        )
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def parent_directory(root_fd: int, name: str):
    parts = Path(name).parts
    if not parts or Path(name).is_absolute() or ".." in parts:
        raise ValueError("file path must remain beneath its explicit root")
    parent = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            os.close(parent)
            parent = child
        yield parent, parts[-1]
    except OSError as error:
        raise ValueError(
            f"bound paths cannot follow symlinks: {name}: {error}"
        ) from error
    finally:
        os.close(parent)


@contextmanager
def regular_file(root_fd: int, name: str):
    with parent_directory(root_fd, name) as (parent, leaf):
        descriptor = os.open(
            leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("bound path is not a regular file")
            yield stream


def file_fingerprint(value: os.stat_result) -> tuple:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_artifact(
    root_fd: int, binding: dict, *, retain=False
) -> tuple[dict, bytes, tuple]:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "bytes"}:
        raise ValueError("artifact requires exactly path, sha256 and bytes")
    name, expected, size = binding["path"], binding["sha256"], binding["bytes"]
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("artifact path must be relative to the explicit artifact root")
    if ".." in Path(name).parts:
        raise ValueError("artifact path may not escape the artifact root")
    if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
        raise ValueError("artifact needs a complete lowercase SHA256")
    if type(size) is not int or size <= 0:
        raise ValueError("artifact bytes must be a positive integer")
    if retain and size > 4 * 1024 * 1024:
        raise ValueError("CI evidence exceeds the 4 MiB bound")
    digest = hashlib.sha256()
    payload = bytearray()
    total = 0
    with regular_file(root_fd, name) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size != size:
            raise ValueError(f"artifact file size mismatch: {name}")
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > size:
                raise ValueError("artifact grew while being read")
            digest.update(chunk)
            if retain:
                payload.extend(chunk)
        after = os.fstat(stream.fileno())
    if (
        total != size
        or file_fingerprint(before) != file_fingerprint(after)
        or digest.hexdigest() != expected
    ):
        raise ValueError(f"artifact bytes or identity changed: {name}")
    return dict(binding), bytes(payload), file_fingerprint(before)


def check_ci(document: dict, source: dict, workflows: list[str]) -> list[dict]:
    if not isinstance(document, dict) or not isinstance(
        document.get("workflow_runs"), list
    ):
        raise ValueError("CI evidence must be the complete workflow-runs payload")
    runs = document["workflow_runs"]
    if type(document.get("total_count")) is not int or document["total_count"] != len(
        runs
    ):
        raise ValueError("CI pagination is incomplete")
    if not runs or len(runs) > 100:
        raise ValueError("CI run count must be between 1 and 100")
    observed, ids = [], set()
    for run in runs:
        if (
            not isinstance(run, dict)
            or type(run.get("id")) is not int
            or run["id"] in ids
        ):
            raise ValueError("CI run identity is missing or duplicated")
        ids.add(run["id"])
        repository = run.get("repository")
        if (
            run.get("head_sha") != source["commit"]
            or not isinstance(repository, dict)
            or repository.get("full_name") != source["repository"]
        ):
            raise ValueError("CI run belongs to another source or repository")
        if run.get("path") in workflows:
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                raise ValueError("a required observed CI run has not succeeded")
            observed.append(
                {
                    key: run.get(key)
                    for key in ("id", "path", "head_sha", "run_attempt", "html_url")
                }
            )
    if {run["path"] for run in observed} != set(workflows):
        raise ValueError("required workflow evidence is missing")
    return observed


def canonical_sha256(document: dict) -> str:
    """Hash content identities using sorted, compact, ASCII JSON (no floats)."""
    raw = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def check_compatibility(declaration: dict, artifacts: dict) -> None:
    """Check bound declarations, not whether a model or migration is correct."""
    if (
        not isinstance(declaration, dict)
        or set(declaration) != {"schema", "models", "state_transition"}
        or declaration["schema"] != "hepta.cell-model-compatibility.v1"
    ):
        raise ValueError("unknown or incomplete model compatibility declaration")
    expected = {}
    for role in MODEL_ROLES:
        prefix = "incumbent_" if role == "incumbent_model" else ""
        expected[role] = {"model_sha256": artifacts[role]["sha256"]} | {
            axis + "_sha256": artifacts[prefix + axis]["sha256"]
            for axis in CONTRACT_AXES
        }
    if declaration["models"] != expected:
        raise ValueError(
            "model contract does not match bound model/schema/encoder/backend"
        )
    transition = declaration["state_transition"]
    mode = transition.get("mode") if isinstance(transition, dict) else None
    if mode in ("carry", "reset"):
        if set(transition) != {"mode"}:
            raise ValueError("carry/reset cannot contain undeclared transition fields")
        if (
            mode == "carry"
            and expected["incumbent_model"] != expected["candidate_model"]
        ):
            raise ValueError(
                "changed model/schema/encoder/backend requires reset or migration"
            )
    elif mode == "migrate":
        required = {
            "mode": "migrate",
            "migration_sha256": artifacts["state_migration"]["sha256"],
            "from_contract_sha256": canonical_sha256(expected["incumbent_model"]),
            "to_contract_sha256": canonical_sha256(expected["candidate_model"]),
        }
        if transition != required:
            raise ValueError(
                "migration must bind its artifact and both exact contracts"
            )
    else:
        raise ValueError("state transition must declare carry, reset or migrate")


def check_consumer_readback(
    result: dict, readback: dict, expected_model_role: str, expected_task_id: str
) -> dict:
    """Compare a supplied consumer declaration without authenticating execution."""
    if not isinstance(result, dict) or result.get("legacy", True):
        raise ValueError("legacy configurations have no complete consumption bundle")
    if result.get("schema") != "hepta.cell-joint-config-integrity.v2" or (
        result.get("configuration_integrity") != "verified"
    ):
        raise ValueError("consumer requires a verified v2 integrity result")
    bundle = result.get("bundle")
    if not isinstance(bundle, dict) or canonical_sha256(bundle) != result.get(
        "bundle_sha256"
    ):
        raise ValueError("verified bundle content no longer matches its digest")
    if expected_model_role not in MODEL_ROLES:
        raise ValueError("the expected selected model role must be explicit")
    fields = {
        "schema",
        "task_id",
        "model_role",
        "bundle_sha256",
        "model_sha256",
        "state_schema_sha256",
        "encoder_sha256",
        "backend_sha256",
    }
    if (
        not isinstance(readback, dict)
        or set(readback) != fields
        or (readback["schema"] != "hepta.cell-consumption-readback.v1")
    ):
        raise ValueError("unknown or incomplete consumer readback")
    if (
        not isinstance(readback["task_id"], str)
        or re.fullmatch(r"[\w./:@-]{1,256}", readback["task_id"]) is None
    ):
        raise ValueError("consumer task identity must be nonempty and bounded")
    if readback["task_id"] != expected_task_id:
        raise ValueError("consumer belongs to a different task")
    if readback["bundle_sha256"] != result["bundle_sha256"]:
        raise ValueError("consumer belongs to a different complete bundle")
    expected = result["bundle"]["compatibility"]["models"][expected_model_role]
    if (
        readback["model_role"] != expected_model_role
        or {key: readback[key] for key in expected} != expected
    ):
        raise ValueError("consumer selected model/schema/encoder/backend differs")
    return {
        "consumption_binding_integrity": "verified",
        "readback": dict(readback),
        "consumer_readback_authenticity_verified": False,
        "actual_successor_consumption_verified": False,
        "model_execution_verified": False,
    }


def verify(config: dict, source_root: Path, artifact_root: Path) -> dict:
    if not isinstance(config, dict) or config.get("schema") not in (SCHEMA, SCHEMA_V2):
        raise ValueError("unknown joint configuration schema")
    legacy = config["schema"] == SCHEMA
    fields = {
        "schema",
        "source",
        "artifacts",
        "required_workflows",
        "ci_evidence",
    } | (set() if legacy else {"compatibility"})
    if set(config) != fields:
        raise ValueError("joint configuration has unknown or missing fields")
    source = config.get("source")
    if not isinstance(source, dict) or set(source) != {"repository", "commit", "tree"}:
        raise ValueError("source requires repository, commit and tree")
    if (
        not isinstance(source["repository"], str)
        or re.fullmatch(r"[\w.-]+/[\w.-]+", source["repository"]) is None
    ):
        raise ValueError("source repository identity is invalid")
    if any(
        not isinstance(source[k], str) or GIT_OID.fullmatch(source[k]) is None
        for k in ("commit", "tree")
    ):
        raise ValueError("source commit and tree must be complete Git identities")
    artifacts = config.get("artifacts")
    roles = ROLES if legacy else ROLES_V2
    if not legacy:
        declaration = config["compatibility"]
        transition = (
            declaration.get("state_transition")
            if isinstance(declaration, dict)
            else None
        )
        if isinstance(transition, dict) and transition.get("mode") == "migrate":
            roles = roles | {"state_migration"}
    if not isinstance(artifacts, dict) or set(artifacts) != roles:
        raise ValueError(
            "all eight joint configuration roles must be bound"
            if legacy
            else "v2 requires all model, state_schema, encoder and backend roles (and declared migration)"
        )
    workflows = config.get("required_workflows")
    if (
        not isinstance(workflows, list)
        or not 1 <= len(workflows) <= 32
        or any(
            not isinstance(p, str)
            or re.fullmatch(r"\.github/workflows/[\w.-]+\.ya?ml", p) is None
            for p in workflows
        )
        or len(set(workflows)) != len(workflows)
    ):
        raise ValueError("required workflows must be an explicit bounded unique list")
    source_root = source_root.resolve(strict=True)
    artifact_root = artifact_root.resolve(strict=True)
    before = source_identity(source_root)
    if before != {
        "commit": source["commit"],
        "tree": source["tree"],
        "index_tree": source["tree"],
    }:
        raise ValueError("configuration does not name the actual clean execution tree")
    checked, versions = {}, []
    with directory_root(artifact_root) as artifact_fd:
        for role in sorted(roles):
            checked[role], _, version = read_artifact(artifact_fd, artifacts[role])
            versions.append((artifacts[role]["path"], version))
        ci_binding, ci_bytes, version = read_artifact(
            artifact_fd, config.get("ci_evidence"), retain=True
        )
        versions.append((ci_binding["path"], version))
        ci = check_ci(strict_json(ci_bytes), source, workflows)
        if not legacy:
            check_compatibility(config["compatibility"], checked)
        for name, version in versions:
            with regular_file(artifact_fd, name) as stream:
                if file_fingerprint(os.fstat(stream.fileno())) != version:
                    raise ValueError(
                        "artifact changed during joint configuration verification"
                    )
    if source_identity(source_root) != before:
        raise ValueError("source changed during configuration verification")
    result = {
        "schema": "hepta.cell-joint-config-integrity.v1"
        if legacy
        else "hepta.cell-joint-config-integrity.v2",
        "legacy": legacy,
        "configuration_integrity": "verified",
        "source": source,
        "artifacts": checked,
        "ci_evidence": ci_binding,
        "required_ci_runs": ci,
        "provider_authenticity_verified": False,
        "production_qualification": False,
        "authority_granted": False,
    }
    if not legacy:
        bundle = {
            "schema": "hepta.cell-consumption-bundle.v1",
            "source": dict(source),
            "artifacts": {
                role: {key: binding[key] for key in ("sha256", "bytes")}
                for role, binding in checked.items()
            },
            "compatibility": copy.deepcopy(config["compatibility"]),
            "required_workflows": sorted(workflows),
        }
        result.update(
            source=dict(source),
            bundle=bundle,
            bundle_sha256=canonical_sha256(bundle),
            compatibility_declaration_integrity="verified",
            semantic_compatibility_verified=False,
            state_transition_executed=False,
            model_execution_verified=False,
            actual_successor_consumption_verified=False,
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--consumer-readback", type=Path)
    parser.add_argument("--expected-model-role", choices=MODEL_ROLES)
    parser.add_argument("--expected-task-id")
    args = parser.parse_args()
    try:
        consumer_options = (
            args.consumer_readback,
            args.expected_model_role,
            args.expected_task_id,
        )
        if any(consumer_options) and not all(consumer_options):
            raise ValueError(
                "consumer readback requires an explicit expected model role and task identity"
            )
        if args.configuration.stat().st_size > 1024 * 1024:
            raise ValueError("configuration exceeds the 1 MiB bound")
        raw = args.configuration.read_bytes()
        output = args.output.resolve()
        if output.is_relative_to(args.source_root.resolve()):
            raise ValueError("integrity receipts must be outside the source checkout")
        result = verify(strict_json(raw), args.source_root, args.artifact_root)
        if args.consumer_readback:
            with directory_root(
                args.consumer_readback.parent.resolve(strict=True)
            ) as root_fd:
                with regular_file(root_fd, args.consumer_readback.name) as stream:
                    before = file_fingerprint(os.fstat(stream.fileno()))
                    consumer_raw = stream.read(1024 * 1024 + 1)
                    if len(consumer_raw) > 1024 * 1024 or before != file_fingerprint(
                        os.fstat(stream.fileno())
                    ):
                        raise ValueError("consumer readback changed or exceeds 1 MiB")
            result["consumer"] = check_consumer_readback(
                result,
                strict_json(consumer_raw),
                args.expected_model_role,
                args.expected_task_id,
            ) | {"readback_sha256": hashlib.sha256(consumer_raw).hexdigest()}
        result["configuration_sha256"] = hashlib.sha256(raw).hexdigest()
        result["observed_at_utc"] = datetime.now(timezone.utc).isoformat()
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        print(
            json.dumps(
                {
                    "configuration_integrity": "verified",
                    "production_qualification": False,
                }
            )
        )
        return 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"configuration_integrity": "rejected", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
