"""Fresh deterministic source records and an executor-independent value oracle."""

import hashlib
import random

from .contracts import canonical, digest
from .store import EventStore

SINCE, AT, LATEST = 20250101, 20250201, 20250301
OPCODES = ("identity", "add_bias", "multiply", "affine", "clamp")


def create_sources(path, *, seed, domain, count=24):
    rng = random.Random(seed ^ int(hashlib.sha256(domain.encode()).hexdigest()[:8], 16))
    scope = f"v6.{domain}.{seed}"
    truth = {}
    store = EventStore(path)
    try:
        for index in range(count):
            nonce = hashlib.sha256(canonical([seed, domain, index, "post-router-fit"])).hexdigest()[:12]
            entity = (
                {"engineering": "unit", "laboratory": "sample", "logistics": "lot"}.get(domain, "entity") + "-" + nonce
            )
            events = [rng.randint(-90, 90) for _ in range(3)]
            semantic = {"factor": rng.choice([-7, -3, -2, 2, 3, 5, 7]), "label": "attribute-" + nonce}
            program = {
                "opcode": OPCODES[(index + seed) % len(OPCODES)],
                "bias": rng.randint(-25, 25),
                "limit": rng.randint(20, 70),
            }
            record = {
                "entity": entity,
                "scope": scope,
                "events": events,
                "semantic": semantic,
                "procedure": program,
                "sources": {},
            }
            for event_index, stamp in enumerate((SINCE, AT, LATEST)):
                record["sources"][str(stamp)] = store.append(
                    scope=scope,
                    entity=entity,
                    kind="event",
                    effective_at=stamp,
                    value=events[event_index],
                    origin_id=f"fixture.{domain}.{index}.event{event_index}",
                )
            for kind, value in (("semantic", semantic), ("procedure", program)):
                record["sources"][kind] = store.append(
                    scope=scope,
                    entity=entity,
                    kind=kind,
                    effective_at=20240101,
                    value=value,
                    origin_id=f"fixture.{domain}.{index}.{kind}",
                )
            truth[entity] = record
        return {
            "scope": scope,
            "seed": seed,
            "domain": domain,
            "entities": truth,
            "source_cut": store.cut,
            "source_frontier": store.frontier(scope),
            "truth_digest": digest(truth),
        }
    finally:
        store.close()


def expected(record, operation):
    """Grader arithmetic is deliberately not imported from the executor."""
    current, history, prior = record["events"][2], record["events"][1], record["events"][0]
    source = record["sources"]
    if operation is None:
        return None, []
    if operation == "current":
        return current, [source[str(LATEST)]]
    if operation == "history":
        return history, [source[str(AT)]]
    if operation == "change":
        return current - prior, [source[str(LATEST)], source[str(SINCE)]]
    if operation in ("semantic", "procedure"):
        return record[operation], [source[operation]]
    if operation == "apply":
        program, semantic = record["procedure"], record["semantic"]
        opcode, bias, factor, limit = program["opcode"], program["bias"], semantic["factor"], program["limit"]
        result = {
            "identity": current,
            "add_bias": current + bias,
            "multiply": current * factor,
            "affine": current * factor + bias,
            "clamp": sorted([-limit, current * factor + bias, limit])[1],
        }[opcode]
        return result, [source[str(LATEST)], source["semantic"], source["procedure"]]
    raise ValueError("unknown gold operation")
