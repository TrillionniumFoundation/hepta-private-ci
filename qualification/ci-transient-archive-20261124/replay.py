"""Exercise the exact patched wrapper's portable filesystem logic on Linux.

This enables the Windows-only, std-only path consolidation code in a test copy.
It is not a native Windows build or a replacement for Windows CI.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--rules-rust", type=Path, required=True)
parser.add_argument("--rustc", type=Path, required=True)
parser.add_argument("--patch", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
UPSTREAM = args.rules_rust.resolve()
RUSTC = args.rustc.resolve()
PATCH = args.patch.resolve()
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=True)
assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=UPSTREAM, text=True).strip() == "f19661ba71f77c993ce1eb082053692610fe4313"


def run(label, argv, cwd):
    start = time.monotonic()
    result = subprocess.run(argv, cwd=cwd, capture_output=True)
    (OUT / f"{label}.stdout").write_bytes(result.stdout)
    (OUT / f"{label}.stderr").write_bytes(result.stderr)
    return {
        "label": label,
        "argv": [str(arg) for arg in argv],
        "cwd": str(cwd),
        "returncode": result.returncode,
        "seconds": time.monotonic() - start,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
    }


archive = OUT / "tinyjson-2.5.1.crate"
if not archive.exists():
    urllib.request.urlretrieve(
        "https://static.crates.io/crates/tinyjson/tinyjson-2.5.1.crate", archive
    )
assert hashlib.sha256(archive.read_bytes()).hexdigest() == (
    "9ab95735ea2c8fd51154d01e39cf13912a78071c2d89abc49a7ef102a7dd725a"
)
with tarfile.open(archive) as compressed:
    compressed.extractall(OUT, filter="data")
records = []
records.append(
    run(
        "tinyjson-build",
        [RUSTC, "--edition=2018", "--crate-name=tinyjson", "--crate-type=rlib",
         OUT / "tinyjson-2.5.1/src/lib.rs", "-o", OUT / "libtinyjson.rlib"],
        OUT,
    )
)
assert records[-1]["returncode"] == 0, records[-1]

for variant in ["parent", "candidate"]:
    directory = OUT / variant
    shutil.copytree(UPSTREAM / "util/process_wrapper", directory, dirs_exist_ok=True)
    main = (directory / "main.rs").read_text()
    if variant == "parent":
        main = main.replace(
            '                || (file_name_lower.contains(".temp-archive-") && file_name_lower.ends_with(".a"))\n',
            "",
        )
    # The production patch keeps these functions Windows-only. Enable their
    # std-only bodies in the Linux test copy, without changing their logic.
    main = main.replace("#[cfg(windows)]", "#[cfg(any(windows, test))]")
    main = main.replace("#[cfg(not(windows))]", "#[cfg(not(any(windows, test)))]")
    main = main.replace("#[cfg(all(test, windows))]", "#[cfg(test)]")
    (directory / "main.rs").write_text(main)
    records.append(run(
        f"{variant}-build",
        [RUSTC, "--edition=2018", "--test", "main.rs", "--extern",
         f"tinyjson={OUT / 'libtinyjson.rlib'}", "-o", directory / "wrapper-tests"],
        directory,
    ))
    assert records[-1]["returncode"] == 0, records[-1]
    records.append(run(
        f"{variant}-tests", [directory / "wrapper-tests", "--test-threads=1"], directory
    ))

receipt = {
    "upstream_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=UPSTREAM, text=True
    ).strip(),
    "compiler": subprocess.check_output([RUSTC, "-Vv"], text=True),
    "qualification": "Windows std-only consolidation logic enabled in Linux test copy; native Windows CI pending",
    "patch_sha256": hashlib.sha256(PATCH.read_bytes()).hexdigest(),
    "records": records,
}
(OUT / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt, indent=2))
assert records[-3]["returncode"] != 0, "Parent must reproduce the regression"
assert records[-1]["returncode"] == 0, "Candidate must pass the same regression"
