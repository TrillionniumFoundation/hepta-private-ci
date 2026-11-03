"""A fail-closed publication owner for versioned numeric memory artifacts.

The writer may use the source ledger. The reader loads parameters, optional
explicit residuals, and value-free addresses only. A separately persisted
monotone witness rejects restoration of an older active pointer. This is a
single-writer research control plane, not a distributed consensus service.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import time

import numpy as np

from .codec import decode_factor, encode_factor
from .factor_cell import FactorBank, canonical_matrix


HEX = re.compile(r"[0-9a-f]{64}")
SCOPE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def canonical(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_regular(path, limit=128_000_000):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("invalid or oversized memory state file")
    return path.read_bytes()


def atomic_write(path, payload):
    """Durably replace one pointer; witness-first publication fails closed."""
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("symlink at publication boundary")
    temporary = path.with_name(path.name + ".pending")
    if temporary.is_symlink():
        raise ValueError("symlink at temporary publication boundary")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare_version(
    root, *, scope, generation, years, matrix, mask=None, rank=4, seed=0
):
    """Clean-fit a candidate from exactly the supplied valid source frontier."""
    if not SCOPE.fullmatch(scope) or type(generation) is not int or generation < 1:
        raise ValueError("invalid scope or generation")
    values, available = canonical_matrix(matrix, mask)
    if (
        years != sorted(set(years))
        or len(years) != len(values)
        or any(type(y) is not int for y in years)
    ):
        raise ValueError("invalid value-free address index")
    started = time.perf_counter()
    directory = Path(root) / "versions" / str(generation)
    directory.mkdir(parents=True, exist_ok=False)
    bank, fitting = FactorBank.fit(
        values, mask=available, ranks=[min(rank, *values.shape)], seed=seed
    )
    model = bank.save(directory / "memory.factor")
    residual, codec = encode_factor(
        bank, values, model_storage="external", method="best"
    )
    (directory / "residual.codec").write_bytes(residual)
    addresses = canonical({"years": years, "columns": values.shape[1]})
    (directory / "addresses.json").write_bytes(addresses)
    frontier = sha(
        values.tobytes()
        + np.packbits(available.ravel(), bitorder="little").tobytes()
        + addresses
    )
    manifest = {
        "schema": "memory-cell-v3.numeric-version.v1",
        "scope": scope,
        "generation": generation,
        "frontier_sha256": frontier,
        "model_sha256": model["sha256"],
        "model_bytes": model["bytes"],
        "residual_sha256": sha(residual),
        "residual_bytes": len(residual),
        "addresses_sha256": sha(addresses),
        "addresses_bytes": len(addresses),
        "training": "clean fit from valid source frontier; no predecessor weights",
    }
    encoded = canonical(manifest)
    (directory / "manifest.json").write_bytes(encoded)
    # The witness must never commit a version whose contents were only in the
    # operating system's write cache. Persist files before their directories.
    for file in directory.iterdir():
        with file.open("rb") as stream:
            os.fsync(stream.fileno())
    for parent in (directory, directory.parent, directory.parent.parent):
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return manifest, {
        "fitting": fitting,
        "codec": codec,
        "version_bytes": sum(p.stat().st_size for p in directory.iterdir()),
        "prepare_seconds": time.perf_counter() - started,
        "manifest_sha256": sha(encoded),
        "valid_values": int(available.sum()),
        "masked_values": int((~available).sum()),
        "clean_training_frontier_sha256": frontier,
    }


def load_parameters(manifest, payloads):
    """Parse the same bytes that were checked, without reopening the address file."""
    bank = FactorBank.from_bytes(
        payloads["model"], expected_sha256=manifest["model_sha256"]
    )
    addresses = json.loads(payloads["addresses"])
    years = addresses.get("years")
    if (
        set(addresses) != {"years", "columns"}
        or not isinstance(years, list)
        or any(type(year) is not int or not 1 <= year <= 9999 for year in years)
        or years != sorted(set(years))
        or type(addresses["columns"]) is not int
        or bank.shape != (len(years), addresses["columns"])
    ):
        raise ValueError("address index and model shape differ")
    return bank, tuple(years)


class FactorOwner:
    """Admission checks precede reads and every graph operation.

    The external witness must be protected from rollback by the deployment.
    This implementation assumes one writer, checks local durability, and makes
    no claim that an attacker who controls both directories cannot roll them
    back together. Historical artifacts remain auditable and are not unlearned.
    """

    def __init__(self, root, witness, *, scope):
        self.root, self.witness = Path(root), Path(witness)
        if (
            not SCOPE.fullmatch(scope)
            or self.root.is_symlink()
            or self.witness.is_symlink()
        ):
            raise ValueError("invalid owner location or scope")
        self.scope = scope
        self.root.mkdir(parents=True, exist_ok=True)
        self.witness.parent.mkdir(parents=True, exist_ok=True)
        self._active, self._manifest, self._bank, self._years = None, None, None, None
        self._exact = None
        self.parameter_read_calls = 0
        self.exact_read_calls = 0
        self.admission_calls = 0

    def _version(self, generation, expected_manifest=None, *, validate_replay=False):
        directory = self.root / "versions" / str(generation)
        if directory.is_symlink() or (self.root / "versions").is_symlink():
            raise ValueError("symlink in version inventory")
        raw = read_regular(directory / "manifest.json", 65536)
        if expected_manifest is not None and sha(raw) != expected_manifest:
            raise ValueError("version manifest binding differs")
        manifest = json.loads(raw)
        required = {
            "schema",
            "scope",
            "generation",
            "frontier_sha256",
            "model_sha256",
            "model_bytes",
            "residual_sha256",
            "residual_bytes",
            "addresses_sha256",
            "addresses_bytes",
            "training",
        }
        if (
            set(manifest) != required
            or manifest["schema"] != "memory-cell-v3.numeric-version.v1"
            or manifest["scope"] != self.scope
            or manifest["generation"] != generation
        ):
            raise ValueError("invalid version manifest contract")
        for field in (
            "frontier_sha256",
            "model_sha256",
            "residual_sha256",
            "addresses_sha256",
        ):
            if not isinstance(manifest[field], str) or not HEX.fullmatch(
                manifest[field]
            ):
                raise ValueError("invalid version digest")
        components = [("memory.factor", "model"), ("addresses.json", "addresses")]
        if validate_replay:
            components.append(("residual.codec", "residual"))
        payloads = {}
        for filename, prefix in components:
            content = read_regular(directory / filename)
            if (
                len(content) != manifest[prefix + "_bytes"]
                or sha(content) != manifest[prefix + "_sha256"]
            ):
                raise ValueError("version artifact bytes differ")
            payloads[prefix] = content
        if validate_replay:
            bank, _ = load_parameters(manifest, payloads)
            matrix, mask = decode_factor(
                payloads["residual"],
                model=bank,
                expected_sha256=manifest["residual_sha256"],
            )
            frontier = sha(
                matrix.tobytes()
                + np.packbits(mask.ravel(), bitorder="little").tobytes()
                + payloads["addresses"]
            )
            if frontier != manifest["frontier_sha256"]:
                raise ValueError(
                    "candidate replay frontier differs from publication commitment"
                )
        return manifest, raw, payloads

    def recover(self):
        witness = json.loads(read_regular(self.witness, 65536))
        if (
            set(witness) != {"schema", "scope", "generation", "active_sha256"}
            or witness["schema"] != "memory-cell-v3.witness.v1"
            or witness["scope"] != self.scope
            or type(witness["generation"]) is not int
            or witness["generation"] < 1
            or not isinstance(witness["active_sha256"], str)
            or not HEX.fullmatch(witness["active_sha256"])
        ):
            raise ValueError("invalid durable witness")
        intent_path = self.root / "publication-intent.json"
        if intent_path.exists():
            intent = json.loads(read_regular(intent_path, 65536))
            if (
                set(intent) != {"schema", "pointer", "predecessor_generation"}
                or intent["schema"] != "memory-cell-v3.publication-intent.v1"
            ):
                raise ValueError("invalid durable publication intent")
            pointer = intent["pointer"]
            if (
                not isinstance(pointer, dict)
                or set(pointer) != {"schema", "scope", "generation", "manifest_sha256"}
                or pointer["schema"] != "memory-cell-v3.active.v1"
                or pointer["scope"] != self.scope
                or type(pointer["generation"]) is not int
                or type(intent["predecessor_generation"]) is not int
                or pointer["generation"] != intent["predecessor_generation"] + 1
                or not isinstance(pointer["manifest_sha256"], str)
                or not HEX.fullmatch(pointer["manifest_sha256"])
            ):
                raise ValueError("invalid pending version pointer")
            encoded = canonical(pointer)
            if witness["generation"] == pointer["generation"]:
                if witness["active_sha256"] != sha(encoded):
                    raise ValueError(
                        "pending publication differs from witness commitment"
                    )
                self._version(
                    pointer["generation"],
                    pointer["manifest_sha256"],
                    validate_replay=True,
                )
                atomic_write(self.root / "active.json", encoded)
                intent_path.unlink()
                descriptor = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            elif witness["generation"] != intent["predecessor_generation"]:
                raise ValueError("publication intent has an unrelated predecessor")
        active_raw = read_regular(self.root / "active.json", 65536)
        active = json.loads(active_raw)
        if (
            set(active) != {"schema", "scope", "generation", "manifest_sha256"}
            or active["schema"] != "memory-cell-v3.active.v1"
            or active["scope"] != self.scope
        ):
            raise ValueError("invalid active pointer")
        generation = active["generation"]
        if (
            type(generation) is not int
            or generation < 1
            or not isinstance(active["manifest_sha256"], str)
            or not HEX.fullmatch(active["manifest_sha256"])
        ):
            raise ValueError("invalid active generation")
        if witness != {
            "schema": "memory-cell-v3.witness.v1",
            "scope": self.scope,
            "generation": generation,
            "active_sha256": sha(active_raw),
        }:
            raise ValueError("active pointer differs from monotone witness")
        manifest, _, payloads = self._version(generation, active["manifest_sha256"])
        if active != self._active:
            bank, years = load_parameters(manifest, payloads)
            self._active, self._manifest, self._bank, self._years = (
                active,
                manifest,
                bank,
                years,
            )
            self._exact = None
        return dict(manifest)

    def publish(self, generation, *, expected_generation):
        if (
            type(generation) is not int
            or type(expected_generation) is not int
            or generation != expected_generation + 1
        ):
            raise ValueError("publication generation must advance exactly once")
        current = self.root / "active.json"
        if current.exists() or self.witness.exists():
            existing = self.recover()
            if existing["generation"] == generation:
                return existing
            if existing["generation"] != expected_generation:
                raise ValueError("publication predecessor differs")
        elif expected_generation != 0:
            raise ValueError("publication predecessor is missing")
        manifest, raw, _ = self._version(generation, validate_replay=True)
        pointer_value = {
            "schema": "memory-cell-v3.active.v1",
            "scope": self.scope,
            "generation": generation,
            "manifest_sha256": sha(raw),
        }
        pointer = canonical(pointer_value)
        witness = canonical(
            {
                "schema": "memory-cell-v3.witness.v1",
                "scope": self.scope,
                "generation": generation,
                "active_sha256": sha(pointer),
            }
        )
        atomic_write(
            self.root / "publication-intent.json",
            canonical(
                {
                    "schema": "memory-cell-v3.publication-intent.v1",
                    "pointer": pointer_value,
                    "predecessor_generation": expected_generation,
                }
            ),
        )
        atomic_write(self.witness, witness)
        atomic_write(current, pointer)
        self.recover()
        return manifest

    def admission_check(self, generation, operation, artifact_binding, frontier_digest):
        manifest = self.recover()
        self.admission_calls += 1
        if (
            generation != manifest["generation"]
            or artifact_binding != manifest["model_sha256"]
            or frontier_digest != manifest["frontier_sha256"]
        ):
            raise ValueError("stale generation, artifact, or source frontier")
        if not isinstance(operation, str) or not operation:
            raise ValueError("missing operation identity")

    def read(self, coordinates, *, generation, mode="parameters"):
        manifest = self.recover()
        self.admission_check(
            generation, "read", manifest["model_sha256"], manifest["frontier_sha256"]
        )
        if mode not in {"parameters", "lossless_codec"}:
            raise ValueError("unknown memory read mode")
        mapping = {year: row for row, year in enumerate(self._years)}
        positions, rows, columns = [], [], []
        output = [None] * len(coordinates)
        for index, (year, month) in enumerate(coordinates):
            if type(year) is not int or type(month) is not int:
                raise ValueError("address requires integer year and month")
            if year in mapping and 1 <= month <= self._bank.shape[1]:
                positions.append(index)
                rows.append(mapping[year])
                columns.append(month - 1)
        if positions:
            if mode == "parameters":
                values = self._bank.read(np.asarray(rows), np.asarray(columns))
                self.parameter_read_calls += 1
            else:
                if self._exact is None:
                    raw = read_regular(
                        self.root / "versions" / str(generation) / "residual.codec"
                    )
                    self._exact = decode_factor(
                        raw,
                        model=self._bank,
                        expected_sha256=manifest["residual_sha256"],
                    )
                matrix, mask = self._exact
                values = [
                    int(matrix[r, c]) if mask[r, c] else None
                    for r, c in zip(rows, columns, strict=True)
                ]
                self.exact_read_calls += 1
            for position, value in zip(positions, values, strict=True):
                output[position] = value
        return output
