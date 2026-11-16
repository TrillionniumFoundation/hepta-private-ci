"""Pinned key/provenance admission index for research-only parameter memory.

This catalog contains no answer values. It does not prove a model knows when to
abstain, authenticate source authority, or grant production acceptance. The host
retains its independent SHA pin and supplies the owner's trusted source view.
"""

import hashlib
import json
from pathlib import Path
import re
import stat


MAX_BYTES = 128 * 1024
MAX_ENTRIES = 512
SCHEMA = "hepta.parametric-memory.metadata-catalog.v1"


def _identifier(value, maximum):
    return (
        type(value) is str
        and 1 <= len(value) <= maximum
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value) is not None
    )


def _scope(value):
    return (
        type(value) is str
        and 1 <= len(value) <= 128
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", value) is not None
    )


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate catalog field")
        result[key] = value
    return result


def _binding(active, catalog, source=None):
    if (
        active is None
        or active.scope != catalog["scope"]
        or active.cell_id != catalog["cell_id"]
        or active.manifest_sha256 != catalog["manifest_sha256"]
        or (source is not None and source not in active.roots)
    ):
        raise ValueError(
            "catalog is stale or not bound to active checkpoint provenance"
        )


class MetadataCatalog:
    """Read typed keys through an independently pinned immutable metadata file."""

    def __init__(self, path, expected_sha256):
        if not _digest(expected_sha256):
            raise ValueError("independently retained catalog SHA256 required")
        self.path = Path(path).absolute()
        self.expected_sha256 = expected_sha256
        self._read()

    def _read(self):
        info = self.path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not 0 < info.st_size <= MAX_BYTES
        ):
            raise ValueError("bounded regular catalog file required")
        with self.path.open("rb") as stream:
            payload = stream.read(MAX_BYTES + 1)
        if (
            len(payload) != info.st_size
            or hashlib.sha256(payload).hexdigest() != self.expected_sha256
        ):
            raise ValueError("catalog bytes differ from retained SHA256")
        catalog = json.loads(payload, object_pairs_hook=_unique)
        fields = {
            "schema",
            "scope",
            "cell_id",
            "manifest_sha256",
            "entries",
            "production_accepted",
        }
        if (
            type(catalog) is not dict
            or set(catalog) != fields
            or catalog["schema"] != SCHEMA
            or not _scope(catalog["scope"])
            or not _scope(catalog["cell_id"])
            or not _digest(catalog["manifest_sha256"])
            or catalog["production_accepted"] is not False
            or type(catalog["entries"]) is not list
            or len(catalog["entries"]) > MAX_ENTRIES
        ):
            raise ValueError("unregistered or unbounded metadata-only catalog")
        keys = set()
        for entry in catalog["entries"]:
            if (
                type(entry) is not dict
                or set(entry) != {"entity", "relation", "source_digest"}
                or not _identifier(entry["entity"], 64)
                or not _identifier(entry["relation"], 32)
                or not _digest(entry["source_digest"])
            ):
                raise ValueError(
                    "catalog entries may contain only bounded keys and provenance"
                )
            key = entry["entity"], entry["relation"]
            if key in keys:
                raise ValueError("duplicate catalog entity/relation key")
            keys.add(key)
        return catalog

    def read(self, owner, *, entity, relation, provider, callback):
        """Unknown keys abstain without inference; known keys keep raw responses."""
        if (
            not _identifier(entity, 64)
            or not _identifier(relation, 32)
            or not callable(callback)
        ):
            raise ValueError(
                "typed bounded entity/relation and inference callback required"
            )
        catalog = self._read()
        active = owner.current(catalog["cell_id"], catalog["scope"])
        _binding(active, catalog)
        entry = next(
            (
                e
                for e in catalog["entries"]
                if (e["entity"], e["relation"]) == (entity, relation)
            ),
            None,
        )
        if entry is None:
            self._read()
            if owner.current(catalog["cell_id"], catalog["scope"]) != active:
                raise ValueError("active version changed during catalog admission")
            return {"status": "unknown", "response": "unknown"}
        question = f"Which {relation} did we assign to {entity}?"

        def invoke(selected):
            _binding(selected, catalog, entry["source_digest"])
            self._read()
            return callback(selected, question)

        response = owner.invoke(
            catalog["cell_id"],
            catalog["scope"],
            provider,
            invoke,
            query_roots=(entry["source_digest"],),
        )
        self._read()
        return {"status": "known", "response": response}
