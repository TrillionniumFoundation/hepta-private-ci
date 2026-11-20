"""Local trusted archive adapter; all actual blob reads are bounded and recorded."""

import os
import re
import stat

from v2_common import policy, require, sha


class BoundedBlobRoot:
    def __init__(self, root):
        self.root = root
        self.reads = []
        self.total = 0
        limits = policy()["cost_limits"]
        self.byte_limit = (
            limits["runtime_bytes"] + limits["task_bytes"] + limits["diagnostic_bytes"]
        )
        self.call_limit = 2 * limits["total_files"] + 16

    def __truediv__(self, part):
        require(part == "blobs", "only original material blobs may be read")
        return _BlobDirectory(self)


class _BlobDirectory:
    def __init__(self, owner):
        self.owner = owner

    def __truediv__(self, digest):
        require(
            type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest),
            "invalid blob name",
        )
        return _Blob(self.owner, digest)


class _Blob:
    def __init__(self, owner, digest):
        self.owner, self.digest = owner, digest

    def read_bytes(self):
        owner = self.owner
        require(len(owner.reads) < owner.call_limit, "material read call limit")
        remaining = owner.byte_limit - owner.total
        path = owner.root / "blobs" / self.digest
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            require(
                stat.S_ISREG(info.st_mode) and info.st_size <= remaining,
                "material read byte limit",
            )
            raw = handle.read(remaining + 1)
        require(
            len(raw) <= remaining and sha(raw) == self.digest,
            "material read bytes changed",
        )
        owner.total += len(raw)
        owner.reads.append({"sha256": self.digest, "bytes": len(raw)})
        return raw
