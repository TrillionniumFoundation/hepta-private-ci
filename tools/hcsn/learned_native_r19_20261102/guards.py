"""Pre-freeze malformed-profile and near-tie rejection checks."""
import json
from pathlib import Path
import resource
import subprocess
import time

HERE = Path(__file__).resolve().parent


def main():
    started = time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    directory = HERE / "development_04/guard_cases"
    directory.mkdir(exist_ok=False)
    binary = HERE / "development_04/forward"
    light = (HERE / "profiles_v2/191101_light_analytic.model").read_text()
    value = (HERE / "profiles_v2/191101_value_analytic.model").read_text()
    tape = "WORLD 0 1 2 3\nQUERY -1 0 0.75 0 0.03725 0\n"
    cases = []

    def run(name, model, text=tape, reject=True):
        profile, source, output = (directory / f"{name}.{suffix}" for suffix in ("model", "tape", "tsv"))
        profile.write_text(model); source.write_text(text)
        child = subprocess.run([str(binary), str(profile), str(source), str(output)], capture_output=True)
        assert (child.returncode != 0) == reject, (name, child.returncode, child.stderr)
        cases.append(dict(name=name, rejected=reject, stderr=child.stderr.decode()))
        return output

    header = light.splitlines()[0]
    run("nan_threshold", light.replace(header, "\t".join(header.split("\t")[:3] + ["NaN"]), 1))
    row = next(x for x in light.splitlines() if x.startswith("SYMBOL\t"))
    fields = row.split("\t"); fields[1] = "1e300"
    run("fp32_overflow", light.replace(row, "\t".join(fields), 1))
    malformed = light
    for key in ("H2W", "H2B"):
        row = next(x for x in malformed.splitlines() if x.startswith(key + "\t"))
        malformed = malformed.replace(row, key + "\t" + "\t".join("0" for _ in row.split()[1:]), 1)
    run("head_exact_tie", malformed)
    run("valid_value", value, reject=False)
    tied = value
    for key, constant in (("SYMBOL", "0"), ("ENCODED", ".25"), ("EMISSION", ".25")):
        row = next(x for x in tied.splitlines() if x.startswith(key + "\t"))
        tied = tied.replace(row, key + "\t" + "\t".join(constant for _ in row.split()[1:]), 1)
    run("action_near_tie", tied, tape.replace("0.03725", "0"))
    stopped = light.replace(header, "\t".join(header.split("\t")[:3] + ["-1"]), 1)
    valid = run("stop_unpurchased_invalid_token", stopped, tape.replace("0.03725 0", "0.03725 -100"), False)
    assert valid.read_text().split()[0] == "0"
    end = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = dict(status="PASS", cases=cases, cpu_seconds_including_children=time.process_time()-started
        + end.ru_utime + end.ru_stime-child_start.ru_utime-child_start.ru_stime,
        scope="Pre-freeze engineering checks, not formal parity worlds")
    (HERE / "GUARD_CHECKS.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(status="PASS", cases=len(cases))))


if __name__ == "__main__":
    main()
