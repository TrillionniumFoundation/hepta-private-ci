"""Identity-bound Linux RSS observations for owned process trees.

Numeric Popen PIDs are never used as mounted-proc PIDs. A full-family result
requires descendant enumeration; an explicitly registered set is a different
measurement and never silently promoted to full-family coverage.
"""

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import time


class Unavailable(RuntimeError):
    """Required process identity or inventory could not be established."""


@dataclass(frozen=True)
class Identity:
    proc_pid: int
    namespace_pids: tuple
    start_ticks: int
    parent_proc_pid: int

    def record(self):
        return asdict(self)


def parse_stat(raw):
    left, right = raw.find("("), raw.rfind(")")
    if left < 1 or right <= left:
        raise Unavailable("Malformed proc stat command field")
    try:
        pid = int(raw[:left].strip())
        fields = raw[right + 1:].split()
        state = fields[0]
        ppid, start_ticks = int(fields[1]), int(fields[19])
    except (ValueError, IndexError) as error:
        raise Unavailable("Malformed proc stat identity fields") from error
    if pid < 1 or ppid < 0 or start_ticks < 0 or state in {"Z", "X", "x"}:
        raise Unavailable("Process is not a live measurable identity")
    return pid, ppid, start_ticks


class Observer:
    def __init__(self, proc_root="/proc", page_bytes=None, max_processes=64):
        self.proc = Path(proc_root)
        self.page_bytes = int(page_bytes or os.sysconf("SC_PAGE_SIZE"))
        self.max_processes = int(max_processes)
        if self.page_bytes <= 0 or self.max_processes < 1:
            raise ValueError("Invalid observer bounds")

    def _read(self, path):
        try:
            return path.read_text()
        except (OSError, UnicodeError) as error:
            raise Unavailable(f"Cannot read required owned-process metadata: {path}: {error}") from error

    def identity(self, proc_pid):
        proc_pid = int(proc_pid)
        if proc_pid < 1:
            raise Unavailable("Nonpositive mounted-proc PID")
        directory = self.proc / str(proc_pid)
        before = parse_stat(self._read(directory / "stat"))
        fields = {}
        for line in self._read(directory / "status").splitlines():
            key, separator, value = line.partition(":")
            if separator:
                fields[key] = value.strip()
        try:
            chain = tuple(int(x) for x in fields["NSpid"].split())
            status_pid, status_ppid = int(fields["Pid"]), int(fields["PPid"])
        except (KeyError, ValueError) as error:
            raise Unavailable("Required NSpid/Pid/PPid mapping unavailable") from error
        after = parse_stat(self._read(directory / "stat"))
        if (before != after or before[0] != proc_pid or status_pid != proc_pid
                or status_ppid != before[1] or not chain or chain[0] != proc_pid
                or any(x < 1 for x in chain)):
            raise Unavailable("Process identity changed or namespace mapping disagrees")
        return Identity(proc_pid, chain, before[2], before[1])

    def own_identity(self, expected_namespace_pid=None):
        try:
            target = os.readlink(self.proc / "self")
            if not target.isdecimal():
                raise Unavailable("proc/self has no numeric mounted-proc identity")
            identity = self.identity(int(target))
        except OSError as error:
            raise Unavailable("proc/self identity unavailable") from error
        expected = os.getpid() if expected_namespace_pid is None else int(expected_namespace_pid)
        self_stat = parse_stat(self._read(self.proc / "self" / "stat"))
        if identity.namespace_pids[-1] != expected or self_stat != (
                identity.proc_pid, identity.parent_proc_pid, identity.start_ticks):
            raise Unavailable("proc/self does not bind the current namespace PID")
        return identity

    def require_same(self, expected):
        actual = self.identity(expected.proc_pid)
        if actual != expected:
            raise Unavailable("Owned process disappeared, was reparented, or its PID was reused")
        return actual

    def register_owned_child(self, parent, child_pid_seen_by_parent, trusted_handshake):
        """Bind a child handshake received over the caller's own spawn channel.

        The caller supplies its real Popen/fork result, not a PID discovered by a
        system-wide scan. Handshakes are not an authentication protocol for an
        untrusted remote process.
        """
        self.require_same(parent)
        try:
            claimed = Identity(int(trusted_handshake["proc_pid"]),
                               tuple(int(x) for x in trusted_handshake["namespace_pids"]),
                               int(trusted_handshake["start_ticks"]),
                               int(trusted_handshake["parent_proc_pid"]))
        except (KeyError, ValueError, TypeError) as error:
            raise Unavailable("Invalid owned-child handshake") from error
        depth = len(parent.namespace_pids) - 1
        if (len(claimed.namespace_pids) <= depth
                or claimed.namespace_pids[depth] != int(child_pid_seen_by_parent)
                or claimed.parent_proc_pid != parent.proc_pid):
            raise Unavailable("Child handshake does not bind the observed spawn edge")
        self.require_same(claimed)
        self.require_same(parent)
        return claimed

    def read_rss(self, identity):
        self.require_same(identity)
        values = self._read(self.proc / str(identity.proc_pid) / "statm").split()
        try:
            resident_pages = int(values[1])
        except (ValueError, IndexError) as error:
            raise Unavailable("Malformed resident page count") from error
        if resident_pages < 0:
            raise Unavailable("Negative resident page count")
        self.require_same(identity)
        return resident_pages * self.page_bytes

    def children(self, parent):
        self.require_same(parent)
        task_root = self.proc / str(parent.proc_pid) / "task"
        try:
            tasks = sorted(task_root.iterdir(), key=lambda x: int(x.name))
        except (OSError, ValueError) as error:
            raise Unavailable("Owned-process thread inventory unavailable") from error
        if not tasks or len(tasks) > 4096:
            raise Unavailable("Invalid or excessive owned thread inventory")
        result = set()
        for task in tasks:
            try:
                values = [int(x) for x in self._read(task / "children").split()]
            except ValueError as error:
                raise Unavailable("Malformed child inventory") from error
            if any(x < 1 for x in values):
                raise Unavailable("Invalid child PID")
            result.update(values)
        self.require_same(parent)
        return sorted(result)

    def discover_family(self, root):
        self.require_same(root)
        members, pending = {root.proc_pid: root}, [root]
        while pending:
            parent = pending.pop()
            for pid in self.children(parent):
                child = self.identity(pid)
                if child.parent_proc_pid != parent.proc_pid:
                    raise Unavailable("Observed descendant edge changed")
                if pid in members:
                    if members[pid] != child:
                        raise Unavailable("Descendant PID identity collision")
                    continue
                if len(members) >= self.max_processes:
                    raise Unavailable("Process inventory bound exceeded")
                members[pid] = child
                pending.append(child)
        self.require_same(root)
        return sorted(members.values(), key=lambda x: x.proc_pid)

    def _sample(self, identities, scope):
        began = time.monotonic_ns()
        try:
            if not identities or len(identities) > self.max_processes:
                raise Unavailable("Invalid registered inventory size")
            if len({x.proc_pid for x in identities}) != len(identities):
                raise Unavailable("Duplicate registered process PID")
            members = [{"identity": x.record(), "rss_bytes": self.read_rss(x)} for x in identities]
            return {"available": True, "rss_sum_bytes": sum(x["rss_bytes"] for x in members),
                    "members": members, "scope": scope, "sample_begin_monotonic_ns": began,
                    "sample_end_monotonic_ns": time.monotonic_ns(),
                    "physical_unique_memory": False, "atomic_snapshot": False}
        except Unavailable as error:
            return {"available": False, "rss_sum_bytes": None, "members": None,
                    "scope": scope, "reason": str(error), "sample_begin_monotonic_ns": began,
                    "sample_end_monotonic_ns": time.monotonic_ns()}

    def sample_registered_set(self, root, identities):
        """Sample an explicit owned set; unknown descendants remain unknown."""
        try:
            members = {x.proc_pid: x for x in identities}
            if len(members) != len(identities) or members.get(root.proc_pid) != root:
                raise Unavailable("Registered set has duplicates or no matching root")
            for member in identities:
                seen = set()
                cursor = member
                while cursor != root:
                    if cursor.proc_pid in seen or cursor.parent_proc_pid not in members:
                        raise Unavailable("Registered set is not a rooted owned tree")
                    seen.add(cursor.proc_pid)
                    cursor = members[cursor.parent_proc_pid]
            result = self._sample(identities, "registered_owned_process_set")
        except Unavailable as error:
            result = {"available": False, "rss_sum_bytes": None, "members": None,
                      "scope": "registered_owned_process_set", "reason": str(error)}
        result["full_descendant_coverage"] = False
        return result

    def sample_family(self, root):
        began = time.monotonic_ns()
        try:
            members = self.discover_family(root)
            result = self._sample(members, "enumerated_owned_process_family")
            if not result["available"]:
                return result
            if self.discover_family(root) != members:
                raise Unavailable("Family membership changed during sampling")
            result["full_descendant_coverage"] = True
            result["inventory_begin_monotonic_ns"] = began
            result["inventory_end_monotonic_ns"] = time.monotonic_ns()
            return result
        except Unavailable as error:
            return {"available": False, "rss_sum_bytes": None, "members": None,
                    "scope": "enumerated_owned_process_family", "full_descendant_coverage": False,
                    "reason": str(error), "inventory_begin_monotonic_ns": began,
                    "inventory_end_monotonic_ns": time.monotonic_ns()}
