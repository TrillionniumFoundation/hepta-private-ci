#!/usr/bin/env python3
"""Fixed-command native HIA / real GRU worker for an authorized runtime entry.

This program is not an authorization service or a daemon adoption endpoint.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import sys
import time
import numpy as np
from package_hia_cell_candidate import git, read_file, relative
from hepta_cells.bundle import Bundle
from hepta_cells.component_types import (
    Budget,
    CellError,
    ComponentIdentity,
    Partition,
    PendingExecution,
)
from hepta_cells.hia_component import HiaCellComponent
from hepta_cells.lifecycle import CellOwner
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def device():
    numeric_paths = [
        Path(importlib.util.find_spec("numpy._core._multiarray_umath").origin)
    ]
    numeric_paths.extend((Path(np.__file__).parent.parent / "numpy.libs").glob("*.so*"))
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "python_sha256": sha(Path(sys.executable).resolve()),
        "host_identity_sha256": hashlib.sha256(platform.node().encode()).hexdigest(),
        "numpy_binaries": {p.name: sha(p) for p in sorted(numeric_paths)},
        "thread_settings": {
            name: __import__("os").environ.get(name)
            for name in (
                "OPENBLAS_NUM_THREADS",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
        "numeric_profile": "float64",
        "byteorder": sys.byteorder,
    }


def verify_candidate_source_closure(value, roots):
    """Admit only a complete execution closure; optional provenance stays scoped."""
    required = {
        ("cells", "scripts/" + name)
        for name in (
            "hepta_cell_joint_worker.py",
            "hepta_cell_campaign_worker.py",
            "hepta_cell_semantic_campaign_worker.py",
            "runtime_stdio.py",
            "runtime_process_contract.py",
            "runtime_process_bridge.py",
            "qualify_runtime_process_bridge.py",
            "qualify_runtime_campaign.py",
            "refreeze_joint_worker.py",
            "package_hia_cell_candidate.py",
            "qualify_hia_cell_joint.py",
            "qualify_cell_updates.py",
            "verify_hepta_maintenance_cycle.py",
            "verify_hepta_semantic_cycle.py",
            "review_hepta_maintenance_snapshot.py",
        )
    }
    for group, prefixes in (
        ("cells", ("scripts/hepta_cells", "scripts/hepta_pred1")),
        ("hia", ("hepta",)),
    ):
        root = roots[group]
        names = {
            str(path.relative_to(root))
            for prefix in prefixes
            for path in (root / prefix).rglob("*.py")
        }
        # Portable Cell bundles need not carry a checkout. When one is present,
        # missing tracked sources remain required even under skip-worktree.
        if (root / ".git").exists():
            names.update(
                name
                for name in git(
                    root, "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", *prefixes
                )
                .decode()
                .split("\0")
                if name.endswith(".py")
            )
        required.update((group, name) for name in names)
    listed = {}
    for item in value["files"]:
        if item["root"] not in ("cells", "hia"):
            continue
        key = (item["root"], str(relative(item["path"])))
        if key in listed:
            raise ValueError("duplicate source in execution closure")
        listed[key] = item["sha256"]
    if not required <= listed.keys():
        raise ValueError("candidate lacks required execution source closure")
    # Old v1 records without this optional field still need the complete source
    # closure. Reading them does not invent an original HEAD/tree qualification.
    if "source_identity" not in value:
        return
    identities = value["source_identity"]
    if type(identities) is not dict or set(identities) != {"cells", "hia"}:
        raise ValueError("source identity must cover the Cell and HIA execution roots")
    for group, identity in identities.items():
        if (
            identity.get("schema") != "hepta.joint-source-identity.v1"
            or identity.get("object_format") not in {"sha1", "sha256"}
            or type(identity.get("exact_head_source")) is not bool
            or type(identity.get("allow_dirty")) is not bool
            or type(identity.get("git_status_porcelain")) is not str
        ):
            raise ValueError("invalid execution source identity")
        width = 40 if identity["object_format"] == "sha1" else 64
        if any(
            not re.fullmatch("[0-9a-f]{" + str(width) + "}", identity.get(key, ""))
            for key in ("head", "tree")
        ):
            raise ValueError("invalid original Git identity")
        rows = identity["files"]
        names = [str(relative(row["path"])) for row in rows]
        expected = {name for source_group, name in listed if source_group == group}
        if len(set(names)) != len(names) or set(names) != expected:
            raise ValueError(
                "source identity scope differs from execution file closure"
            )
        for row in rows:
            raw, mode = read_file(roots[group], row["path"])
            checksum = hashlib.sha256(raw).hexdigest()
            blob = hashlib.new(
                identity["object_format"],
                b"blob " + str(len(raw)).encode() + b"\0" + raw,
            ).hexdigest()
            if (
                checksum != row["sha256"]
                or checksum != listed[(group, row["path"])]
                or len(raw) != row["bytes"]
                or blob != row["git_blob"]
                or format(mode | 0o100000, "o") != row["mode"]
            ):
                raise ValueError("execution bytes or mode differ from source identity")
            if identity["exact_head_source"] and (
                blob != row["head_blob"] or row["mode"] != row["head_mode"]
            ):
                raise ValueError(
                    "execution source differs from its claimed original HEAD"
                )
        if identity["exact_head_source"] and identity["git_status_porcelain"]:
            raise ValueError("dirty source cannot claim exact original HEAD bytes")
    cells = identities["cells"]
    if value["source_bases"]["cells"] != (
        cells["head"] if cells["exact_head_source"] else None
    ):
        raise ValueError("Cell source base differs from execution identity")


def load_candidate(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    if len(raw) > 2**20:
        raise ValueError("candidate manifest exceeds bound")
    value = strict_json(raw)
    if (
        value["schema"] != "hepta.joint-cell-candidate.v1"
        or value["device"] != device()
    ):
        raise ValueError("candidate schema or device/numeric environment changed")
    roots = {
        "cells": Path(__file__).resolve().parent.parent,
        "hia": Path(value["hia_root"]).resolve(strict=True),
        "artifacts": path.parent,
    }
    required = {
        ("cells", "scripts/hepta_cell_joint_worker.py"),
        ("cells", "scripts/hepta_cells/hia_component.py"),
        ("hia", "tools/cell_bridge_native.py"),
        ("hia", "examples/hia_cell_bridge/continuation.hepta"),
        ("hia", "pyproject.toml"),
        ("artifacts", "native/build.json"),
        ("artifacts", "inputs.json"),
    }
    required.update(
        ("cells", "scripts/" + name)
        for name in (
            "hepta_cell_campaign_worker.py",
            "runtime_stdio.py",
            "runtime_process_contract.py",
            "runtime_process_bridge.py",
            "qualify_runtime_process_bridge.py",
            "qualify_runtime_campaign.py",
            "refreeze_joint_worker.py",
            "package_hia_cell_candidate.py",
        )
    )
    required.update(
        ("hia", "docs/" + name)
        for name in (
            "HIA_CORE_LOWERING_ABI.json",
            "HIA_CORE_EMITTER_ABI.json",
            "HIA_BYTE_WRAPPER_ABI.json",
            "HIA_MACHINE_OBJECT_ABI.json",
        )
    )
    required.update(
        ("hia", str(p.relative_to(roots["hia"])))
        for p in (roots["hia"] / "hepta").rglob("*.py")
    )
    observed = set()
    for item in value["files"]:
        key, root = (item["root"], item["path"]), roots[item["root"]]
        location = (root / item["path"]).resolve(strict=True)
        if (
            key in observed
            or not location.is_relative_to(root)
            or not location.is_file()
        ):
            raise ValueError("duplicate or escaping candidate artifact")
        if sha(location) != item["sha256"]:
            raise ValueError("candidate artifact changed: " + item["path"])
        observed.add(key)
    for package in ("hepta_cells", "hepta_pred1"):
        required.update(
            ("cells", str(p.relative_to(roots["cells"])))
            for p in (roots["cells"] / "scripts" / package).glob("*.py")
        )
    if not required <= observed:
        raise ValueError("candidate lacks required source closure")
    verify_candidate_source_closure(value, roots)
    native = value["native"]
    build = strict_json((roots["artifacts"] / "native/build.json").read_bytes())
    if (
        build["compiler_commit"] != value["source_bases"]["hia_compiler"]
        or build["image_sha256"] != native["image_sha256"]
        or build["source_sha256"] != native["source_sha256"]
    ):
        raise ValueError("compiler/build/source binding differs")
    if ("artifacts", native["image"]) not in observed or sha(
        roots["artifacts"] / native["image"]
    ) != native["image_sha256"]:
        raise ValueError("native image binding differs")
    for model in value["models"].values():
        if ("artifacts", model["path"]) not in observed or sha(
            roots["artifacts"] / model["path"]
        ) != model["sha256"]:
            raise ValueError("model artifact binding differs")
    spec = importlib.util.spec_from_file_location(
        "hepta_joint_native_bridge", roots["hia"] / "tools/cell_bridge_native.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    bridge = module.NativeCellBridge(
        roots["hia"],
        roots["artifacts"] / native["image"],
        native["image_sha256"],
        expected_source_sha256=native["source_sha256"],
    )
    return value, hashlib.sha256(raw).hexdigest(), roots, bridge


def execute(candidate_path, database, request, *, admission_directory=None):
    start = time.perf_counter_ns()
    if type(request) is not dict or set(request) != {
        "request_id",
        "cell_id",
        "operation",
        "payload",
    }:
        raise ValueError("one exact bounded worker request required")
    if admission_directory is not None:
        if request["operation"] != "readback":
            raise ValueError(
                "qualification admission is restricted to original readback"
            )
        # Keep qualification-only imports out of ordinary maintenance source identity.
        from hepta_cells.joint_concurrency import wait_joint_phase
    value, candidate_hash, roots, native = load_candidate(candidate_path)
    model = value["models"][request["cell_id"]]
    kernel, _ = TemporalKernel.restore_checkpoint(
        roots["artifacts"] / model["path"],
        expected_sha256=model["sha256"],
        cell_id=request["cell_id"],
        config=TemporalConfig(**model["config"]),
    )
    partition = Partition(**value["partition"], cell_id=request["cell_id"])
    owner = CellOwner(database)
    inner = TemporalComponent(kernel, Bundle(**model["bundle"]), partition.run_id)
    component = HiaCellComponent(
        owner,
        inner,
        native,
        candidate_sha256=candidate_hash,
        image_sha256=value["native"]["image_sha256"],
    )
    try:
        active = owner.db.execute(
            "SELECT identity FROM cells WHERE partition=?", (partition.digest,)
        ).fetchone()
        if (
            active
            and ComponentIdentity(**json.loads(active["identity"]))
            != component.identity
        ):
            raise CellError("requested candidate differs from the active Cell identity")
        if not active:
            if request["operation"] != "step":
                raise CellError("unknown partition; readback cannot create a Cell")
            owner.create(
                partition,
                component,
                budget=Budget(**value["budget"]),
                total_work_units=value["total_work_units"],
            )
        operation = request["operation"]
        if admission_directory is not None:
            # A cold open may correctly reject concurrently changing retained
            # bytes. Admit both owners before the qualification releases work.
            wait_joint_phase(admission_directory, "ADMITTED")
        if operation == "step":
            result = owner.step(
                partition, component, request["request_id"], request["payload"]
            )
        elif operation == "readback":

            def readback(pending):
                if admission_directory is not None:
                    # Reconcile has already retained this readback attempt and
                    # released its transaction. Require both attempts to exist
                    # before either native continuation can finish.
                    wait_joint_phase(admission_directory, "READBACK")
                return component.readback(pending)

            result = owner.reconcile(
                partition, component, request["request_id"], readback
            )
        elif operation == "cancel":
            result = owner.request_cancel(partition, component, request["request_id"])
            component.observe_cancellation(partition, request["request_id"])
        elif operation == "checkpoint":
            result = owner.checkpoint(partition)
        elif operation == "status":
            result = owner.status(partition)
        else:
            raise ValueError("unsupported worker operation")
        return {
            "status": "observed",
            "candidate_sha256": candidate_hash,
            "result": result,
            "continuation": component.continuation_status(
                partition, request["request_id"]
            ),
            "worker_wall_ns": time.perf_counter_ns() - start,
        }
    except PendingExecution as error:
        return {
            "status": "pending",
            "candidate_sha256": candidate_hash,
            "reason": str(error),
            "owner": owner.status(partition),
            "continuation": component.continuation_status(
                partition, request["request_id"]
            ),
            "worker_wall_ns": time.perf_counter_ns() - start,
        }
    finally:
        owner.close()
        native.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--admission-directory",
        type=Path,
        help="qualification-only two-process readback barrier; not an authority or recovery override",
    )
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError("worker request exceeds 65536 bytes")
    result = execute(
        args.candidate,
        args.database,
        strict_json(raw),
        admission_directory=args.admission_directory,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0 if result["status"] == "observed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
