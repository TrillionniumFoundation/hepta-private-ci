"""The existing full native/PNG path, with separate lossless evidence capture."""

import hashlib
import json
import time

import numpy as np

from independent.accounting import WorkLedger
from independent.evaluation import _outputs
from independent.native import NativeGenerator

WILLIAMS = ((0, 1, 3, 2), (1, 2, 0, 3), (2, 3, 1, 0), (3, 0, 2, 1))


def cohorts(data):
    sources = sorted(
        set(data["source_ids"]),
        key=lambda source: (
            data["sources"][source]["scene"],
            hashlib.sha256(("reinfer-d1-cohort:" + source).encode()).hexdigest(),
        ),
    )
    groups = []
    ids = np.asarray(data["source_ids"])
    for offset in range(0, 192, 4):
        selected = sources[offset : offset + 4]
        indices = np.concatenate([np.flatnonzero(ids == source) for source in selected])
        assert len(indices) == 64
        groups.append(indices)
    order = sorted(
        range(48),
        key=lambda i: hashlib.sha256(
            (
                "reinfer-d1-order:"
                + ":".join(data["source_ids"][int(j)] for j in groups[i])
            ).encode()
        ).hexdigest(),
    )
    return np.stack([groups[i] for i in order])


def prepare(model, library):
    return NativeGenerator(model, library_path=library, prepare_low=False)


def state():
    return {
        "p": np.full((3072, 12), np.nan),
        "q": np.full((3072, 12), np.nan),
        "choices": np.zeros((4, 3072, 2), dtype=np.uint8),
        "payload_sha256": np.zeros((4, 3072, 32), dtype=np.uint8),
        "output_bytes": np.zeros((4, 3072), dtype=np.uint32),
        "completed": np.zeros((4, 48), dtype=bool),
        "batches": [],
    }


def batch(generator, x, sample_seed):
    ledger = WorkLedger("actual-batch", 64 * 2 * 19236)
    started, wall = time.process_time_ns(), time.perf_counter_ns()
    p, q, receipt = generator.batch(x, "full", ledger=ledger, per_request_cap=2 * 19236)
    native_done = time.process_time_ns()
    outputs, sizes = _outputs(
        generator, p, q, ledger, np.random.default_rng(sample_seed)
    )
    output_done = time.process_time_ns()
    result = {
        "cpu_ns": output_done - started,
        "wall_ns": time.perf_counter_ns() - wall,
        "native_and_ledger_cpu_ns": native_done - started,
        "output_and_ledger_cpu_ns": output_done - native_done,
        "work_units": ledger.consumed_units,
        "forwards": receipt["model_forwards"],
    }
    assert result["work_units"] == 64 * 19236 and result["forwards"] == 64
    return p, q, outputs, sizes, result


def capture(storage, rows, wave, cohort_index, p, q, outputs, sizes, cost, payloads):
    if wave == 0:
        storage["p"][rows], storage["q"][rows] = p, q
    else:
        np.testing.assert_allclose(storage["p"][rows], p, rtol=1e-10, atol=1e-12)
        np.testing.assert_allclose(storage["q"][rows], q, rtol=1e-10, atol=1e-12)
    for i, (row, output) in enumerate(zip(rows, outputs)):
        payload = json.dumps(
            output, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        digest = hashlib.sha256(payload).digest()
        payloads.setdefault(digest.hex(), output)
        storage["payload_sha256"][wave, row] = np.frombuffer(digest, dtype=np.uint8)
        storage["choices"][wave, row] = (
            output["choices"]["text"],
            output["choices"]["image"],
        )
        storage["output_bytes"][wave, row] = sizes[i]
    storage["completed"][wave, cohort_index] = True
    storage["batches"].append({"wave": wave, "cohort": cohort_index, **cost})
