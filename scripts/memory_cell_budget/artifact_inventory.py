"""Complete operational-file inventories; no filename-based cost exclusions."""

import hashlib
import os
from pathlib import Path
import stat

from budget_ledger import digest


KINDS = {
    "base",
    "source",
    "adapter",
    "router",
    "index",
    "owner",
    "recovery",
    "runtime",
    "evidence",
}


def measure(components):
    """Count all declared components, deduplicating physical hard links explicitly.

    An external shared base is still a component and is charged once per complete
    system. Content-identical files on different inodes remain separate storage.
    Callers must retain the component manifest, including any benchmark-only roots.
    """
    roots, names = [], set()
    for entry in components:
        if (
            set(entry) != {"name", "path", "kind", "private"}
            or entry["kind"] not in KINDS
        ):
            raise ValueError("complete named component declaration required")
        if entry["name"] in names or type(entry["private"]) is not bool:
            raise ValueError(
                "distinct component names and explicit private capacity required"
            )
        requested = Path(entry["path"])
        if requested.is_symlink() or not requested.exists():
            raise ValueError("real operational component required")
        path = requested.resolve()
        if any(
            path == old or path.is_relative_to(old) or old.is_relative_to(path)
            for old in roots
        ):
            raise ValueError("overlapping roots would conceal or double-count storage")
        roots.append(path)
        names.add(entry["name"])
    files, physical, private = [], {}, 0
    for entry, root in zip(components, roots):
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            before = path.lstat()
            if stat.S_ISLNK(before.st_mode):
                raise ValueError("operational inventories cannot skip symlink targets")
            if stat.S_ISDIR(before.st_mode):
                continue
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("regular operational files required")
            h = hashlib.sha256()
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
                after = os.fstat(stream.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if any(
                getattr(before, k) != getattr(after, k)
                or getattr(opened, k) != getattr(after, k)
                for k in fields
            ):
                raise ValueError("component changed during measurement")
            identity = (after.st_dev, after.st_ino)
            allocated = getattr(after, "st_blocks", 0) * 512
            if identity not in physical:
                physical[identity] = dict(logical=after.st_size, allocated=allocated)
            if entry["private"]:
                private += after.st_size
            files.append(
                dict(
                    component=entry["name"],
                    kind=entry["kind"],
                    private=entry["private"],
                    path=str(path.relative_to(root)) if root.is_dir() else path.name,
                    bytes=after.st_size,
                    allocated_bytes=allocated,
                    sha256=h.hexdigest(),
                )
            )
    result = dict(
        components=components,
        files=files,
        logical_bytes=sum(x["bytes"] for x in files),
        physical_payload_bytes=sum(x["logical"] for x in physical.values()),
        allocated_bytes=sum(x["allocated"] for x in physical.values()),
        private_bytes=private,
        physical_files=len(physical),
        file_entries=len(files),
        hash_read_bytes=sum(x["bytes"] for x in files),
        excludes_benchmark_harness_only_if_not_declared=True,
    )
    result["inventory_sha256"] = digest(result)
    return result


def storage_charge(before, after, elapsed_ns, *, retained_state_monotonic):
    """Conservative byte-time for a declared monotonic retention interval.

    Nonmonotonic temporary storage needs finer inventory events and is not silently
    called an exact measurement. Output carries that limitation for qualification.
    """
    if (
        type(elapsed_ns) is not int
        or elapsed_ns < 0
        or type(retained_state_monotonic) is not bool
    ):
        raise ValueError(
            "measured elapsed nanoseconds and explicit retention semantics required"
        )
    maximum = max(before["logical_bytes"], after["logical_bytes"])
    return dict(
        storage_byte_ns=maximum * elapsed_ns,
        method="endpoint-upper-charge"
        if retained_state_monotonic
        else "endpoint-only-estimate",
        complete_interval_accounting=retained_state_monotonic,
        exact_byte_time=False,
        before=before["inventory_sha256"],
        after=after["inventory_sha256"],
    )
