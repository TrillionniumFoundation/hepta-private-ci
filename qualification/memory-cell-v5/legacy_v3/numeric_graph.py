"""Value-free addressing and supplied arithmetic capabilities for learned layouts.

The parameter reader owns only a reloaded FactorBank and charged address metadata.
Targets and the exact-value comparator live outside inference. Calendar navigation
and arithmetic are supplied programs; this experiment learns their composition.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re

import numpy as np

from .factor_cell import FactorBank
from .learned_graph import GraphExecutor, GraphQuery, OperationSpec, TypedValue
from .semantic_router import canonical, digest


INTENTS = ("at", "previous", "change", "mean3", "range3", "peak3")
SERIES_NAMES = {
    "co2": "Mauna Loa atmospheric carbon dioxide",
    "temperature": "global surface temperature anomaly",
    "sunspots": "international sunspot number",
    "unemployment": "United States unemployment rate",
}

# Opaque operation identities: the optimizer receives terminal rewards, not a
# lexical similarity between an intent label and a privileged operation name.
SPECS = (
    OperationSpec("c01", "address", "number", "semantic"),
    OperationSpec("c02", "address", "address", "episodic"),
    OperationSpec("c03", "address", "addresses", "episodic"),
    OperationSpec("c04", "address", "addresses", "episodic"),
    OperationSpec("c05", "addresses", "vector", "semantic"),
    OperationSpec("c06", "vector", "number", "procedural"),
    OperationSpec("c07", "vector", "number", "procedural"),
    OperationSpec("c08", "vector", "number", "procedural"),
    OperationSpec("c09", "vector", "number", "procedural"),
    OperationSpec("c10", "vector", "number", "procedural"),
    OperationSpec("c11", "vector", "number", "procedural"),
)

# This privileged planner is an explicitly supplied comparator. Training does
# not consume it; only the terminal numeric and source-coordinate targets.
EXACT_PLANS = {
    "at": ("c01",),
    "previous": ("c02", "c01"),
    "change": ("c03", "c05", "c07"),
    "mean3": ("c04", "c05", "c06"),
    "range3": ("c04", "c05", "c08"),
    "peak3": ("c04", "c05", "c09"),
}


def shift_month(address, offset):
    year, month = address
    serial = int(year) * 12 + int(month) - 1 + offset
    return (serial // 12, serial % 12 + 1)


def coordinate_id(domain, address):
    return f"{domain}:{address[0]:04d}-{address[1]:02d}"


def valid_source(source):
    years = source["years"]
    values = np.asarray(source["values"])
    if (
        source["domain"] not in SERIES_NAMES
        or source["fields"] != list(range(1, 13))
        or not years
        or any(type(y) is not int or not 1 <= y <= 9999 for y in years)
        or years != sorted(set(years))
        or values.shape != (len(years), 12)
        or values.dtype.kind not in "iu"
        or type(source["scale"]) is not int
        or source["scale"] <= 0
    ):
        raise ValueError("invalid numeric graph source")
    return values


@dataclass(frozen=True)
class ParameterReader:
    """Loaded parameters plus value-free routing metadata; no residual repair."""

    bank: FactorBank
    domain: str
    years: tuple[int, ...]
    scale: int
    artifact_sha256: str
    metadata_sha256: str

    def read(self, coordinates):
        rows = {year: index for index, year in enumerate(self.years)}
        positions, row_ids, column_ids = [], [], []
        output = [None] * len(coordinates)
        for index, (year, month) in enumerate(coordinates):
            if type(year) is not int or type(month) is not int:
                raise ValueError("calendar addresses must be integers")
            if year in rows and 1 <= month <= 12:
                positions.append(index)
                row_ids.append(rows[year])
                column_ids.append(month - 1)
        if positions:
            values = self.bank.read(np.asarray(row_ids), np.asarray(column_ids))
            for index, value in zip(positions, values, strict=True):
                output[index] = value
        return output

    @classmethod
    def load(cls, directory, *, artifact_sha256, metadata_sha256):
        path = Path(directory)
        metadata_file = path / "addresses.json"
        if metadata_file.is_symlink() or metadata_file.stat().st_size > 1048576:
            raise ValueError("invalid numeric address metadata")
        raw = metadata_file.read_bytes()
        if digest(raw) != metadata_sha256:
            raise ValueError("numeric address metadata digest differs")
        metadata = json.loads(raw)
        if set(metadata) != {
            "schema",
            "domain",
            "years",
            "scale",
            "unit",
            "artifact_sha256",
        }:
            raise ValueError("numeric address metadata inventory differs")
        if (
            metadata["schema"] != "memory-cell-v3.numeric-addresses.v1"
            or metadata["artifact_sha256"] != artifact_sha256
        ):
            raise ValueError("numeric artifact binding differs")
        years = metadata["years"]
        if (
            metadata["domain"] not in SERIES_NAMES
            or years != sorted(set(years))
            or any(type(y) is not int or not 1 <= y <= 9999 for y in years)
            or type(metadata["scale"]) is not int
            or metadata["scale"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256)
        ):
            raise ValueError("invalid numeric address contract")
        bank = FactorBank.load(path / "memory.factor", expected_sha256=artifact_sha256)
        if bank.shape != (len(years), 12):
            raise ValueError("numeric address shape differs from model")
        return cls(
            bank,
            metadata["domain"],
            tuple(years),
            metadata["scale"],
            artifact_sha256,
            metadata_sha256,
        )


def write_memory(source, directory, *, rank, seed):
    values = valid_source(source)
    bank, training = FactorBank.fit(values, ranks=[rank], seed=seed)
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=False)
    artifact = bank.save(path / "memory.factor")
    metadata = {
        "schema": "memory-cell-v3.numeric-addresses.v1",
        "domain": source["domain"],
        "years": source["years"],
        "scale": source["scale"],
        "unit": source["unit"],
        "artifact_sha256": artifact["sha256"],
    }
    encoded = canonical(metadata) + b"\n"
    (path / "addresses.json").write_bytes(encoded)
    loaded = ParameterReader.load(
        path, artifact_sha256=artifact["sha256"], metadata_sha256=digest(encoded)
    )
    if loaded.bank.to_bytes() != bank.to_bytes():
        raise AssertionError("numeric model save/load changed parameters")
    return loaded, {
        "training": training,
        "artifact": artifact,
        "metadata_sha256": digest(encoded),
        "address_metadata_bytes": len(encoded),
        "deployed_bytes": len(encoded) + artifact["bytes"],
        "source_json_sha256": digest(canonical(source)),
        "save_load_parity": True,
        "inference_values_from": "saved-and-reloaded-integer-factor-parameters",
        "residual_correction": False,
        "raw_target_cache": False,
    }


def exact_reader(source):
    """Explicit raw-value baseline; never passed to the parameter-only arm."""
    values = valid_source(source)
    rows = {year: index for index, year in enumerate(source["years"])}

    def read(coordinates):
        return [
            int(values[rows[year], month - 1])
            if year in rows and 1 <= month <= 12
            else None
            for year, month in coordinates
        ]

    return read


def numeric_executor(
    domain,
    read_values,
    *,
    scope="numeric-study",
    generation=1,
    admission_check=None,
    artifact_bindings=None,
    source_frontier_digest=None,
):
    def support(coordinates):
        return tuple(coordinate_id(domain, address) for address in coordinates)

    def read_one(value, query):
        number = read_values([tuple(value.value)])[0]
        return (
            None
            if number is None
            else TypedValue("number", number, support([value.value]))
        )

    def previous(value, query):
        return TypedValue("address", shift_month(value.value, -1))

    def pair(value, query):
        return TypedValue(
            "addresses", [shift_month(value.value, -1), tuple(value.value)]
        )

    def window(value, query):
        return TypedValue(
            "addresses", [shift_month(value.value, i) for i in (-2, -1, 0)]
        )

    def read_many(value, query):
        numbers = read_values([tuple(x) for x in value.value])
        if any(x is None for x in numbers):
            return None
        return TypedValue("vector", numbers, support(value.value))

    def reduce(function):
        def run(value, query):
            return TypedValue("number", function(value.value), value.support)

        return run

    callbacks = {
        "c01": read_one,
        "c02": previous,
        "c03": pair,
        "c04": window,
        "c05": read_many,
        "c06": reduce(lambda x: sum(x) / len(x)),
        "c07": reduce(lambda x: x[-1] - x[0]),
        "c08": reduce(lambda x: max(x) - min(x)),
        "c09": reduce(max),
        "c10": reduce(min),
        "c11": reduce(sum),
    }

    def bind_handle(callback):
        def run(value, query):
            if query.handle != domain:
                raise ValueError("numeric handle belongs to another source")
            coordinates = (
                [value.value]
                if value.kind == "address"
                else value.value
                if value.kind == "addresses"
                else []
            )
            for address in coordinates:
                if (
                    not isinstance(address, (list, tuple))
                    or len(address) != 2
                    or any(type(x) is not int for x in address)
                    or not 1 <= address[0] <= 9999
                    or not 1 <= address[1] <= 12
                ):
                    raise ValueError("invalid calendar address")
            return callback(value, query)

        return run

    callbacks = {name: bind_handle(callback) for name, callback in callbacks.items()}
    return GraphExecutor(
        SPECS,
        callbacks,
        scope=scope,
        generation=generation,
        admission_check=admission_check,
        artifact_bindings=artifact_bindings,
        source_frontier_digest=source_frontier_digest,
    )


def target_for(source, intent, address):
    """Independent task grader; no use of candidate graph paths or callbacks."""
    rows = {year: i for i, year in enumerate(source["years"])}
    if intent == "at":
        coordinates = [address]
    elif intent == "previous":
        coordinates = [shift_month(address, -1)]
    elif intent == "change":
        coordinates = [shift_month(address, -1), address]
    elif intent in {"mean3", "range3", "peak3"}:
        coordinates = [shift_month(address, i) for i in (-2, -1, 0)]
    else:
        raise ValueError("unsupported numeric target intent")
    numbers = [int(source["values"][rows[y]][m - 1]) for y, m in coordinates]
    if intent in {"at", "previous"}:
        answer = numbers[0]
    elif intent == "change":
        answer = numbers[1] - numbers[0]
    elif intent == "mean3":
        answer = (numbers[0] + numbers[1] + numbers[2]) / 3
    elif intent == "range3":
        answer = max(numbers) - min(numbers)
    else:
        answer = max(numbers)
    return TypedValue(
        "number", answer, tuple(coordinate_id(source["domain"], x) for x in coordinates)
    )


def numeric_grade(actual, target, *, reward_scale=1):
    if actual is None or actual.kind != "number" or actual.support != target.support:
        return 0.0
    return 1.0 / (1.0 + abs(float(actual.value) - float(target.value)) / reward_scale)


def make_query(row):
    return TypedValue("address", tuple(row["address"])), GraphQuery(
        scope=row["scope"],
        utterance=row["utterance"],
        handle=row["domain"],
        as_of=row["date"],
    )
