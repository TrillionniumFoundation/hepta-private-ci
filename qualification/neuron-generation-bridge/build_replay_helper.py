#!/usr/bin/env python3
"""Build the unchanged std-only proposal entry, retaining compiler provenance.

This explicit standalone qualification build is separate from Cargo/Bazel gates.
"""

import argparse
from pathlib import Path
import resource
import subprocess
import time

from trained_replay import SOURCE_FILES, require, sha, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "rustc", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    head = subprocess.check_output(["git", "-C", str(args.source_root), "rev-parse", "HEAD"], text=True).strip()
    crate = args.source_root / "codex-rs/hepta-infer-worker-host"
    hashes = {}
    for name in SOURCE_FILES:
        data = (crate / name).read_bytes()
        committed = subprocess.check_output(["git", "-C", str(args.source_root), "show",
                      head + ":codex-rs/hepta-infer-worker-host/" + name])
        require(data == committed, "Uncommitted executable source: " + name)
        hashes[name] = sha(data)
    binary = args.output / "hepta-joint-propose"
    compiler = args.rustc.resolve(strict=True)
    version = subprocess.check_output([str(compiler), "--version", "--verbose"], text=True)
    command = [str(compiler), "--edition=2024", "-C", "opt-level=2",
               str(crate / "src/bin/hepta-joint-propose.rs"), "-o", str(binary)]
    result = subprocess.run(command, capture_output=True)
    (args.output / "build.stdout").write_bytes(result.stdout)
    (args.output / "build.stderr").write_bytes(result.stderr)
    unchanged = all(sha((crate / name).read_bytes()) == value for name, value in hashes.items())
    receipt = {"schema": "hepta.joint-standalone-qualification-build.v1", "source_sha": head,
               "source_files": hashes, "command": command, "exit_code": result.returncode,
               "compiler": version, "compiler_sha256": sha(compiler.read_bytes()),
               "source_unchanged": unchanged,
               "qualification_source_sha256": {name: sha((Path(__file__).parent / name).read_bytes())
                                              for name in ("build_replay_helper.py", "trained_replay.py")},
               "unmeasured": ["energy_joules", "physical_disk_bytes"],
               "scope": "Standalone std-only entry build. No Cargo, Bazel or Agentd gate claim."}
    if result.returncode == 0:
        receipt["executable_sha256"] = sha(binary.read_bytes())
        linked = subprocess.check_output(["ldd", str(binary)], text=True)
        receipt["ldd"] = linked
        libraries = {}
        for token in linked.split():
            path = Path(token)
            if token.startswith("/") and path.is_file():
                libraries[token] = sha(path.read_bytes())
        receipt["linked_library_sha256"] = libraries
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt.update(wall_seconds=time.perf_counter() - started,
                   harness_cpu_seconds=time.process_time() - cpu,
                   child_cpu_seconds=usage_after.ru_utime + usage_after.ru_stime -
                                     usage_before.ru_utime - usage_before.ru_stime)
    write_json(args.output / "BUILD.json", receipt)
    require(result.returncode == 0 and unchanged, "Build failed or source changed")


if __name__ == "__main__":
    main()
