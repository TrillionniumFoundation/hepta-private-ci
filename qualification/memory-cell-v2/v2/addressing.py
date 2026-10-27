"""Explicit, charged version addressing; values never enter this index.

As-of resolution is metadata processing, not temporal reasoning in parameters.
A latest tombstone refuses a current read while earlier as-of reads may resolve.
"""

from bisect import bisect_right
from datetime import datetime, timezone
import json
from pathlib import Path

from .encoder import canonical, sha


KINDS = ("semantic", "episodic", "procedural")
FIELDS = {"kind", "key", "revision", "timestamp", "deleted"}


def _time(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ValueError("timestamp must be a bounded ISO string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a time zone")
    return parsed.astimezone(timezone.utc)


def address_text(kind, key, revision):
    return f"Memory type {kind}. Key {key}. Revision {revision}."


class AddressIndex:
    """Only type, key, revision, timestamp and deletion metadata are retained."""

    def __init__(self, rows):
        if not isinstance(rows, (list, tuple)) or len(rows) > 65536:
            raise ValueError("address rows must be a bounded sequence")
        entries, identities, instants = [], set(), set()
        for original in rows:
            if not isinstance(original, dict) or set(original) != FIELDS:
                raise ValueError("address rows may contain metadata fields only")
            row = dict(original)
            if (
                row["kind"] not in KINDS
                or not isinstance(row["key"], str)
                or not 1 <= len(row["key"]) <= 16384
                or type(row["revision"]) is not int
                or not 1 <= row["revision"] <= 2**31
                or type(row["deleted"]) is not bool
            ):
                raise ValueError("invalid address metadata")
            stamp = _time(row["timestamp"])
            row["timestamp"] = stamp.isoformat()
            identity = (row["kind"], row["key"], row["revision"])
            instant = (row["kind"], row["key"], row["timestamp"])
            if identity in identities or instant in instants:
                raise ValueError("duplicate revision or ambiguous same-key timestamp")
            identities.add(identity)
            instants.add(instant)
            entries.append(row)
        self._entries = tuple(
            sorted(entries, key=lambda row: (row["kind"], row["key"], row["revision"]))
        )
        self._versions, self._times = {}, {}
        for row in self._entries:
            identity = row["kind"], row["key"]
            stamp = _time(row["timestamp"])
            if identity in self._times and stamp <= self._times[identity][-1]:
                raise ValueError("revision order contradicts timestamp order")
            self._times.setdefault(identity, []).append(stamp)
            self._versions.setdefault(identity, []).append(row)

    @classmethod
    def from_events(cls, events):
        return cls(
            [
                {
                    "kind": event.cell_type,
                    "key": event.key,
                    "revision": event.revision,
                    "timestamp": event.timestamp,
                    "deleted": event.deleted,
                }
                for event in events
            ]
        )

    @property
    def entries(self):
        return tuple(dict(row) for row in self._entries)

    def resolve(self, kind, key, as_of=None):
        if kind not in KINDS or not isinstance(key, str):
            return None
        identity = kind, key
        if identity not in self._versions:
            return None
        position = (
            len(self._versions[identity]) - 1
            if as_of is None
            else (bisect_right(self._times[identity], _time(as_of)) - 1)
        )
        if position < 0:
            return None
        row = self._versions[identity][position]
        return None if row["deleted"] else address_text(kind, key, row["revision"])

    def to_dict(self):
        payload = {
            "schema": "memory-cell-v2.address-index.v1",
            "entries": [dict(row) for row in self.entries],
        }
        return {**payload, "sha256": sha(canonical(payload))}

    @property
    def bytes(self):
        return len(canonical(self.to_dict())) + 1

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical(self.to_dict()) + b"\n")

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 2**20:
            raise ValueError("invalid address-index file")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate address-index field")
                result[key] = value
            return result

        payload = json.loads(path.read_bytes(), object_pairs_hook=unique)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema", "entries", "sha256"}
            or payload["schema"] != "memory-cell-v2.address-index.v1"
        ):
            raise ValueError("invalid address-index envelope")
        index = cls(payload["entries"])
        if index.to_dict() != payload:
            raise ValueError("address-index binding mismatch")
        return index
