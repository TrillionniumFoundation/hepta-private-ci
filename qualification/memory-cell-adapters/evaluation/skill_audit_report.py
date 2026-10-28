"""Bound skill audit transport by encoded bytes without changing any result.

The original semantic writer's 500-record batches can exceed 400 kB for richer
skill phase records. This serializer preserves record order and values while
splitting an oversized batch. It does not score evidence or invoke a model.
"""

import hashlib
import json


MAX_BYTES = 400000
SECTIONS = ("checks", "phase_records", "cycle_source_state_identities")


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def write_bounded_report(path, report):
    output = dict(report)
    sections = {name: output.pop(name) for name in SECTIONS}
    output["detail_parts"] = {}
    for name, values in sections.items():
        mapping = isinstance(values, dict)
        entries = list(values.items()) if mapping else list(values)
        inventory = []

        def write_batch(batch):
            number = len(inventory)
            body = {"schema": "hepta.memory.audit-detail-part.v1", "section": name, "part": number,
                    "records": dict(batch) if mapping else batch}
            raw = encoded(body)
            if len(raw) >= MAX_BYTES:
                if len(batch) < 2:
                    raise ValueError("Single audit detail record exceeds byte limit")
                middle = len(batch) // 2
                write_batch(batch[:middle])
                write_batch(batch[middle:])
                return
            part = path.with_name(f"{path.stem}.{name}.{number:03d}.json")
            with part.open("xb") as handle:
                handle.write(raw)
            inventory.append({"file": part.name, "records": len(batch), "bytes": len(raw),
                              "sha256": hashlib.sha256(raw).hexdigest()})

        for start in range(0, len(entries), 500):
            write_batch(entries[start:start + 500])
        output["detail_parts"][name] = inventory
    raw = encoded(output)
    if len(raw) >= MAX_BYTES:
        raise ValueError("Audit summary exceeds byte limit")
    with path.open("xb") as handle:
        handle.write(raw)
