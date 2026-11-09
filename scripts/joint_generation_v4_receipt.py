"""Local source/run bindings for the synthetic v4 diagnostic, not build proofs."""

import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time


NATIVE = "codex-rs/hepta-infer-worker-host/src/"
SOURCE_PATHS = (
    *(
        "scripts/joint_generation_v4_" + name + ".py"
        for name in (
            "io",
            "model",
            "codecs",
            "ndu",
            "gradients",
            "diagnostic",
            "receipt",
        )
    ),
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/hepta-infer-worker-host/Cargo.toml",
    NATIVE + "bin/hepta-joint-propose.rs",
    *(
        NATIVE + "joint_generation/" + name + ".rs"
        for name in (
            "bridge_state",
            "codec",
            "decoder",
            "math",
            "media_codec",
            "model",
            "observation",
            "observed_model",
            "planner",
            "proposal",
            "protocol",
            "state",
            "text_codec",
        )
    ),
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def artifact_binding(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def source_binding(root, expected_commit=None):
    root = Path(root).resolve(strict=True)

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=True
        ).stdout

    commit = git("rev-parse", "HEAD").decode().strip()
    tree = git("rev-parse", commit + "^{tree}").decode().strip()
    object_format = git("rev-parse", "--show-object-format").decode().strip()
    head_blobs = {}
    for row in git("ls-tree", "-r", "-z", commit, "--", *SOURCE_PATHS).split(b"\0"):
        if row:
            entry, path = row.split(b"\t", 1)
            head_blobs[path.decode()] = entry.split()[2].decode()
    inventory, changed = {}, []
    for path in SOURCE_PATHS:
        raw = (root / path).read_bytes()
        actual_blob = hashlib.new(
            object_format, b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
        inventory[path] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if actual_blob != head_blobs.get(path):
            changed.append(path)
    if expected_commit is not None and (commit != expected_commit or changed):
        raise ValueError(
            "Expected source commit differs or required source bytes are dirty"
        )
    return {
        "commit": commit,
        "tree": tree,
        "required_source_sha256": inventory,
        "source_inventory_sha256": digest(inventory),
        "required_source_changes": changed,
        "required_sources_match_commit": not changed,
        "tracked_dirty_paths": [
            p.decode()
            for p in git("diff", "--name-only", "-z", commit).split(b"\0")
            if p
        ],
        "untracked_paths": [
            p.decode()
            for p in git("ls-files", "--others", "--exclude-standard", "-z").split(
                b"\0"
            )
            if p
        ],
        "inventory_scope": "v4 Python dependencies and standalone native stdio modules; system libraries are not source-certified",
    }


def build_attestation(path, source, binary):
    if path is None:
        return {"status": "not_provided", "source_build_proven": False}
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    bound = {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    value = json.loads(raw)
    expected = {
        "schema": "hepta.joint-v4.local-build-attestation.v1",
        "source_commit": source["commit"],
        "source_tree": source["tree"],
        "source_inventory_sha256": source["source_inventory_sha256"],
        "binary_sha256": binary["sha256"],
        "exit_code": 0,
    }
    if any(value.get(key) != item for key, item in expected.items()) or (
        not isinstance(value.get("command"), list)
        or not value["command"]
        or not all(isinstance(item, str) for item in value["command"])
        or not isinstance(value.get("compiler_version"), str)
        or type(value.get("exit_code")) is not int
    ):
        raise ValueError(
            "Local build attestation does not match tested source and binary"
        )
    return {
        "status": "matching_local_attestation",
        "artifact": bound,
        "statement": value,
        "source_build_proven": False,
        "authority": "caller-supplied local statement; hashes alone do not prove a build",
    }


class InvocationCost:
    """One enclosing interval; phase clocks are nested diagnostics, never added."""

    def __init__(self):
        self.wall = time.perf_counter()
        self.usage = tuple(
            resource.getrusage(who)
            for who in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)
        )

    def finish(self):
        now = tuple(
            resource.getrusage(who)
            for who in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)
        )
        cpu = [
            (end.ru_utime + end.ru_stime) - (start.ru_utime + start.ru_stime)
            for start, end in zip(self.usage, now, strict=True)
        ]
        return {
            "wall_seconds": time.perf_counter() - self.wall,
            "cpu_self_seconds": cpu[0],
            "cpu_reaped_children_seconds": cpu[1],
            "cpu_self_and_reaped_children_seconds": sum(cpu),
            "interval": "diagnostic run entry through receipt preparation; interpreter startup/import and final report write excluded",
            "nested_phase_clocks_summed": False,
            "energy_joules": None,
            "provider_charges": None,
            "complete_cost_claimed": False,
        }
