"""Build a numerical probe with the existing identified Hepta dependency closure."""
import argparse
import hashlib
import json
from pathlib import Path

from ...task_native_loop_20261031 import build

HERE = Path(__file__).resolve().parent
BINARY = "codex-hcsn-finite-probe"


def main(args):
    target, identity, sources, digest, env, deps, manifest = build.prepare(args)
    manifest += f'\n[[bin]]\nname = "{BINARY}"\npath = {json.dumps(str(HERE / "probe.rs"))}\n'
    (target / "Cargo.toml").write_text(manifest)
    for path in (HERE / "probe.rs", HERE / "probe_tests.rs", Path(__file__).resolve()):
        sources[str(path.relative_to(build.REPO))] = hashlib.sha256(path.read_bytes()).hexdigest()
    commands = [build.execute(["cargo", "build", "--offline", "--manifest-path", str(target / "Cargo.toml"),
                              "--bin", BINARY], target, env)]
    if commands[-1]["returncode"] == 0:
        commands.append(build.execute(["just", "test", "--offline", "--locked", "--manifest-path",
            str(target / "Cargo.toml"), "--config-file", str(target / "nextest.toml"),
            "-p", build.PACKAGE, "--bin", BINARY], build.REPO / "codex-rs", env))
    binary = target / "target/debug" / BINARY
    report = dict(schema="hcsn.finite-probe.build.r11.v1", success=all(c["returncode"] == 0 for c in commands),
                  binary=str(binary), binary_sha256=build.sha(binary.read_bytes()) if binary.is_file() else None,
                  source_sha256=sources, upstream=identity, dependency_sources=deps,
                  all_dependency_archives_verified=all(x["archive_checksum_verified"] for x in deps.values()),
                  source_digest=build.sha(json.dumps(sources, sort_keys=True).encode()),
                  commands=commands, production_activation=False)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps(dict(success=report["success"], binary=str(binary), report=str(args.report))))
    for command in commands:
        if command["returncode"]:
            print(command["stderr"][-6000:])
    return 0 if report["success"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("build", "toolchain", "cargo-cache", "tools", "report"):
        parser.add_argument("--"+key, type=Path, required=True)
    parser.add_argument("--cached-source-fallback", action="store_true")
    raise SystemExit(main(parser.parse_args()))
