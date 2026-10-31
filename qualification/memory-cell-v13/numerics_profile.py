"""Capture and require a comparable NumPy baseline profile before continuation.

This is an execution-profile experiment, not a diagnosis of the first CI run.
The unchanged migration verifier remains responsible for exact training state.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np
from numpy.lib.introspect import opt_func_info


FUNCTIONS = ("tanh", "exp", "sqrt", "add", "subtract", "multiply", "divide")
THREAD_ENV = {"OPENBLAS_CORETYPE": "NEHALEM", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
SCHEMA = "hepta.memory.numerics-profile.v13"


def digest(path):
    with Path(path).open("rb") as stream:
        return {"bytes": Path(path).stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(common):
    errors = []
    if common["numpy"] != "2.3.5":
        errors.append("NumPy version differs from the qualified dependency")
    if common["enabled_dispatch"] or not all(common["effective_baseline"].values()):
        errors.append("nonbaseline CPU dispatch remains enabled or baseline is unavailable")
    disabled = set(common["environment"]["NPY_DISABLE_CPU_FEATURES"].split(","))
    if disabled != set(common["compiled_dispatch"]):
        errors.append("disabled features do not exactly cover this wheel's dispatch list")
    if any(common["environment"].get(k) != v for k, v in THREAD_ENV.items()):
        errors.append("BLAS core or thread environment differs from the required profile")
    baseline = "baseline(" + " ".join(common["compiled_baseline"]) + ")"
    kernels = common["float64_kernels"]
    if set(kernels) != set(FUNCTIONS) or any(not signatures or any(
            entry["current"] != baseline for entry in signatures.values()) for signatures in kernels.values()):
        errors.append("required float64 ufunc kernels are not all baseline")
    if not common["openblas_libraries"]:
        errors.append("bundled OpenBLAS shared library was not found")
    return errors


def capture(role):
    core = np._core._multiarray_umath
    baseline, dispatch = list(core.__cpu_baseline__), list(core.__cpu_dispatch__)
    flags = {key: bool(value) for key, value in core.__cpu_features__.items()}
    library_dir = Path(np.__file__).resolve().parent.parent / "numpy.libs"
    libraries = sorted(library_dir.glob("*openblas*.so*"))
    common = dict(numpy=np.__version__, compiled_baseline=baseline, compiled_dispatch=dispatch,
                  effective_baseline={k: flags[k] for k in baseline},
                  effective_dispatch={k: flags[k] for k in dispatch},
                  enabled_dispatch=[k for k in dispatch if flags[k]],
                  float64_kernels=opt_func_info(func_name=r"^(tanh|exp|sqrt|add|subtract|multiply|divide)$", signature="float64"),
                  environment={k: os.environ.get(k, "") for k in (*THREAD_ENV, "NPY_DISABLE_CPU_FEATURES")},
                  numpy_core=digest(core.__file__), openblas_libraries={p.name: digest(p) for p in libraries},
                  capture_script=digest(__file__), python=platform.python_version(),
                  python_implementation=platform.python_implementation(), python_compiler=platform.python_compiler(),
                  libc=list(platform.libc_ver()), system=platform.system(), machine=platform.machine(),
                  source_commit=os.environ.get("GITHUB_SHA"), run_id=os.environ.get("GITHUB_RUN_ID"),
                  run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"))
    boot = Path("/proc/sys/kernel/random/boot_id")
    cpu = Path("/proc/cpuinfo")
    details = {}
    for line in cpu.read_text().split("\n\n", 1)[0].splitlines() if cpu.exists() else []:
        key, _, value = line.partition(":")
        if key.strip() in ("vendor_id", "model name", "flags"):
            details[key.strip()] = value.strip()
    errors = validate(common)
    return dict(schema=SCHEMA, role=role, passed=not errors, errors=errors, comparable=common,
                comparable_sha256=canonical_sha(common), observed=dict(
                    hostname=platform.node(), platform=platform.platform(), cpu=details, cpu_features=flags,
                    boot_id=boot.read_text().strip() if boot.exists() else None,
                    job=os.environ.get("GITHUB_JOB"), pid=os.getpid(), executable=sys.executable,
                    numpy_core_path=core.__file__, openblas_paths=[str(p) for p in libraries]))


def compare(paths):
    profiles = [json.loads(Path(p).read_text()) for p in paths]
    errors = []
    for role, path, profile in zip(("prepare", "resume", "verify"), paths, profiles):
        if profile.get("schema") != SCHEMA or profile.get("role") != role:
            errors.append(role + ": wrong profile schema or role")
        if profile.get("passed") is not True:
            errors.append(role + ": capture did not pass")
        errors.extend(role + ": " + error for error in validate(profile["comparable"]))
        if profile["comparable_sha256"] != canonical_sha(profile["comparable"]):
            errors.append(role + ": comparable hash mismatch")
        if profile["observed"].get("job") not in (None, role):
            errors.append(role + ": CI job differs from capture role")
    first = profiles[0]["comparable"]
    differing = sorted({k for p in profiles[1:] for k in set(first) | set(p["comparable"])
                        if first.get(k) != p["comparable"].get(k)})
    if differing:
        errors.append("numerical profiles differ: " + ", ".join(differing))
    return dict(schema=SCHEMA + ".comparison", passed=not errors, errors=errors, differing_fields=differing,
                profiles=[dict(role=p["role"], profile_file=digest(path), comparable_sha256=p["comparable_sha256"],
                               boot_id=p["observed"]["boot_id"], path=str(path)) for path, p in zip(paths, profiles)],
                scope="Effective numerical profile only; unchanged migration.py must independently pass bit-exact state checks.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("capture", "compare"))
    parser.add_argument("--role", choices=("prepare", "resume", "verify"))
    parser.add_argument("--profiles", nargs=3, metavar=("PREPARE", "RESUME", "VERIFY"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.phase == "capture" and not args.role or args.phase == "compare" and not args.profiles:
        parser.error("capture requires --role; compare requires three --profiles in role order")
    result = capture(args.role) if args.phase == "capture" else compare(args.profiles)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(phase=args.phase, passed=result["passed"], errors=result["errors"])))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
