"""Independent source reconstruction, integer arithmetic and receipt checks."""

import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np


PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
SOURCE_PREFIX = "qualification/memory-cell-v3/sources/numeric/"
WORK_KEYS = (
    "candidate_fits",
    "svd_calls",
    "svd_work_proxy",
    "fit_wall_seconds",
    "kmeans_distance_component_terms",
    "kmeans_iterations",
)


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def source_hash(values):
    return sha256(
        np.asarray(values, dtype="<i4").tobytes()
        + np.packbits(np.ones(values.size, dtype=bool), bitorder="little").tobytes()
    )


def checked_file(root, *parts):
    path = Path(root)
    for part in parts:
        relative = Path(part)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("noncanonical audit artifact path")
        for component in relative.parts:
            path = path / component
            if path.is_symlink():
                raise ValueError("audit does not follow artifact symlinks")
    if not path.is_file():
        raise ValueError("missing audit artifact: " + str(path))
    return path


def read_json(path):
    return json.loads(Path(path).read_bytes())


class Checks:
    def __init__(self):
        self.count = 0
        self.failures = []

    def require(self, condition, label, detail=None):
        self.count += 1
        if not condition:
            self.failures.append({"check": label, "detail": detail})

    def near(self, actual, expected, label):
        valid = (
            isinstance(actual, (int, float))
            and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
        )
        self.require(
            valid,
            label,
            {"reported": actual, "recomputed": expected} if not valid else None,
        )


class Sources:
    def __init__(self, run, summary, allow_legacy, checks):
        self.run = Path(run)
        self.checks = checks
        self.archive = None
        self.identity = None
        identity = self.run / "source_identity.json"
        snapshot = self.run / "source_snapshot.zip"
        if identity.is_file() and snapshot.is_file():
            self.identity = read_json(identity)
            self.archive = zipfile.ZipFile(snapshot)
            protocol_raw = checked_file(self.run, "protocol.json").read_bytes()
            self.protocol = json.loads(protocol_raw)
            self.mode = read_json(checked_file(self.run, "environment.json"))["mode"]
            checks.require(
                protocol_raw == self.read("qualification/memory-cell-v3/PROTOCOL.json"),
                "protocol snapshot bytes",
            )
            checks.require(
                summary["source_commit"] == self.identity["commit"],
                "capacity source commit binding",
            )
            checks.require(
                summary["settings"] == self.protocol["capacity"],
                "capacity exact protocol profile",
            )
            checks.require(
                self.mode in ("development_only", "frozen_protocol_research"),
                "recognized execution mode",
            )
            development = self.mode == "development_only"
            checks.require(
                summary["development"] == development, "capacity mode binding"
            )
            checks.require(
                summary["seeds"]
                == self.protocol["development_seeds" if development else "seeds"],
                "capacity seed binding",
            )
            self.binding = (
                "snapshot-bound-development"
                if development
                else "snapshot-bound-formal; independent full evidence verification also required"
            )
        elif (
            allow_legacy
            and summary.get("development") is True
            and not identity.exists()
            and not snapshot.exists()
        ):
            self.protocol = {"capacity": summary["settings"], "statistics": {}}
            self.mode = "legacy_development_without_source_snapshot"
            self.binding = "Fixed source bytes checked against retained source digests, but exact executed code identity was not captured and cannot be retrospectively assigned."
        else:
            raise ValueError(
                "missing unified source snapshot; only explicit legacy-development auditing is permitted"
            )

    def read(self, name):
        if self.archive is None:
            return checked_file(REPO, name).read_bytes()
        expected = self.identity["files"][name]
        info = self.archive.getinfo(name)
        if info.file_size != expected["bytes"] or info.file_size > 32 * 1024 * 1024:
            raise ValueError("bound source size mismatch")
        payload = self.archive.read(name)
        if sha256(payload) != expected["sha256"]:
            raise ValueError("bound source digest mismatch: " + name)
        return payload

    def close(self):
        if self.archive is not None:
            self.archive.close()


def independent_sources(store, settings, seeds):
    sources = {}
    for domain in settings["numeric_domains"]:
        payload = store.read(SOURCE_PREFIX + domain + ".json")
        original = json.loads(payload)
        matrix = np.asarray(original["values"], dtype=np.int64)
        if matrix.ndim != 2 or (matrix < -(2**31)).any() or (matrix > 2**31 - 1).any():
            raise ValueError("invalid fixed numeric source")
        groups = min(settings["cells"], len(matrix))
        routes = np.array(
            [min(groups - 1, row * groups // len(matrix)) for row in range(len(matrix))]
        )
        raw = store.read(SOURCE_PREFIX + original["source"]["filename"])
        store.checks.require(
            len(raw) == original["raw_source"]["bytes"]
            and sha256(raw) == original["raw_source"]["sha256"],
            domain + " raw provenance bytes",
        )
        sources[domain] = {
            "values": matrix.astype(np.int32),
            "scale": original["scale"],
            "seeds": seeds,
            "group": domain,
            "metadata": original,
            "source_json_sha256": sha256(payload),
            "declared_routes": routes,
        }
    if settings["include_digits"]:
        payload = store.read("qualification/memory-cell-v2/sources/external/digits.npz")
        with np.load(io.BytesIO(payload), allow_pickle=False) as data:
            values = data["X"]
            if (
                not np.isfinite(values).all()
                or not np.equal(values, np.floor(values)).all()
            ):
                raise ValueError("pixel source is not integral")
            sources["digits-pixels"] = {
                "values": values.astype(np.int32),
                "scale": 1,
                "seeds": seeds,
                "group": "digits-pixels",
                "source_npz_sha256": sha256(payload),
                "declared_routes": data["y"].copy(),
            }
    for seed in seeds:
        generator = np.random.default_rng(seed)
        n, d, k = (
            settings["synthetic_rows"],
            settings["synthetic_columns"],
            settings["cells"],
        )
        groups = np.array([min(k - 1, row * k // n) for row in range(n)])
        latent = generator.integers(-7, 8, size=(n, 2))
        decoders = generator.integers(-7, 8, size=(k, 2, d))
        centers = generator.integers(-80, 81, size=(k, d))
        structured = np.stack(
            [
                latent[row].dot(decoders[groups[row]]) + centers[groups[row]]
                for row in range(n)
            ]
        )
        random = generator.integers(-200, 201, size=(n, d))
        selector = generator.random((n, d))
        for mixture in settings["random_mix"]:
            name = (
                "synthetic-mix-" + str(mixture).replace(".", "p") + "-seed-" + str(seed)
            )
            values = structured.copy()
            positions = selector < mixture
            values[positions] = random[positions]
            sources[name] = {
                "values": values.astype(np.int32),
                "scale": 1,
                "seeds": [seed],
                "group": "synthetic-mix-" + str(float(mixture)),
                "random_mix": mixture,
                "declared_routes": groups,
            }
    return sources


def independent_coordinates(shape, seed, settings):
    count = int(np.prod(shape))
    permutation = np.random.default_rng(seed).permutation(count)
    selected = min(count - 1, max(1, int(count * settings["selection_fraction"])))
    mask = np.zeros(count, dtype=bool)
    mask[permutation[:selected]] = True
    queries = np.random.default_rng(seed + 101).permutation(np.flatnonzero(~mask))[
        : settings["hidden_query_limit"]
    ]
    return mask.reshape(shape), queries // shape[1], queries % shape[1]


def integer_reference(bank, rows, columns):
    """Python integer dot products, independent of production read/reconstruct."""
    positions = np.empty(len(bank.routes), dtype=np.int64)
    counts = [0] * len(bank.blocks)
    for index, group in enumerate(bank.routes):
        positions[index] = counts[int(group)]
        counts[int(group)] += 1
    answers = []
    for row, column in zip(rows, columns, strict=True):
        if not bank.mask[row, column]:
            answers.append(None)
            continue
        block = bank.blocks[int(bank.routes[row])]
        left = block.record_factors[positions[row]]
        value = sum(
            int(left[rank]) * int(block.decoder[rank, column])
            for rank in range(len(left))
        )
        if block.shift > 0:
            value = (value + 2 ** (block.shift - 1)) // 2**block.shift
        elif block.shift < 0:
            value *= 2 ** (-block.shift)
        answers.append(value + int(block.center[column]))
    return answers


def independent_metrics(answers, truth, scale, variance):
    errors = [
        int(answer) - int(target) for answer, target in zip(answers, truth, strict=True)
    ]
    count = len(errors)
    mse = sum(error * error for error in errors) / count
    return {
        "queries": count,
        "mse_scaled_integer": mse,
        "normalized_mse": mse / max(variance, 1e-30),
        "mae_original_units": sum(abs(error) for error in errors) / count / scale,
        "rmse_original_units": math.sqrt(mse) / scale,
        "max_error_original_units": max(abs(error) for error in errors) / scale,
        "exact_accuracy": sum(error == 0 for error in errors) / count,
    }


def receipt_work(receipts, route_receipts, checks, label, shape):
    work = dict.fromkeys(WORK_KEYS, 0)
    work["candidate_fits"] = len(receipts)
    for receipt in receipts:
        calls = sum(block["svd_calls"] for block in receipt["blocks"])
        proxy = sum(
            block["rows"]
            * block["columns"]
            * min(block["rows"], block["columns"])
            * block["svd_calls"]
            for block in receipt["blocks"]
        )
        checks.require(
            receipt["optimizer_steps"] == 0
            and receipt["svd_calls"] == calls
            and receipt["svd_work_proxy"] == proxy,
            label + " SVD work formula",
        )
        checks.require(
            math.isfinite(receipt["fit_wall_seconds"])
            and receipt["fit_wall_seconds"] >= 0,
            label + " nonnegative recorded time",
        )
        work["svd_calls"] += calls
        work["svd_work_proxy"] += proxy
        work["fit_wall_seconds"] += receipt["fit_wall_seconds"]
    for route in route_receipts:
        expected = shape[0] * shape[1] * route["cells"] * (route["iterations"] + 1)
        checks.require(
            route["distance_component_terms"] == expected,
            label + " kmeans work formula",
        )
        checks.require(
            math.isfinite(route["fit_wall_seconds"]) and route["fit_wall_seconds"] >= 0,
            label + " nonnegative route time",
        )
        work["fit_wall_seconds"] += route["fit_wall_seconds"]
        work["kmeans_distance_component_terms"] += route["distance_component_terms"]
        work["kmeans_iterations"] += route["iterations"]
    return work


def compare_work(actual, reported, checks, label):
    for key in WORK_KEYS:
        checks.near(reported[key], actual[key], label + " " + key)


def add_work(total, work):
    for key in WORK_KEYS:
        total[key] += work[key]
