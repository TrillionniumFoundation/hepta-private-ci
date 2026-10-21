"""Observe Linux memory ceilings without inferring a reservation or model pass.

The kernel's non-root-only cgroup.type interface distinguishes a namespace or
bind-mount root from the actual hierarchy root. Missing memory.max alone cannot
make that distinction. Incomplete or hidden ancestry retains only an upper
bound, never an effective complete-hierarchy ceiling.
"""

import errno
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MAX_RECORD_BYTES = 256 * 1024
MAX_ANCESTORS = 64


def capture(*, source_commit, runner_image, proc=Path("/proc"), system=Path("/")):
    started = datetime.now(timezone.utc).isoformat()
    files, failures, errors = {}, {}, []

    def read(path, *, label=None):
        key = label or str(path)
        try:
            if path.is_symlink():
                raise ValueError("symlink interface file is not an observation")
            with path.open("rb") as stream:
                raw = stream.read(MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError("resource record exceeds 256 KiB")
            value = raw.decode("utf-8", errors="strict")
            files[key] = {
                "path": str(path),
                "text": value,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
            return value
        except (OSError, ValueError) as error:
            failures[key] = {
                "path": str(path),
                "errno": getattr(error, "errno", None),
                "error": str(error),
            }
            return None

    def missing(path):
        return failures.get(str(path), {}).get("errno") == errno.ENOENT

    def names(value):
        if value is None:
            return None
        parts = value.split()
        if len(set(parts)) != len(parts) or any(
            not re.fullmatch("[a-z_]+", part) for part in parts
        ):
            raise ValueError("invalid controller names")
        return parts

    def number(value, *, unlimited=False):
        if value is None:
            return None
        token = value.strip()
        if unlimited and token == "max":
            return None
        if not re.fullmatch("[0-9]+", token) or int(token) > 2**63 - 1:
            raise ValueError("invalid memory interface number")
        return int(token)

    meminfo = read(proc / "meminfo")
    cgroups = read(proc / "self/cgroup")
    mounts = read(proc / "self/mountinfo")
    total, available, root_signature, stable = None, None, False, False
    rows, hierarchy_resolved, root_path = [], False, None
    try:
        if meminfo is None or cgroups is None or mounts is None:
            raise ValueError("required proc observation unavailable")
        values = {}
        for line in meminfo.splitlines():
            if line.startswith(("MemTotal:", "MemAvailable:")):
                match = re.fullmatch(r"(MemTotal|MemAvailable):\s+([0-9]+) kB", line)
                if match is None or match[1] in values:
                    raise ValueError("invalid or duplicate physical memory field")
                values[match[1]] = int(match[2]) * 1024
        total, available = values.get("MemTotal"), values.get("MemAvailable")
        if total is None or total <= 0 or available is not None and available > total:
            raise ValueError("invalid physical memory census")
        lines = cgroups.splitlines()
        if len(lines) != 1 or not lines[0].startswith("0::"):
            raise ValueError("one unified hierarchy required; legacy/hybrid is unknown")
        records = []
        for line in mounts.splitlines():
            left, right = line.split(" - ", 1)
            fields, filesystem = left.split(), right.split()[0]
            if len(fields) < 6:
                raise ValueError("incomplete mountinfo record")
            records.append((fields[3], fields[4], filesystem))
        unified = [record for record in records if record[2] == "cgroup2"]
        if len(unified) != 1:
            raise ValueError("one unambiguous visible cgroup-v2 mount required")
        mount_root, mount_point, _ = unified[0]
        process_path = lines[0][3:]
        for value in (mount_root, mount_point, process_path):
            if (
                not PurePosixPath(value).is_absolute()
                or ".." in PurePosixPath(value).parts
                or "\\" in value
            ):
                raise ValueError("escaped or invalid cgroup path is not interpreted")
        for record in records:
            if record != unified[0] and PurePosixPath(record[1]).is_relative_to(
                PurePosixPath(mount_point)
            ):
                raise ValueError("overmounted cgroup view cannot attest its interfaces")
        relative = PurePosixPath(process_path).relative_to(PurePosixPath(mount_root))
        visible_mount = system / mount_point.lstrip("/")
        root_path = str(visible_mount)
        current = visible_mount / relative
        while True:
            if len(rows) >= MAX_ANCESTORS:
                raise ValueError("visible ancestry exceeds bounded 64-node census")
            kind = read(current / "cgroup.type")
            limit = read(current / "memory.max")
            usage = read(current / "memory.current")
            controllers = names(read(current / "cgroup.controllers"))
            subtree = names(read(current / "cgroup.subtree_control"))
            actual_root = (
                current == visible_mount
                and mount_root == "/"
                and missing(current / "cgroup.type")
                and missing(current / "memory.max")
                and controllers is not None
                and subtree is not None
            )
            if not actual_root and (kind is None or kind.strip() != "domain"):
                raise ValueError("missing, invalid or threaded cgroup type is unknown")
            rows.append(
                {
                    "directory": str(current),
                    "cgroup_type": kind.strip() if kind is not None else None,
                    "global_root_interface_signature": actual_root,
                    "controllers": controllers,
                    "subtree_controllers": subtree,
                    "memory_max_bytes": number(limit, unlimited=True),
                    "memory_max_is_unlimited": limit is not None
                    and limit.strip() == "max",
                    "memory_current_bytes": number(usage),
                    "limit_state": "read" if limit is not None else "unresolved",
                    "limit_absent": missing(current / "memory.max"),
                    "usage_absent": missing(current / "memory.current"),
                }
            )
            if current == visible_mount:
                root_signature = actual_root
                break
            current = current.parent
        for index, row in enumerate(rows):
            if row["global_root_interface_signature"]:
                row["limit_state"] = "global_root_has_no_memory_max"
            elif row["limit_state"] == "unresolved" and index + 1 < len(rows):
                parent_controls = rows[index + 1]["subtree_controllers"]
                if (
                    row["limit_absent"]
                    and row["usage_absent"]
                    and parent_controls is not None
                    and "memory" not in parent_controls
                ):
                    row["limit_state"] = "memory_controller_disabled_by_visible_parent"
        hierarchy_resolved = all(row["limit_state"] != "unresolved" for row in rows)
        if not hierarchy_resolved:
            errors.append("missing non-root memory limit without parent disable proof")
        # A migration or remount during collection invalidates a complete view.
        stable = (
            read(proc / "self/cgroup", label="process_cgroup_after") == cgroups
            and read(proc / "self/mountinfo", label="mountinfo_after") == mounts
        )
        if not stable:
            errors.append("process cgroup or mount view changed during observation")
        leaf = Path(rows[0]["directory"])
        for name in ("memory.stat", "memory.events", "memory.high", "memory.peak"):
            read(leaf / name)
    except (ValueError, IndexError) as error:
        errors.append(str(error))
        hierarchy_resolved = False
    finite_limits = [
        row["memory_max_bytes"] for row in rows if row["memory_max_bytes"] is not None
    ]
    ceiling_bound = min([total, *finite_limits]) if total is not None else None
    complete = root_signature and hierarchy_resolved and stable and not errors
    gaps = [
        max(0, row["memory_max_bytes"] - row["memory_current_bytes"])
        for row in rows
        if row["memory_max_bytes"] is not None
        and row["memory_current_bytes"] is not None
    ]
    if available is not None:
        gaps.append(available)
    return {
        "schema": "hepta.memory-strong-rag.actual-resource-snapshot.v2",
        "started_at": started,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runner_image": runner_image,
        "runner_metadata": {
            key: os.environ.get(key)
            for key in (
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB",
                "RUNNER_NAME",
                "RUNNER_ENVIRONMENT",
                "ImageOS",
                "ImageVersion",
            )
        },
        "pid": os.getpid(),
        "hostname": os.uname().nodename,
        "physical_memory_total_bytes": total,
        "host_mem_available_bytes": available,
        "visible_mount": root_path,
        "global_root_interface_signature_observed": root_signature,
        "visible_cgroup_hierarchy_resolved": hierarchy_resolved,
        "membership_and_mount_view_stable": stable,
        "visible_cgroup_limits": rows,
        "observed_visible_capacity_upper_bound_bytes": ceiling_bound,
        "observed_complete_hierarchy_memory_ceiling_bytes": ceiling_bound
        if complete
        else None,
        "observed_unreclaimed_headroom_upper_bound_bytes": min(gaps) if gaps else None,
        "hidden_ancestor_limits_not_attested": not (root_signature and stable),
        "raw_files": files,
        "read_failures": failures,
        "errors": errors,
        "scope": (
            "Linux physical RAM and visible cgroup-v2 ceilings; unsigned, "
            "non-atomic observation. Includes reclaimable cache in memory.current. "
            "Not reserved available RAM, a NUMA/rlimit census, or a model "
            "execution admission."
        ),
        "eligible_host_reserved": False,
        "same_hardware_on_next_run_guaranteed": False,
        "full_inference_latency_qualified": False,
        "new_model_calls": 0,
        "production_accepted": False,
    }


def write_snapshot(path, *, source_commit, runner_image):
    result = capture(source_commit=source_commit, runner_image=runner_image)
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return result
