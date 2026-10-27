"""Coordinate-addressed numeric memory fitted as compact local subspaces.

Every record latent, decoder weight, column center, route and availability
mask is serialized. Integer factors make saved-model reconstruction independent
of BLAS batching. Full SVD is real fitting, not an optimizer-step claim.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import time

import numpy as np


MAGIC = b"HMFAC3\0\0"
HEADER = struct.Struct("<8sIHHBBH")
BLOCK_HEADER = struct.Struct("<HhI")
MAX_VALUES = 16_777_216
MAX_ROWS = 1_000_000
MAX_COLUMNS = 4096
MAX_CELLS = 256
MAX_RANK = 256
MAX_ARTIFACT_BYTES = (
    4 * MAX_VALUES
    + 4 * MAX_CELLS * MAX_COLUMNS
    + (MAX_VALUES + 7) // 8
    + (MAX_ROWS * (MAX_CELLS - 1).bit_length() + 7) // 8
    + HEADER.size
    + MAX_CELLS * BLOCK_HEADER.size
)


def canonical_matrix(values, mask=None):
    array = np.asarray(values)
    if array.ndim != 2 or array.dtype.kind not in "iu":
        raise ValueError("numeric memory requires an integer matrix")
    n, d = array.shape
    if not (1 <= n <= MAX_ROWS and 1 <= d <= MAX_COLUMNS and n * d <= MAX_VALUES):
        raise ValueError("numeric memory shape exceeds bounds")
    if (array < -(2**31)).any() or (array > 2**31 - 1).any():
        raise ValueError("numeric memory values exceed int32")
    observed = np.ones(array.shape, dtype=bool) if mask is None else np.asarray(mask)
    if observed.dtype != np.dtype(bool) or observed.shape != array.shape:
        raise ValueError("availability mask shape/type mismatch")
    if not observed.any() or (array[~observed] != 0).any():
        raise ValueError(
            "missing coordinates must be canonical zero; source cannot be empty"
        )
    return np.ascontiguousarray(array, dtype="<i4"), np.ascontiguousarray(observed)


def packed_routes(routes, bits):
    if not bits:
        return b""
    flags = (
        (routes.astype(np.uint64)[:, None] >> np.arange(bits, dtype=np.uint64)) & 1
    ).astype(np.uint8)
    return np.packbits(flags.ravel(), bitorder="little").tobytes()


@dataclass(frozen=True)
class FactorBlock:
    center: np.ndarray
    record_factors: np.ndarray
    decoder: np.ndarray
    shift: int

    @property
    def rank(self):
        return self.record_factors.shape[1]

    def reconstruct(self):
        products = self.record_factors.astype(np.int64) @ self.decoder.astype(np.int64)
        if self.shift > 0:
            products = (products + (1 << (self.shift - 1))) // (1 << self.shift)
        elif self.shift < 0:
            products = products * (1 << -self.shift)
        return products + self.center.astype(np.int64)[None, :]


@dataclass(frozen=True)
class FactorBank:
    """One or more learned numeric cells, with charged row-address routes."""

    routes: np.ndarray
    mask: np.ndarray
    blocks: tuple

    def __post_init__(self):
        route, mask = np.asarray(self.routes), np.asarray(self.mask)
        if mask.ndim != 2 or mask.dtype != np.dtype(bool):
            raise ValueError("invalid availability mask")
        n, d = mask.shape
        if not (1 <= n <= MAX_ROWS and 1 <= d <= MAX_COLUMNS and n * d <= MAX_VALUES):
            raise ValueError("invalid bank dimensions")
        if (
            route.shape != (n,)
            or route.dtype.kind not in "iu"
            or not 1 <= len(self.blocks) <= MAX_CELLS
        ):
            raise ValueError("invalid route schema")
        if set(route.tolist()) != set(range(len(self.blocks))):
            raise ValueError(
                "every cell must have a contiguous, nonempty route identity"
            )
        owned = []
        for index, block in enumerate(self.blocks):
            count = int(np.count_nonzero(route == index))
            rank = (
                block.record_factors.shape[1] if block.record_factors.ndim == 2 else 0
            )
            if not (0 <= rank <= min(count, d, MAX_RANK) and -20 <= block.shift <= 48):
                raise ValueError("invalid factor dimensions or scaling")
            if (
                block.center.shape != (d,)
                or block.record_factors.shape != (count, rank)
                or block.decoder.shape != (rank, d)
            ):
                raise ValueError("factor tensor shape mismatch")
            arrays = []
            for array, dtype, lower, upper in (
                (block.center, "<i4", -(2**31), 2**31 - 1),
                (block.record_factors, "<i2", -32768, 32767),
                (block.decoder, "<i2", -32768, 32767),
            ):
                if (
                    array.dtype.kind not in "iu"
                    or (array < lower).any()
                    or (array > upper).any()
                ):
                    raise ValueError("factor tensor value exceeds declared precision")
                item = np.array(array, dtype=dtype, order="C", copy=True)
                item.setflags(write=False)
                arrays.append(item)
            owned.append(FactorBlock(*arrays, int(block.shift)))
        route = np.array(route, dtype=np.uint8, copy=True)
        mask = np.array(mask, dtype=bool, order="C", copy=True)
        route.setflags(write=False)
        mask.setflags(write=False)
        object.__setattr__(self, "routes", route)
        object.__setattr__(self, "mask", mask)
        object.__setattr__(self, "blocks", tuple(owned))

    @property
    def shape(self):
        return self.mask.shape

    @property
    def digest(self):
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @property
    def parameter_bytes(self):
        return sum(
            b.center.nbytes + b.record_factors.nbytes + b.decoder.nbytes
            for b in self.blocks
        )

    def reconstruct(self):
        result = np.empty(self.shape, dtype=np.int64)
        for index, block in enumerate(self.blocks):
            result[self.routes == index] = block.reconstruct()
        return result

    def read(self, rows, columns):
        row, column = np.asarray(rows), np.asarray(columns)
        if (
            row.shape != column.shape
            or row.ndim != 1
            or row.dtype.kind not in "iu"
            or column.dtype.kind not in "iu"
        ):
            raise ValueError("coordinates must be aligned integer vectors")
        if (
            (row < 0).any()
            or (row >= self.shape[0]).any()
            or (column < 0).any()
            or (column >= self.shape[1]).any()
        ):
            raise ValueError("coordinate outside memory scope")
        predictions = np.empty(len(row), dtype=np.int64)
        for index, block in enumerate(self.blocks):
            positions = np.flatnonzero(self.routes[row] == index)
            local_rows = np.searchsorted(
                np.flatnonzero(self.routes == index), row[positions]
            )
            chosen = column[positions]
            products = np.sum(
                block.record_factors[local_rows].astype(np.int64)
                * block.decoder[:, chosen].T.astype(np.int64),
                axis=1,
            )
            if block.shift > 0:
                products = (products + (1 << (block.shift - 1))) // (1 << block.shift)
            elif block.shift < 0:
                products = products * (1 << -block.shift)
            predictions[positions] = products + block.center[chosen]
        return [
            int(v) if known else None
            for v, known in zip(predictions, self.mask[row, column], strict=True)
        ]

    def to_bytes(self):
        n, d = self.shape
        bits = (len(self.blocks) - 1).bit_length()
        has_mask = int(not self.mask.all())
        parts = [
            HEADER.pack(MAGIC, n, d, len(self.blocks), bits, has_mask, 1),
            packed_routes(self.routes, bits),
        ]
        if has_mask:
            parts.append(np.packbits(self.mask.ravel(), bitorder="little").tobytes())
        for block in self.blocks:
            parts.extend(
                [
                    BLOCK_HEADER.pack(
                        block.rank, block.shift, len(block.record_factors)
                    ),
                    block.center.tobytes(),
                    block.record_factors.tobytes(),
                    block.decoder.tobytes(),
                ]
            )
        return b"".join(parts)

    @classmethod
    def from_bytes(cls, payload, expected_sha256=None):
        if (
            not isinstance(payload, bytes)
            or not HEADER.size <= len(payload) <= MAX_ARTIFACT_BYTES
        ):
            raise ValueError("truncated factor artifact")
        if (
            expected_sha256 is not None
            and hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise ValueError("factor artifact digest mismatch")
        magic, n, d, k, bits, has_mask, version = HEADER.unpack_from(payload)
        if (magic, version) != (MAGIC, 1) or has_mask not in (0, 1):
            raise ValueError("unknown factor artifact contract")
        if not (
            1 <= n <= MAX_ROWS
            and 1 <= d <= MAX_COLUMNS
            and n * d <= MAX_VALUES
            and 1 <= k <= MAX_CELLS
        ):
            raise ValueError("factor artifact dimensions exceed bounds")
        if bits != (k - 1).bit_length():
            raise ValueError("noncanonical route width")
        position = HEADER.size
        route_bytes = (n * bits + 7) // 8
        if position + route_bytes > len(payload):
            raise ValueError("truncated routes")
        if bits:
            flags = np.unpackbits(
                np.frombuffer(
                    payload[position : position + route_bytes], dtype=np.uint8
                ),
                bitorder="little",
            )
            if flags[n * bits :].any():
                raise ValueError("nonzero route padding")
            routes = (
                flags[: n * bits].reshape(n, bits).astype(np.uint64)
                @ (np.uint64(1) << np.arange(bits, dtype=np.uint64))
            ).astype(np.uint8)
        else:
            routes = np.zeros(n, dtype=np.uint8)
        position += route_bytes
        if has_mask:
            size = (n * d + 7) // 8
            if position + size > len(payload):
                raise ValueError("truncated availability mask")
            flags = np.unpackbits(
                np.frombuffer(payload[position : position + size], dtype=np.uint8),
                bitorder="little",
            )
            if flags[n * d :].any():
                raise ValueError("nonzero mask padding")
            mask = flags[: n * d].reshape(n, d).astype(bool)
            position += size
        else:
            mask = np.ones((n, d), dtype=bool)
        blocks = []
        for index in range(k):
            if position + BLOCK_HEADER.size > len(payload):
                raise ValueError("truncated factor block header")
            rank, shift, count = BLOCK_HEADER.unpack_from(payload, position)
            position += BLOCK_HEADER.size
            if count != int(np.count_nonzero(routes == index)) or not 0 <= rank <= min(
                count, d, MAX_RANK
            ):
                raise ValueError("factor block record/rank mismatch")
            size = 4 * d + 2 * count * rank + 2 * rank * d
            if position + size > len(payload):
                raise ValueError("truncated factor tensors")
            center = np.frombuffer(payload, dtype="<i4", count=d, offset=position)
            position += 4 * d
            records = np.frombuffer(
                payload, dtype="<i2", count=count * rank, offset=position
            ).reshape(count, rank)
            position += 2 * count * rank
            decoder = np.frombuffer(
                payload, dtype="<i2", count=rank * d, offset=position
            ).reshape(rank, d)
            position += 2 * rank * d
            blocks.append(FactorBlock(center, records, decoder, shift))
        if position != len(payload):
            raise ValueError("trailing factor artifact bytes")
        return cls(routes, mask, tuple(blocks))

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(self.to_bytes())
        return {"bytes": path.stat().st_size, "sha256": self.digest}

    @classmethod
    def load(cls, path, expected_sha256=None):
        path = Path(path)
        if path.is_symlink() or path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError("invalid or oversized factor artifact")
        return cls.from_bytes(path.read_bytes(), expected_sha256)

    @classmethod
    def fit(cls, matrix, *, ranks, routes=None, mask=None, seed=0, imputation_steps=8):
        started = time.perf_counter()
        values, observed = canonical_matrix(matrix, mask)
        n, d = values.shape
        ranks = tuple(ranks)
        route = np.zeros(n, dtype=np.uint8) if routes is None else np.asarray(routes)
        if (
            route.dtype.kind not in "iu"
            or route.shape != (n,)
            or set(route.tolist()) != set(range(len(ranks)))
        ):
            raise ValueError("invalid fitting routes")
        if not 1 <= len(ranks) <= MAX_CELLS or not 0 <= imputation_steps <= 100:
            raise ValueError("invalid fitting budget")
        blocks, fit_records = [], []
        svd_calls, svd_work = 0, 0
        float_squared_error = 0.0
        for index, rank in enumerate(ranks):
            local = values[route == index].astype(np.float64)
            known = observed[route == index]
            if not isinstance(rank, (int, np.integer)) or not 0 <= rank <= min(
                len(local), d, MAX_RANK
            ):
                raise ValueError("rank exceeds local dimensions")
            counts = known.sum(axis=0)
            centers = np.floor(
                np.divide(
                    np.where(known, local, 0).sum(axis=0),
                    counts,
                    out=np.zeros(d),
                    where=counts > 0,
                )
                + 0.5
            ).astype("<i4")
            filled = np.where(known, local, centers[None, :])
            iterations = (1 if known.all() else imputation_steps + 1) if rank else 0
            block_start = time.perf_counter()
            left, singular, right = (
                np.empty((len(local), 0)),
                np.empty(0),
                np.empty((0, d)),
            )
            unquantized = np.broadcast_to(centers, local.shape).astype(np.float64)
            for _ in range(iterations):
                left, singular, right = np.linalg.svd(
                    filled - centers, full_matrices=False
                )
                unquantized = (left[:, :rank] * singular[:rank]) @ right[
                    :rank
                ] + centers
                filled = np.where(known, local, unquantized)
            svd_calls += iterations
            svd_work += iterations * len(local) * d * min(len(local), d)
            unquantized_error = float(
                np.square(unquantized[known] - local[known]).sum()
            )
            float_squared_error += unquantized_error
            first = left[:, :rank] * np.sqrt(singular[:rank])
            second = np.sqrt(singular[:rank])[:, None] * right[:rank]
            quantized, exponents = [], []
            for factor in (first, second):
                peak = float(np.max(np.abs(factor))) if factor.size else 0.0
                exponent = (
                    max(-24, min(20, int(np.ceil(np.log2(peak / 32760)))))
                    if peak
                    else 0
                )
                q = np.floor(factor / (2.0**exponent) + 0.5)
                if (q < -32768).any() or (q > 32767).any():
                    raise ValueError("factor quantization would saturate")
                quantized.append(q.astype("<i2"))
                exponents.append(exponent)
            shift = -sum(exponents)
            if not -20 <= shift <= 48:
                raise ValueError("factor scale outside portable integer contract")
            blocks.append(FactorBlock(centers, quantized[0], quantized[1], shift))
            fit_records.append(
                {
                    "cell": index,
                    "rows": len(local),
                    "columns": d,
                    "rank": int(rank),
                    "svd_calls": iterations,
                    "fit_seconds": time.perf_counter() - block_start,
                    "unquantized_squared_error": unquantized_error,
                    "shift": shift,
                }
            )
        bank = cls(route, observed, tuple(blocks))
        prediction = bank.reconstruct()
        error = prediction[observed] - values[observed].astype(np.int64)
        receipt = {
            "schema": "memory-cell-v3.factor-fit.v1",
            "algorithm": "centered full SVD; iterative missing-value imputation only when needed",
            "seed": int(seed),
            "fit_randomness": "none; seed is an experiment identity, not a randomized factorization",
            "optimizer_steps": 0,
            "svd_calls": svd_calls,
            "svd_work_proxy": svd_work,
            "work_proxy_definition": "sum(rows * columns * min(rows, columns)) over actual SVD calls; not measured FLOPs",
            "fit_wall_seconds": time.perf_counter() - started,
            "blocks": fit_records,
            "parameter_bytes": bank.parameter_bytes,
            "artifact_bytes": len(bank.to_bytes()),
            "artifact_sha256": bank.digest,
            "routing_bytes": len(
                packed_routes(bank.routes, (len(bank.blocks) - 1).bit_length())
            ),
            "availability_mask_bytes": 0 if observed.all() else (n * d + 7) // 8,
            "written_mse": float(np.mean(error.astype(np.float64) ** 2)),
            "written_mae": float(np.mean(np.abs(error))),
            "written_exact_accuracy": float(np.mean(error == 0)),
            "unquantized_svd_mse": float_squared_error / int(observed.sum()),
            "source_sha256": hashlib.sha256(
                values.tobytes()
                + np.packbits(observed.ravel(), bitorder="little").tobytes()
            ).hexdigest(),
        }
        return bank, receipt
