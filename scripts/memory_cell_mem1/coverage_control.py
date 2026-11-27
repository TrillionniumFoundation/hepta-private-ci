"""Teacher-free replay order controls on one frozen native state and pool."""

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import random
import time

from environment import OUTPUTS, WIDTH, commitment, panels
from native import NativeMemory, argmax

PROFILES = (
    "legacy_uniform",
    "legacy_structured",
    "coverage_uniform",
    "coverage_structured",
)
UPDATES = 64


def payload(row):
    return json.dumps(
        asdict(row), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def replay_order(rows, *, seed, profile):
    """Match the full sample multiset, including provenance and priority metadata."""
    if profile not in PROFILES or not rows or len(rows) > UPDATES:
        raise ValueError("invalid replay profile or population")
    if len({row.source for row in rows}) != len(rows):
        raise ValueError("duplicate source in frozen pool")
    for row in rows:
        payload(row)  # Reject non-finite metadata before the native operation.
    rng = random.Random(seed)
    quotas = None
    if profile.startswith("coverage_"):
        identities = sorted(range(len(rows)), key=lambda i: rows[i].source)
        rng.shuffle(identities)
        quotas = {i: UPDATES // len(rows) for i in identities}
        for i in identities[: UPDATES % len(rows)]:
            quotas[i] += 1
        # The ordering RNG is independent of quota allocation.
        rng = random.Random(seed + 1)
    order = []
    for step in range(UPDATES):
        available = [i for i in range(len(rows)) if quotas is None or quotas[i]]
        if profile.endswith("uniform"):
            # Uniform over the remaining multiset, not just distinct sources.
            choices = (
                available
                if quotas is None
                else [i for i in available for _ in range(quotas[i])]
            )
            selected = rng.choice(choices)
        elif step % 4 == 0:
            selected = max(available, key=lambda i: rows[i].step)
        elif step % 4 == 1:
            selected = max(available, key=lambda i: (rows[i].surprise, rows[i].source))
        elif step % 4 == 2:
            counts = Counter(rows[i].label for i in available)
            selected = min(
                available, key=lambda i: (counts[rows[i].label], rows[i].source)
            )
        else:
            retained = [i for i in available if rows[i].task == "A"]
            selected = rng.choice(retained or available)
        order.append(selected)
        if quotas is not None:
            quotas[selected] -= 1
    return order


class MeteredMemory(NativeMemory):
    def __init__(self, *args, **kwargs):
        self.replay_request_bytes = 0
        self.replay_requests = hashlib.sha256()
        super().__init__(*args, **kwargs)

    def command(self, text):
        if text.startswith("update "):
            data = (text + "\n").encode()
            self.replay_request_bytes += len(data)
            self.replay_requests.update(data)
        return super().command(text)


def execute_window(binary, state, checkpoint, owner, rows, *, seed, profile, output):
    """Execute the existing Rust kernel; never update the trajectory's parent."""
    started = time.perf_counter_ns()
    selection_started = time.perf_counter_ns()
    order = replay_order(rows, seed=seed, profile=profile)
    selection_ns = time.perf_counter_ns() - selection_started
    trace = output.with_suffix(".trace.jsonl")
    trace.write_text(
        json.dumps({"event": "started", "profile": profile, "pre_state": checkpoint[0]})
        + "\n"
    )
    memory = MeteredMemory(binary, state, owner.generation)
    result = None
    try:
        memory.restore(checkpoint)
        lineage = []
        for i in order:
            row = rows[i]
            support = owner.support(row)
            if support is None or tuple(owner.features[row.source]) != row.key:
                raise ValueError("ineligible or incorrectly encoded replay source")
            target = [float(label == row.label) for label in range(OUTPUTS)]
            with trace.open("a") as stream:
                stream.write(
                    json.dumps(
                        {"event": "update_attempt", "pool_index": i, "support": support}
                    )
                    + "\n"
                )
            receipt = memory.update(row.key, target, support)
            lineage.append(
                {"pool_index": i, "support": support, "state": memory.digest, **receipt}
            )
            with trace.open("a") as stream:
                stream.write(
                    json.dumps({"event": "update_receipt", **lineage[-1]}) + "\n"
                )
        replay_multiplications = memory.multiplications
        queries = []
        exposed = {row.source for row in rows}
        for panel, values in panels().items():
            for sources in values:
                predictions = [
                    argmax(memory.predict(owner.features[s])) for s in sources
                ]
                valid = all(
                    owner.resolve(s) is not None and s in exposed for s in sources
                )
                queries.append(
                    {
                        "panel": panel,
                        "sources": sources,
                        "output": predictions if valid else None,
                    }
                )
                with trace.open("a") as stream:
                    stream.write(json.dumps({"event": "query", **queries[-1]}) + "\n")
        after = memory.checkpoint()
        output.write_bytes(bytes.fromhex(after[1]))
        result = {
            "profile": profile,
            "status": "completed",
            "pre_state": checkpoint[0],
            "post_state": after[0],
            "pool_sha256": commitment([asdict(r) for r in rows]),
            "lineage": lineage,
            "queries": queries,
            "updates": len(order),
            "replay_payload_bytes": sum(len(payload(rows[i])) for i in order),
            "replay_request_bytes": memory.replay_request_bytes,
            "replay_request_sha256": memory.replay_requests.hexdigest(),
            "kernel_multiplications": replay_multiplications,
            "evaluation_multiplications": memory.multiplications
            - replay_multiplications,
            "teacher": {"calls": 0, "bytes": 0, "multiplications": 0},
            "selection_ns": selection_ns,
            "wall_ns": time.perf_counter_ns() - started,
            "native_ipc_wall_ns": memory.wall_ns,
            "native_calls": memory.calls,
        }
        return result
    except Exception as error:
        with trace.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "event": "failed",
                        "error": repr(error),
                        "observed_calls": memory.calls,
                        "observed_kernel_multiplications": memory.multiplications,
                    }
                )
                + "\n"
            )
        raise
    finally:
        memory.close()
        if result is not None:
            result["wall_ns"] = time.perf_counter_ns() - started


def audit_window(result, rows, owner, *, seed, checkpoint_sha256):
    """Reconstruct selected data and truth; this is not execution authentication."""
    order = replay_order(rows, seed=seed, profile=result["profile"])
    if result["status"] != "completed" or result["pre_state"] != checkpoint_sha256:
        raise ValueError("failed or differently initialized window")
    if result["pool_sha256"] != commitment([asdict(r) for r in rows]):
        raise ValueError("frozen pool identity mismatch")
    if [r["pool_index"] for r in result["lineage"]] != order:
        raise ValueError("replay order differs from frozen selector")
    requests = hashlib.sha256()
    request_bytes = 0
    for i, event in zip(order, result["lineage"]):
        row = rows[i]
        support = owner.support(row)
        if support is None or tuple(owner.features[row.source]) != row.key:
            raise ValueError("ineligible or incorrectly encoded retained source")
        if event["support"] != support:
            raise ValueError("replay provenance mismatch")
        target = [float(label == row.label) for label in range(OUTPUTS)]
        request = (
            f"update {owner.generation} {support} "
            + ",".join(map(repr, row.key))
            + " "
            + ",".join(map(repr, target))
            + "\n"
        ).encode()
        requests.update(request)
        request_bytes += len(request)
    expected = {
        "updates": UPDATES,
        "replay_payload_bytes": sum(len(payload(rows[i])) for i in order),
        "replay_request_bytes": request_bytes,
        "replay_request_sha256": requests.hexdigest(),
        "kernel_multiplications": UPDATES * (3 * WIDTH * OUTPUTS + WIDTH + 2 * OUTPUTS),
        "teacher": {"calls": 0, "bytes": 0, "multiplications": 0},
    }
    if any(result[key] != value for key, value in expected.items()):
        raise ValueError("replay cost ledger differs from retained inputs")
    roster = [(p, list(q)) for p, queries in panels().items() for q in queries]
    if [(r["panel"], list(r["sources"])) for r in result["queries"]] != roster:
        raise ValueError("evaluation query roster differs from frozen panel")
    scores = {}
    for record in result["queries"]:
        sources = record["sources"]
        answer = record["output"]
        if answer is not None and (
            not isinstance(answer, list)
            or len(answer) != len(sources)
            or any(type(x) is not int or not 0 <= x < OUTPUTS for x in answer)
        ):
            raise ValueError("invalid recorded prediction labels")
        # An unobserved but still valid fact remains a missed answer, not a
        # correct abstention. Only actual revocation/scope invalidates truth.
        valid = all(owner.resolve(s) is not None for s in sources)
        expected_output = [owner.facts[s].label for s in sources] if valid else None
        score = scores.setdefault(record["panel"], {"correct": 0, "total": 0})
        score["correct"] += record["output"] == expected_output
        score["total"] += 1
    return {
        "scores": scores,
        "source_multiset": dict(
            sorted(Counter(commitment(asdict(rows[i])) for i in order).items())
        ),
    }


def audit_pair(uniform, structured, uniform_audit, structured_audit):
    keys = (
        "pre_state",
        "pool_sha256",
        "updates",
        "replay_payload_bytes",
        "replay_request_bytes",
        "kernel_multiplications",
        "teacher",
    )
    if any(uniform[k] != structured[k] for k in keys) or (
        uniform_audit["source_multiset"] != structured_audit["source_multiset"]
    ):
        raise ValueError("coverage-matched pair differs in data, state or replay cost")
    return {key: uniform[key] for key in keys}
