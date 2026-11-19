"""Map independent action enclosures to every original warm-1 coordinate."""

from fractions import Fraction as F
import hashlib
import math
import struct

from inputs import BUNDLE, fp_bytes, source_id
from interval import exact_from_bits, require, rounded_fraction


def point(x):
    return x, x


def build(inputs, assembly, ordinary, discounted, upper_occupation):
    blocks = {"active": [], "upper": [], "mass": [], "discounted_hit": [], "occupation": []}
    for c in range(5):
        blocks["active"].extend(ordinary[c][1:256]+[point(F(0))]*255)
        blocks["upper"].extend([point(inputs["channels"][c][-1]), ordinary[c][256], point(F(0))])
        blocks["mass"].extend([ordinary[c][257], point(F(0))])
        blocks["discounted_hit"].extend([discounted[c][257], point(F(0))])
        blocks["occupation"].extend([upper_occupation[c], discounted[c][258], point(F(0))])
    shapes = {"active": (5, 2, 255), "upper": (5, 3), "mass": (5, 2),
              "discounted_hit": (5, 2), "occupation": (5, 3)}
    fields = [{"name": "state/"+name, "shape": shapes[name], "bounds": blocks[name]}
              for name in sorted(blocks)]
    packets = []
    for packet in inputs["packets"]:
        metadata = {"identity": packet["identity"], "generation": 1, "origin": 0, "target": 1,
                    "start": "1/1000" if packet["start"] == 0 else str(packet["start"]), "end": str(packet["end"])}
        # These are coefficients of the original constant source; B[:,0]=0
        # gives an exact invariant. Retain the computed parent enclosure too.
        if packet["start"] == 0:
            for c in range(5):
                require(ordinary[c][0][0] <= packet["rates"][c] <= ordinary[c][0][1], "exact residual-parent invariant")
        packets.append((metadata, {"alpha": ((5, 1), list(map(point, packet["rates"]))),
                                   "generator": ((1, 1), [point(F(0))]), "output": ((1,), [point(F(1))])}))
    emitted_id = source_id("lower-flux", F(0), F(1, 1000), 2, 1, (assembly["parent"]["identity"],))
    metadata = {"identity": emitted_id, "generation": 2, "origin": 1, "target": 2, "start": "1/5", "end": "201/1000"}
    core = [row.get(j, F(0)) for row in assembly["core"] for j in range(256)]
    packets.append((metadata, {"alpha": ((5, 256), list(map(point, [x for v in assembly["alpha"] for x in v]))),
                               "generator": ((256, 256), list(map(point, core))),
                               "output": ((256,), list(map(point, assembly["output"])))}))
    packets.sort(key=lambda item: item[0]["identity"])
    for metadata, values in packets:
        for name in ("alpha", "generator", "output"):
            shape, bounds = values[name]
            fields.append({"name": f"packet/{metadata['identity']}/{name}", "shape": shape, "bounds": bounds})
    require(sum(len(f["bounds"]) for f in fields) == 69728, "complete target coordinates")
    return fields, [metadata for metadata, _ in packets]


def compare(fields, packet_metadata, outputs):
    result = {}
    for arm, capsule in outputs.items():
        require(capsule["metadata"] == {"schema": "hcsn-fullstate-packet-v2", "input_bundle_sha256": BUNDLE,
                "capsule_identity": "af3119de18a4f2f9049fd4f33c2331448237cb1c90810f6cdf2f2bedaa5bf7c1",
                "lane": "warm", "lane_order": 1, "time": "1/1000"}, "target metadata")
        require([p["metadata"] for p in capsule["packets"]] == packet_metadata, "packet semantics")
        actual = {"state/"+name: value for name, value in capsule["blocks"].items()}
        for packet in capsule["packets"]:
            for name in ("alpha", "generator", "output"):
                actual[f"packet/{packet['metadata']['identity']}/{name}"] = packet[name]
        require(set(actual) == {f["name"] for f in fields}, "all coordinate surfaces")
        families, mismatches = {}, 0
        for field in fields:
            row = actual[field["name"]]
            require(row["shape"] == field["shape"] and len(row["values"]) == len(field["bounds"]), "coordinate shapes")
            family = field["name"] if field["name"].startswith("state/") else "packet/"+field["name"].rsplit("/", 1)[1]
            stats = families.setdefault(family, {"coordinates": 0, "unique_rounding": 0, "correctly_rounded_matches": 0,
                "maximum_absolute_error_lower": F(0), "maximum_absolute_error_upper": F(0),
                "sum_absolute_error_lower": F(0), "sum_absolute_error_upper": F(0)})
            for index, (value, (lo, hi)) in enumerate(zip(row["values"], field["bounds"])):
                require(lo <= hi, "ordered mathematical target")
                lower = max(F(0), lo-value, value-hi)
                upper = max(abs(value-lo), abs(value-hi))
                stats["coordinates"] += 1
                stats["maximum_absolute_error_lower"] = max(stats["maximum_absolute_error_lower"], lower)
                stats["maximum_absolute_error_upper"] = max(stats["maximum_absolute_error_upper"], upper)
                stats["sum_absolute_error_lower"] += lower
                stats["sum_absolute_error_upper"] += upper
                left, right = rounded_fraction(lo), rounded_fraction(hi)
                if left == right:
                    stats["unique_rounding"] += 1
                    matches = struct.unpack("<Q", row["raw"][8*index:8*index+8])[0] == left
                    stats["correctly_rounded_matches"] += matches
                    mismatches += not matches
        aggregate = {"coordinates": sum(f["coordinates"] for f in families.values()),
                     "unique_rounding": sum(f["unique_rounding"] for f in families.values()),
                     "correctly_rounded_mismatches_on_unique_coordinates": mismatches,
                     "maximum_absolute_error_lower": max(f["maximum_absolute_error_lower"] for f in families.values()),
                     "maximum_absolute_error_upper": max(f["maximum_absolute_error_upper"] for f in families.values()),
                     "sum_absolute_error_lower": sum((f["sum_absolute_error_lower"] for f in families.values()), F(0)),
                     "sum_absolute_error_upper": sum((f["sum_absolute_error_upper"] for f in families.values()), F(0))}
        aggregate["new_finite_matrix_absolute_gate"] = (aggregate["maximum_absolute_error_upper"] <= F(1, 10**12)
                                                        and aggregate["sum_absolute_error_upper"] <= F(1, 10**9))
        result[arm] = {"aggregate": aggregate, "families": families}
    return result


def encoded_fields(fields):
    """All coordinates retained; exact static tensors use compact FP64 bytes."""
    output = []
    for field in fields:
        bounds = field["bounds"]
        row = {"name": field["name"], "shape": field["shape"], "coordinates": len(bounds)}
        if all(lo == hi for lo, hi in bounds):
            require(all(exact_from_bits(rounded_fraction(lo)) == lo for lo, _ in bounds), "static point must be exact binary64")
            payload = fp_bytes([lo for lo, _ in bounds])
            row.update(kind="exact_binary64_point", payload_hex=payload.hex(), sha256=hashlib.sha256(payload).hexdigest())
        else:
            row.update(kind="exact_rational_enclosures", intervals=[[str(lo), str(hi)] for lo, hi in bounds])
        output.append(row)
    return output
