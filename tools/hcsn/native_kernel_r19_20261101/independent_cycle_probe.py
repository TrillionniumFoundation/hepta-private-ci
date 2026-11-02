"""Independent closed-form cycle probe, stdlib only; no project law imports."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess


def request(commands):
    q = [[0.] * 40 for _ in range(40)]
    q[0][0], q[0][32], q[32][32], q[32][0] = -2., 2., -3., 3.
    values = ["HCSN_FINITE_40_V1"]
    values += [repr(x) for row in q for x in row]
    values += [repr(.2)] * 200 + [repr(.25)] * 160
    values += ["1"] + ["0"] * 39
    return (" ".join(values) + "\n" + "\n".join(commands) + "\n").encode()


def main(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    records, maximum = [], 0.
    for t in [0., 1e-12, .01, .7, 1., 2., 20.]:
        data = request([f"DIAG {t:.17e}"])
        process = subprocess.run([str(args.binary)], input=data, capture_output=True)
        assert process.returncode == 0
        got = json.loads(process.stdout)
        future = [0.] * 40
        future[0] = .6 + .4 * math.exp(-5 * t)
        future[32] = -.4 * math.expm1(-5 * t)
        survivor = [0.] * 40
        survivor[0] = math.exp(-2 * t)
        expected = dict(future=future, survivor=survivor,
                        first=-math.expm1(-2 * t),
                        events=1.2 * t - .16 * math.expm1(-5 * t))
        errors = {name: max(abs(a-b) for a,b in zip(got[name], values))
                  if isinstance(values, list) else abs(got[name] - values)
                  for name, values in expected.items()}
        maximum = max(maximum, *errors.values())
        records.append(dict(time=t, input=data.decode(), stdout=process.stdout.decode(),
                            stderr=process.stderr.decode(), expected=expected, errors=errors))
    result = dict(scope="independent closed-form two-state cycle embedded in 40 states; not full model qualification",
                  source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                  binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                  cases=7, maximum_absolute_error=maximum, tolerance=2e-11,
                  passed=maximum <= 2e-11, records=records)
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k:v for k,v in result.items() if k != "records"}))
    assert result["passed"]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    main(p.parse_args())
