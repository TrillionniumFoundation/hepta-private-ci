#!/usr/bin/env python3
"""Link the fixture generator to an already built, exact old SDK checkout."""

import argparse
import hashlib
import json
import shlex
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--target-dir", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
repo, target, output = (p.resolve() for p in (args.repo, args.target_dir, args.output))
if output.exists():
    parser.error("output must not exist; never regenerate over the checked-in fixture")
source = Path(__file__).with_name("generator.rs").resolve()
logs = output.with_name(output.name + "-generator")
logs.mkdir(parents=True, exist_ok=False)
deps = target / "debug/deps"
fingerprints = target / "debug/.fingerprint"
rustc = ["rustup", "run", "1.95.0", "rustc"]


def git(*argv):
    return subprocess.check_output(["git", "-C", str(repo), *argv], text=True).strip()


commit = git("rev-parse", "HEAD")
expected_trees = {
    "codex-rs/hepta-matrix-sdk": "4e44163267e68183b7bc52f0330f8938bfa4356d",
    "codex-rs/third_party/matrix-sdk-sqlite-0.18.0": "e574621565ebecc51e359f94c2a68883696b8948",
}
for path, expected in expected_trees.items():
    if git("rev-parse", f"HEAD:{path}") != expected:
        raise RuntimeError(f"unexpected old source tree: {path}")
lock_hash = hashlib.sha256((repo / "codex-rs/Cargo.lock").read_bytes()).hexdigest()
if lock_hash != "8354b4cbdf14389db7aa5508e2ed5b524fc2d4c4ea0ecb475955c933f8bea389":
    raise RuntimeError("old Cargo.lock differs from the original fixture graph")
if git("status", "--porcelain", "--untracked-files=no"):
    raise RuntimeError("old checkout has modified tracked files")


def fingerprint_path(library):
    suffix = library.stem.rsplit("-", 1)[1]
    matches = list(fingerprints.glob(f"*-{suffix}"))
    if len(matches) != 1:
        raise RuntimeError(f"missing or ambiguous Cargo fingerprint for {library.name}")
    name = library.stem[3:].rsplit("-", 1)[0]
    return matches[0] / f"lib-{name}"


def dependency(parent, name):
    metadata = json.loads(fingerprint_path(parent).with_suffix(".json").read_text())
    expected = next(row[3] for row in metadata["deps"] if row[1] == name)
    matches = []
    for path in deps.glob(f"lib{name}-*.rlib"):
        value = fingerprint_path(path).read_text().strip()
        if int.from_bytes(bytes.fromhex(value), "little") == expected:
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError(f"cannot select the exact {name} used by {parent.name}")
    return matches[0]


sdk = list(deps.glob("libmatrix_sdk-*.rlib"))
if len(sdk) != 1:
    raise RuntimeError("use a separate target directory with one old matrix_sdk build")
libraries = {"matrix_sdk": sdk[0]}
for name in (
    "matrix_sdk_crypto",
    "matrix_sdk_sqlite",
    "matrix_sdk_base",
    "ruma",
    "serde_json",
    "tokio",
):
    libraries[name] = dependency(sdk[0], name)
libraries["vodozemac"] = dependency(libraries["matrix_sdk_crypto"], "vodozemac")
records = []


def run(name, command):
    command = [str(part) for part in command]
    with (logs / f"{name}.log").open("w") as log:
        log.write("$ " + shlex.join(command) + "\n")
        log.flush()
        result = subprocess.run(
            command, cwd=repo, stdout=log, stderr=subprocess.STDOUT, check=False
        )
        log.write(f"\nexit_status={result.returncode}\n")
    records.append({"name": name, "argv": command, "exit_status": result.returncode})
    (logs / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
    result.check_returncode()


run("rustc-version", rustc + ["--version", "--verbose"])
command = rustc + ["--edition=2024", "-C", "debuginfo=0", "-L", f"dependency={deps}"]
for name, library in libraries.items():
    command += ["--extern", f"{name}={library}"]
for native in sorted(
    {path.parent for path in (target / "debug/build").glob("*/out/*.a")}
):
    command += ["-L", f"native={native}"]
binary = logs / "generate-old-fixture"
run("compile-generator", command + [source, "-o", binary])
run("generate", [binary, "generate", output, commit])
run("reopen-verify", [binary, "verify", output])
nonempty_wals = [p.name for p in output.rglob("*-wal") if p.stat().st_size]
if nonempty_wals:
    raise RuntimeError(
        f"SQLite still has committed WAL data; do not copy only main files: {nonempty_wals}"
    )
files = {
    str(path.relative_to(output)): {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    for path in sorted(output.rglob("*"))
    if path.is_file() and not path.name.endswith(("-wal", "-shm"))
}
(logs / "provenance.json").write_text(
    json.dumps(
        {
            "source_commit": commit,
            "cargo_lock_sha256": lock_hash,
            "generator_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "libraries": {name: str(path) for name, path in libraries.items()},
            "files": files,
        },
        indent=2,
    )
    + "\n"
)
print(f"Generated and independently reopened synthetic old SDK data in {output}")
print(f"Commands, exit statuses and hashes: {logs}")
