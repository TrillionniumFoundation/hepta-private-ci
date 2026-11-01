"""Exercise result enforcement using archived successes and corrupted copies."""

import copy
import hashlib
import json
from pathlib import Path

from verify_regression import read, verify


def main():
    root = Path(__file__).resolve().parent
    capsule = root / "capsule"
    original = [read(capsule / name) for name in (
        "COMP_PRIMITIVES01.json", "COMP_ATTEMPT01_FULL.json.gz",
        "R16_HOLDOUT_V1.json.gz")]
    valid = verify(capsule, *original)
    checks = [{"name": "complete archived results accepted", "passed": True}]

    def rejects(name, mutate):
        data = copy.deepcopy(original)
        mutate(data)
        try:
            verify(capsule, *data)
        except (ValueError, KeyError, TypeError) as error:
            checks.append({"name": name, "rejected": True, "reason": str(error)})
        else:
            raise AssertionError("Invalid result accepted: " + name)

    rejects("missing development row", lambda d: d[1]["rows"].pop())
    rejects("nonfinite output", lambda d: d[1]["rows"][0]["values"].__setitem__(0, float("nan")))
    rejects("out of tolerance output with pass flag",
            lambda d: d[1]["rows"][0]["values"].__setitem__(0, 1e12))
    rejects("missing derivative column", lambda d: d[1]["rows"][0]["jacobian"][0].pop())
    rejects("reported failed row", lambda d: d[1]["rows"][0].__setitem__("passed", False))
    rejects("relaxed tolerance", lambda d: d[2]["gates"].__setitem__("value_scaled", 1.0))
    rejects("nonfinite primitive diagnostic",
            lambda d: d[0]["rows"][0].__setitem__("scaled_error", float("nan")))
    rejects("incomplete validation cases", lambda d: d[2]["cases"].pop())
    rejects("empty matching source seals", lambda d: (
        d[2]["source_sha256_before"].clear(), d[2]["source_sha256_after"].clear()))
    rejects("changed validation runner", lambda d: d[2].__setitem__("runner_sha256", "0" * 64))
    rejects("changed validation parameter",
            lambda d: d[2]["cases"][0]["theta"].__setitem__(0, 0.25))
    rejects("reordered validation rows", lambda d: d[2]["rows"].reverse())
    rejects("changed validation state", lambda d: d[2]["rows"][0].__setitem__("state", 1.0))
    rejects("self-consistent changed reference and output", lambda d: (
        d[2]["rows"][0]["reference"].__setitem__(0, 100.0),
        d[2]["rows"][0]["values"].__setitem__(0, 100.0)))
    rejects("changed reference derivative",
            lambda d: d[2]["rows"][0]["reference_jacobian"][0].__setitem__(0, 0.0))
    return {
        "schema": "hcsn.r16.ci-result-gate-review.v2",
        "verifier_sha256": hashlib.sha256((root / "verify_regression.py").read_bytes()).hexdigest(),
        "scope": "Independent enforcement around frozen diagnostic writers; no candidate or tolerance modification. Frozen V1 input order and references are bound to archived results.",
        "valid_result": valid,
        "checks": checks,
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, allow_nan=False))
