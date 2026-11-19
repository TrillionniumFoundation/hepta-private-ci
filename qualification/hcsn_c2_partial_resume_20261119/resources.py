"""Read the fresh controller cgroup chain without numerical imports."""

from pathlib import Path


def cgroup_chain():
    relative = next((row.split(":", 2)[2] for row in Path("/proc/self/cgroup").read_text().splitlines()
                     if row.startswith("0::")), None)
    if relative is None:
        raise ValueError("unified cgroup resource identity unavailable")
    root = Path("/sys/fs/cgroup")
    directory = root / relative.lstrip("/")
    rows = []
    while directory.is_relative_to(root):
        row = {"path": str(directory)}
        for name in ("memory.max", "memory.current", "memory.events", "cpu.max"):
            path = directory / name
            if path.is_file():
                row[name] = path.read_text().strip()
        rows.append(row)
        if directory == root:
            break
        directory = directory.parent
    return rows


def resource_rejections(rows, budget):
    reasons = []
    if not rows or rows[0].get("memory.max") != str(budget["controller_memory_max_bytes"]):
        reasons.append("actual transient cgroup MemoryMax differs from the frozen allocation")
    if not rows or rows[0].get("cpu.max", "").split() != ["100000", "100000"]:
        reasons.append("actual transient cgroup CPUQuota differs from one CPU")
    for row in rows:
        maximum = row.get("memory.max")
        if maximum not in (None, "max"):
            if "memory.current" not in row or int(maximum) - int(row["memory.current"]) < budget["minimum_finite_cgroup_headroom_bytes"]:
                reasons.append("insufficient fresh finite cgroup headroom: " + row["path"])
    return reasons
