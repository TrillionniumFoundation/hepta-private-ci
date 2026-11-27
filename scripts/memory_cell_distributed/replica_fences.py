"""Independent persisted lower bounds detect an older restored replica DB.

The fence and the signing key must survive. Simultaneous rollback/loss of every
state, fence and external witness is outside this crash-recovery fault model.
"""

import fcntl
import os
from pathlib import Path
import secrets

from authority_contract import decode, digest, encode, fields, hex_value, integer, name


class ReplicaFences:
    def __init__(self, root, *, creation="existing"):
        self.root, self.path = Path(root), Path(root) / "head-fences.json"
        self.lock_path = self.root / "head-fences.lock"
        if self.path.is_symlink() or self.lock_path.is_symlink():
            raise ValueError("replica fences cannot be symlinked")
        if not self.path.exists():
            if creation != "genesis":
                raise ValueError("replica fences lost; explicit restore required")
            self._write({})
        self.load()

    def load(self):
        if self.path.stat().st_size > 64 * 1024:
            raise ValueError("replica fence byte bound")
        values = decode(self.path.read_bytes())
        if len(values) > 64:
            raise ValueError("replica fence scope bound")
        for scope, value in values.items():
            fields(value, ("sequence", "proposal_sha256"))
            if (
                not name(scope)
                or not integer(value["sequence"])
                or value["sequence"] == 0
                or not hex_value(value["proposal_sha256"])
            ):
                raise ValueError("invalid persisted replica fence")
        return values

    @staticmethod
    def _check(floor, certificate):
        if floor is None:
            return
        if certificate is None:
            raise ValueError("committed replica state disappeared")
        sequence = certificate["proposal"]["state"]["sequence"]
        if sequence < floor["sequence"] or (
            sequence == floor["sequence"]
            and digest(certificate["proposal"]) != floor["proposal_sha256"]
        ):
            raise ValueError("replica database rolled back below durable fence")

    def check(self, scope, certificate):
        self._check(self.load().get(scope), certificate)

    def advance(self, certificate):
        state = certificate["proposal"]["state"]
        with self.lock_path.open("ab") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            values = self.load()
            self._check(values.get(state["scope"]), certificate)
            values[state["scope"]] = dict(
                sequence=state["sequence"],
                proposal_sha256=digest(certificate["proposal"]),
            )
            self._write(values)

    def _write(self, values):
        temporary = self.root / (".fences-" + secrets.token_hex(12))
        try:
            with temporary.open("xb") as stream:
                stream.write(encode(values))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)
