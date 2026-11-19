"""Read every retained coordinate without importing any reference producer."""

from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import resource
import struct
import time
import zipfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def check(condition, message):
    if not condition:
        raise ValueError(message)


def capsule(raw):
    check(raw[:8] == b"HCSNFSP2" and len(raw) < 2**23, "capsule identity and cap")
    check(hashlib.sha256(raw[:-32]).digest() == raw[-32:], "wire digest")
    data, position = raw[:-32], 8

    def take(count):
        nonlocal position
        check(0 <= count <= len(data) - position, "wire cursor")
        output = data[position:position + count]
        position += count
        return output

    def integer(width):
        return int.from_bytes(take(width), "big")

    def metadata():
        return json.loads(take(integer(4)))

    def tensor():
        rank = integer(4)
        check(1 <= rank <= 3, "wire tensor rank")
        shape = [integer(8) for _ in range(rank)]
        count = integer(8)
        check(count == 8 * math.prod(shape) and count <= 2**23, "wire tensor size")
        return shape, take(count)

    identity = metadata()
    fields = {}
    count = integer(4)
    check(count == 5, "five state blocks")
    for _ in range(count):
        key = "state/" + take(integer(4)).decode()
        check(key not in fields, "unique wire field")
        fields[key] = tensor()
    packets = []
    count = integer(4)
    check(count == 9, "nine packets")
    for _ in range(count):
        packet = metadata()
        packets.append(packet)
        for name in ("alpha", "generator", "output"):
            key = "packet/" + packet["identity"] + "/" + name
            check(key not in fields, "unique packet field")
            fields[key] = tensor()
    check(position == len(data), "complete wire consumption")
    return identity, packets, fields


def main():
    start, cpu = time.perf_counter(), time.process_time()
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        raw = (REPO / name).read_bytes()
        check(len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"], "source/input binding: " + name)
    dense_path = next(name for name in freeze["files"] if name.endswith("/originals/N256_WARM1.bin"))
    sparse_path = next(name for name in freeze["files"] if name.endswith("/artifact-14501927547.zip"))
    with zipfile.ZipFile(io.BytesIO((REPO / sparse_path).read_bytes())) as archive:
        names = [name for name in archive.namelist() if name.endswith("N256_WARM1_SPARSE.bin")]
        check(len(names) == 1, "single sparse wire payload")
        sparse = archive.read(names[0])
    originals = {"dense": (REPO / dense_path).read_bytes(), "sparse": sparse}
    evidence = HERE / "evidence" / "attempt001"
    result = json.loads((evidence / "RESULT.json").read_text())
    retained = json.loads((evidence / "REFERENCE_COORDINATES.json").read_text())
    cost = json.loads((evidence / "COST.json").read_text())
    check(cost["exit_code"] == 0 and not cost["deadline_kill_sent"], "successful bounded child")
    check(cost["child_cpu_seconds"] < 595 and cost["whole_child_wall_upper_seconds"] < 650, "declared work limits")
    check(len(list(evidence.glob("ACTION-*.json"))) == result["reference_actions"] <= 6, "complete reference-action roster")
    fields = {}
    for field in retained["fields"]:
        name = field["name"]
        check(name not in fields, "unique retained field")
        check(math.prod(field["shape"]) == field["coordinates"], "retained tensor shape")
        if field["kind"] == "exact_binary64_point":
            raw = bytes.fromhex(field["payload_hex"])
            check(len(raw) == 8 * field["coordinates"] and hashlib.sha256(raw).hexdigest() == field["sha256"], "point payload")
            values = [value[0] for value in struct.iter_unpack("<d", raw)]
            check(all(map(math.isfinite, values)), "finite point tensors")
            bounds = [(Fraction.from_float(value), Fraction.from_float(value)) for value in values]
        else:
            check(field["kind"] == "exact_rational_enclosures", "retained encoding")
            bounds = [(Fraction(a), Fraction(b)) for a, b in field["intervals"]]
        check(len(bounds) == field["coordinates"] and all(a <= b for a, b in bounds), "ordered complete enclosure")
        fields[name] = field["shape"], bounds
    total = sum(len(bounds) for _, bounds in fields.values())
    width = max(b - a for _, bounds in fields.values() for a, b in bounds)
    check(total == 69728 and width <= Fraction(1, 2**120), "full-coordinate width gate")
    outcomes = {}
    unresolved = []
    for arm, raw in originals.items():
        identity, packets, actual = capsule(raw)
        check(identity["input_bundle_sha256"] == freeze["input_bundle_sha256"] and identity["time"] == "1/1000", "same first-step identity")
        check(packets == retained["packet_metadata"] and set(actual) == set(fields), "complete semantic roster")
        low_sum = high_sum = low_max = high_max = Fraction(0)
        unique = mismatches = 0
        for name, (shape, bounds) in fields.items():
            actual_shape, tensor = actual[name]
            check(shape == actual_shape, "matching archive shape")
            for index, ((a, b), (number,)) in enumerate(zip(bounds, struct.iter_unpack("<d", tensor))):
                check(math.isfinite(number), "finite original coordinate")
                value = Fraction.from_float(number)
                lo = max(Fraction(0), a - value, value - b)
                hi = max(abs(value - a), abs(value - b))
                low_sum += lo
                high_sum += hi
                low_max, high_max = max(low_max, lo), max(high_max, hi)
                # Native Fraction -> binary64 provides a separate implementation
                # from the producer's integer exponent/mantissa conversion.
                first, last = struct.pack("<d", float(a)), struct.pack("<d", float(b))
                if first == last:
                    unique += 1
                    mismatches += first != tensor[8*index:8*index+8]
                elif arm == "dense":
                    unresolved.append({"field": name, "index": index})
        expected = result["final_level"]["comparisons"][arm]["aggregate"]
        exact = {"maximum_absolute_error_lower": low_max, "maximum_absolute_error_upper": high_max,
                 "sum_absolute_error_lower": low_sum, "sum_absolute_error_upper": high_sum}
        check(all(value == Fraction(expected[key]) for key, value in exact.items()), "independent exact error arithmetic")
        check(unique == expected["unique_rounding"] and mismatches == expected["correctly_rounded_mismatches_on_unique_coordinates"], "independent binary64 rounding")
        outcomes[arm] = {"coordinates": total, "unique_rounding": unique, "correct_rounding_mismatches": mismatches,
                         "exact_bounds": {key: str(value) for key, value in exact.items()},
                         "approximate_bounds": {key: float(value) for key, value in exact.items()},
                         "new_absolute_error_diagnostics_pass": high_max <= Fraction(1, 10**12) and high_sum <= Fraction(1, 10**9)}
    check(result["old_sparse_dense_bitwise_gate"] == "RED_UNCHANGED" and result["all_closed"] is False, "original outcome preserved")
    inventory = {str(path.relative_to(evidence)): {"bytes": path.stat().st_size,
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(evidence.rglob("*")) if path.is_file()}
    return {"status": "VERIFIED_ALL_COORDINATE_BOUNDS_AND_ROUNDING_ARITHMETIC", "outcomes": outcomes,
            "maximum_width_exact": str(width), "maximum_width_approximate": float(width),
            "unresolved_unique_rounding": unresolved, "unresolved_unique_rounding_count": len(unresolved),
            "source_files_verified": len(freeze["files"]), "complete_original_inventory": inventory,
            "reference_actions_executed_by_reader": 0, "candidate_calls": 0, "optimizer_calls": 0,
            "body_wall_seconds": time.perf_counter() - start, "body_cpu_seconds": time.process_time() - cpu,
            "whole_process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "scope": "Independent original-wire decode, all retained bounds and exact error/rounding arithmetic; does not rerun or independently regenerate the interval series.", "all_closed": False}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, allow_nan=False))
