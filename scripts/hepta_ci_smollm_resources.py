"""Read first-harness provisioning observations, never native owner requirements."""

from pathlib import Path, PurePosixPath
import re
import shutil


def cgroup_memory(proc=Path("/proc/self")):
    """Retain the visible v2 hierarchy; unavailable or hidden limits stay unknown."""
    result = {
        "status": "unknown",
        "visible_groups": [],
        "visible_finite_headroom_bytes": None,
        "hidden_ancestor_limits": "unknown",
        "errors": [],
    }
    try:
        membership = (proc / "cgroup").read_text()
        mounts = (proc / "mountinfo").read_text()
        result["proc_self_cgroup"] = membership
        entries = [
            line[3:] for line in membership.splitlines() if line.startswith("0::")
        ]
        if len(entries) != 1:
            raise ValueError("no unique cgroup v2 membership; v1 limits not observed")
        group = PurePosixPath(entries[0])
        if not group.is_absolute() or ".." in group.parts:
            raise ValueError("cgroup membership cannot be mapped safely")
        candidates = []
        for line in mounts.splitlines():
            fields, separator, kind = line.partition(" - ")
            if separator and kind.split()[0] == "cgroup2":
                values = fields.split()
                root, mount = (
                    re.sub(r"\\(040|011|012|134)", lambda m: chr(int(m[1], 8)), value)
                    for value in values[3:5]
                )
                root, mount = PurePosixPath(root), Path(mount)
                if group.is_relative_to(root) and mount.is_absolute():
                    candidates.append((len(root.parts), root, mount, line))
        if not candidates:
            raise ValueError("no visible cgroup v2 mount maps this process")
        # Prefer the widest visible mount so a nested bind mount cannot hide a
        # tighter ancestor that is readable through the enclosing mount.
        _, root, mount, line = min(candidates, key=lambda item: item[0])
        result["mountinfo_entry"] = line
        directory = mount / group.relative_to(root)
        headrooms = []
        while True:
            row = {"path": str(directory), "memory.max": None, "memory.current": None}
            for name in ("memory.max", "memory.current"):
                try:
                    value = (directory / name).read_text().strip()
                    if not (
                        re.fullmatch(r"[0-9]+", value)
                        or name == "memory.max"
                        and value == "max"
                    ):
                        raise ValueError(f"invalid {name}")
                    row[name] = value
                except (OSError, ValueError) as error:
                    result["errors"].append(f"{directory / name}: {error}")
            limit, current = row["memory.max"], row["memory.current"]
            if limit not in (None, "max") and current is not None:
                row["headroom_bytes"] = max(0, int(limit) - int(current))
                headrooms.append(row["headroom_bytes"])
            result["visible_groups"].append(row)
            if directory == mount:
                break
            directory = directory.parent
        result["visible_finite_headroom_bytes"] = min(headrooms) if headrooms else None
        result["status"] = (
            "partial" if result["errors"] else "observed-visible-hierarchy"
        )
    except (OSError, ValueError, IndexError) as error:
        result["errors"].append(str(error))
    return result


def resource_snapshot(output):
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    return {
        "schema": "hepta-smollm-resource-preflight-v1",
        "scope": "conservative-first-harness-provisioning-not-owner-requirement",
        "host_memavailable_bytes": int(memory["MemAvailable"].split()[0]) * 1024,
        "free_disk_bytes": shutil.disk_usage(output).free,
        "minimum_memory_observation_bytes": 6 * 1024**3,
        "minimum_disk_observation_bytes": 8 * 1024**3,
        "cgroup_memory": cgroup_memory(),
        "effective_allocatable_memory_bytes": None,
        "capacity_guaranteed": False,
    }


def require_provisioning(resources):
    # These are the same first-harness floors, not original worker limits.
    # A known tighter enclosing limit cannot be replaced by host MemAvailable.
    minimum = resources["minimum_memory_observation_bytes"]
    if resources["host_memavailable_bytes"] < minimum:
        raise ValueError(
            "first harness provisioning requires host MemAvailable >= 6 GiB"
        )
    headroom = resources["cgroup_memory"]["visible_finite_headroom_bytes"]
    if headroom is not None and headroom < minimum:
        raise ValueError(
            "first harness provisioning has visible cgroup headroom < 6 GiB"
        )
    if resources["free_disk_bytes"] < resources["minimum_disk_observation_bytes"]:
        raise ValueError("first harness provisioning requires free disk >= 8 GiB")
