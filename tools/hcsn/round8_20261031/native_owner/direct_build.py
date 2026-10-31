"""Recompile exact research sources against preserved Cargo-built dependencies.

This fallback is deliberately distinct from a fresh Cargo build. It verifies
the pinned upstream source, matches direct dependencies to the successful
Cargo binary's fingerprints, hashes all available rlib/rmeta/proc-macro inputs,
then compiles and runs the current Rust tests. It does not reverify deleted
registry archives or manufacture vendor checksums.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from build import prepare, run


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dependencies(target, fingerprint):
    root = target / "debug/.fingerprint"
    selected, matched = {}, {}
    record = json.loads(fingerprint.read_text())
    for _, name, _, digest in record["deps"]:
        candidates = []
        for candidate in root.glob("*/lib-"+name):
            if int.from_bytes(bytes.fromhex(candidate.read_text()), "little") == digest:
                suffix = candidate.parent.name.rsplit("-", 1)[1]
                artifact = target / "debug/deps" / ("lib"+name+"-"+suffix+".rlib")
                if artifact.is_file():
                    candidates.append((artifact, candidate))
        if len(candidates) != 1:
            raise ValueError(("ambiguous or missing preserved Cargo dependency", name))
        artifact, candidate = candidates[0]
        selected[name] = artifact
        matched[name] = dict(artifact=str(artifact), sha256=sha(artifact),
            cargo_fingerprint=str(candidate), fingerprint=candidate.read_text(),
            dependency_record=json.loads(candidate.with_suffix(".json").read_text()))
    inventory = {str(path): sha(path) for path in sorted((target/"debug/deps").iterdir())
                 if path.suffix in (".rlib", ".rmeta", ".so")}
    return selected, matched, inventory


def main(args):
    prior = json.loads(args.prior_report.read_text())
    if not prior["success"] or any(row["returncode"] for row in prior["commands"]):
        raise ValueError("prior Cargo/just report did not pass")
    if sha(Path(prior["binary"])) != prior["binary_sha256"]:
        raise ValueError("preserved prior Cargo binary identity changed")
    build, upstream, owned, digest, manifest = prepare(args)
    if upstream != prior["source_files"]:
        raise ValueError("native upstream differs from successful Cargo build")
    target = args.existing_build / "target"
    selected, matched, inventory = dependencies(target, args.prior_fingerprint)
    env = os.environ.copy()
    env.update(PATH=str(args.toolchain/"bin")+":"+env["PATH"],
               HEPTA_TASK_NATIVE_SOURCE_DIGEST=digest)
    rustc = str(args.toolchain/"bin/rustc")
    binary, test = build/"native-owner-final", build/"native-owner-tests-final"
    common = [rustc, "--edition=2024", "--crate-name", "codex_native_event_owner_r8",
              "-C", "debuginfo=0", "-C", "opt-level=0", "-L", "dependency="+str(target/"debug/deps")]
    for name, artifact in selected.items():
        common.extend(["--extern", name+"="+str(artifact)])
    commands = [run([rustc, "--version", "--verbose"], build, env)]
    if commands[0]["stdout"] != prior["commands"][0]["stdout"]:
        raise ValueError("compiler changed from preserved Cargo build")
    for command in (common+["main.rs", "-o", str(binary)],
                    common+["--test", "main.rs", "-o", str(test)],
                    [str(test), "--test-threads=1", "--nocapture"]):
        if all(row["returncode"] == 0 for row in commands):
            commands.append(run(command, build, env))
    unchanged = all(sha(Path(path)) == digest for path, digest in inventory.items())
    result = dict(schema="hcsn.native-event-owner-direct-build.v1",
        success=len(commands) == 4 and all(row["returncode"] == 0 for row in commands) and unchanged,
        source_digest=digest, source_files=upstream, owned_files=owned,
        binary=str(binary), binary_sha256=sha(binary) if binary.is_file() else None,
        test_binary_sha256=sha(test) if test.is_file() else None,
        prior_cargo_build=dict(path=str(args.prior_report), sha256=sha(args.prior_report),
            source_digest=prior["source_digest"], binary_sha256=prior["binary_sha256"]),
        prior_fingerprint=dict(path=str(args.prior_fingerprint), sha256=sha(args.prior_fingerprint),
            record=json.loads(args.prior_fingerprint.read_text())),
        selected_dependencies=matched, dependency_artifact_sha256=inventory,
        dependency_artifacts_unchanged_during_build=unchanged,
        manifest=manifest, prior_cargo_lock=prior["derived_lock"], commands=commands,
        fresh_cargo_archive_verification=False, final_source_just_test_rerun=False,
        final_source_rustc_tests_run=True,
        scope="Exact current sources compiled and tested with rustc against preserved Cargo-built rlibs; original Cargo/just gate retained separately",
        production_activation=False)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({key: result[key] for key in ("success", "source_digest", "binary")}))
    for command in commands:
        if command["returncode"]:
            print(command["stdout"]+command["stderr"])
    return result["success"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("build", "existing-build", "toolchain", "prior-report", "prior-fingerprint", "report"):
        p.add_argument("--"+key, type=Path, required=True)
    raise SystemExit(0 if main(p.parse_args()) else 1)
