"""Verify every retained query checkpoint without importing project helpers."""

import hashlib
import json
import math
import os
from pathlib import Path
import time

os.sched_setaffinity(0, {1})
started = time.process_time()
here = Path(__file__).resolve().parent
folder = here / "recovery_confirmation_01"


def body(value):
    value = dict(value)
    expected = value.pop("sha256")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(raw).hexdigest() == expected
    return value


checks, states, identities = 0, 0, {}
for path in sorted(folder.glob("*/*/state.json")):
    if path.parts[-3].startswith("atomic_"):
        continue
    raw = path.read_bytes()
    identities[str(path.relative_to(folder))] = hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw)
    outer, memory = body(payload), body(payload["memory"])
    reference = json.loads((path.parents[1] / "reference/OUTPUT.json").read_text())["result"]
    completed = outer["completed_query"]
    assert 0 <= completed <= 5
    assert payload["memory"]["sha256"] == reference["queries"][completed]["checkpoint_sha256"]
    assert outer["model"] == memory["model"]
    assert outer["world"] == reference["world"] and outer["seed"] == reference["seed"]
    assert outer["representation"] == reference["representation"]
    assert len(outer["history"]) == completed + 1 and len(outer["receipts"]) == completed + 1
    assert abs(memory["clock"] - reference["queries"][completed]["deadline"]) < 1e-10
    for q, public in enumerate(outer["history"]):
        expected = {k: v for k, v in reference["queries"][q].items() if k not in ("target", "reward", "utility")}
        assert public == expected
        assert outer["receipts"][q]["memory_sha256"] == expected["checkpoint_sha256"]
        assert outer["receipts"][q]["query"] == q
        assert outer["receipts"][q]["file_fsyncs"] == outer["receipts"][q]["directory_fsyncs"] == 1
        checks += 4
    masses = memory["beliefs"] if reference["representation"] == "full" else memory["packed"]
    width = 40 if reference["representation"] == "full" else 8
    assert len(masses) == 4
    for row in masses:
        assert len(row) == width and all(math.isfinite(x) for x in row)
        assert min(row) >= (-1e-13 if width == 40 else 0.)
        assert abs(sum(row) - 1) < 2e-11
        checks += 3
    if width == 8:
        assert len(memory["anchor_times"]) == 4
        assert all(math.isfinite(x) and 0 <= x <= memory["clock"] for x in memory["anchor_times"])
        checks += 2
    states += 1
    checks += 8
assert states == 96
result = dict(passed=True, states=states, checks=checks, sha256=identities,
              measured_body_cpu_seconds=time.process_time() - started,
              reviewer_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              scope="Independent standard-library audit of all retained full, anchored, reference, lost-reply and resumed checkpoint files. Checks envelope/memory hashes, public history, receipts, model ownership, mass and anchor constraints; not an independent diffusion simulator or power-loss test.")
with (here / "INDEPENDENT_ALL_STATE_REVIEW.json").open("x") as stream:
    json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
