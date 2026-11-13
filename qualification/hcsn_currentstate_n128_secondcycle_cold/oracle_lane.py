"""Fresh-process independent dense lane for the N128 second-cycle capsule."""

import argparse
import hashlib
import json
import struct
from fractions import Fraction as F
from pathlib import Path

from qualification.hcsn_currentstate_n128_secondcycle_warm import oracle_warm


CANONICAL = ((F(201, 1000), 5), (F(7, 25), 6), (F(9, 25), 7))


def coordinates(capsule):
    yield from capsule["state"]
    for packet in capsule["packets"]:
        yield from packet["alpha"].flat
        for row in packet["generator"]:
            yield from row
        yield from packet["output"]


def write_raw(path, values):
    digest = hashlib.sha256()
    count = 0
    buffer = bytearray()
    with Path(path).open("wb") as handle:
        for value in values:
            raw = struct.pack("<d", value)
            buffer.extend(raw)
            digest.update(raw)
            count += 1
            if len(buffer) >= 1 << 20:
                handle.write(buffer)
                buffer.clear()
        handle.write(buffer)
    return count, digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    for name in ("start", "law", "metadata", "npz", "output"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--query", action="append", nargs=3, metavar=("NUM", "DEN", "ORDER"), required=True)
    args = parser.parse_args()
    requested = tuple((F(int(num), int(den)), int(order)) for num, den, order in args.query)
    requested_orders = {order for _, order in requested}
    limit = max(query for query, _ in requested)
    schedule = tuple(row for row in CANONICAL if row[0] <= limit)
    oracle_warm.QUERIES = tuple(query for query, _ in schedule)
    capsules, cost = oracle_warm.run(args.start, args.law, args.metadata, args.npz)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for (_, order), capsule in zip(schedule, capsules):
        if order not in requested_orders:
            continue
        count, raw_sha = write_raw(output / f"COORDINATES-{order}.f64le", coordinates(capsule))
        rows.append({"order": order, "coordinates": count, "coordinate_sha256": raw_sha})
    result = {
        "engine": "oracle",
        "requested_queries": [[q.numerator, q.denominator, order] for q, order in requested],
        "canonical_schedule": [[q.numerator, q.denominator, order] for q, order in schedule],
        "outputs": rows,
        "cost": cost,
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
