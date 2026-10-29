#!/usr/bin/env python3
"""Measured export and relocation of formal002 without changing frozen sources."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import shutil
import subprocess
import sys
import tarfile
import time


V2_SEAL = "experiments/adaptive_neuron_v2/results/registration001/SOURCE_SEAL.json"
BRIDGE_SEAL = "experiments/adaptive_credit_bridge_v1/results/formal001/SOURCE_SEAL.json"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as target:
        json.dump(value, target, indent=2, sort_keys=True, allow_nan=False)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())


def load(path):
    return json.loads(Path(path).read_text())


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            raise ValueError("Symbolic archive input: " + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            }
    return result


def inventory_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def copy_tree(source, destination):
    before = inventory(source)
    shutil.copytree(source, destination)
    if inventory(destination) != before or inventory(source) != before:
        raise ValueError("Copy changed source or payload: " + str(source))
    return {"files": len(before), "sha256": inventory_digest(before)}


def source_command(source, arguments):
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(source))
    subprocess.run([sys.executable, *arguments], cwd=source, env=environment, check=True)


def original_owner_build(archive, destination, frozen):
    """Retain the original archive's manifest/lock/vendor and reconstruct its inputs."""
    origin = "hepta_adaptive_neuron_v2/exact_evidence/"
    retained = {}
    with tarfile.open(archive) as source:
        declared = json.load(source.extractfile("hepta_adaptive_neuron_v2/ARCHIVE_MANIFEST.json"))["files"]
        for member in source.getmembers():
            if member.name.startswith(origin + "runtime/build01/"):
                relative = member.name.removeprefix(origin + "runtime/build01/")
            elif member.name.startswith(origin + "vendor/"):
                relative = "vendor/" + member.name.removeprefix(origin + "vendor/")
            else:
                continue
            if not member.isfile() or ".." in PurePosixPath(relative).parts:
                raise ValueError("Unsafe original archive member")
            data = source.extractfile(member).read()
            identity = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            if identity != declared[member.name]:
                raise ValueError("Original owner archive manifest mismatch")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(data)
            target.chmod(member.mode & 0o777)
            retained[member.name] = identity
    for name in ("hepta-types", "hepta-infer-core", "hepta-neuron"):
        copy_tree(frozen / "codex-rs" / name, destination / name)
    examples = destination / "hepta-neuron/examples"
    examples.mkdir(exist_ok=True)
    paths = {
        "original_owner.rs": frozen / "codex-rs/hepta-agentd/src/neuron_runtime.rs",
        "original_credit.rs": frozen / "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
        "measure.rs": frozen / "experiments/multimodal_output_portfolio/abc_next/native/measure.rs",
    }
    paths.update({p.name: p for p in (frozen / "experiments/adaptive_neuron_v2/owner").glob("*.rs")})
    for name, path in paths.items():
        shutil.copy2(path, examples / name)
    config = destination / ".cargo/config.toml"
    config.parent.mkdir()
    config.write_text('[source.crates-io]\nreplace-with="vendor"\n[source.vendor]\ndirectory="vendor"\n')
    return {"original_archive_sha256": sha(archive), "retained_members": len(retained),
            "retained_member_manifest_sha256": inventory_digest(retained),
            "source_examples": {name: sha(path) for name, path in paths.items()},
            "scope": "Original build01 Cargo manifest, lock, receipt and vendor; inputs reconstructed from the sealed owner build.py composition. No rebuild is claimed by export."}


def export(args):
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    frozen = args.source_root.resolve()
    sealed = load(frozen / BRIDGE_SEAL)
    source = destination / "source"
    source.mkdir()
    for name, identity in sealed["inputs"].items():
        path = frozen / name
        if path.is_symlink() or sha(path) != identity["sha256"]:
            raise ValueError("Frozen source mismatch: " + name)
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for name in (V2_SEAL, BRIDGE_SEAL):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frozen / name, target)
    # Call the unchanged, source-sealed materializer rather than inventing a Git proof.
    source_command(frozen, ["-c", "from pathlib import Path; from experiments.adaptive_credit_bridge_v1.provenance import materialize_git_proof; import sys; materialize_git_proof(Path(sys.argv[1]),Path(sys.argv[2]))", str(source), str(frozen / BRIDGE_SEAL)])
    source_command(source, ["-c", "from experiments.adaptive_credit_bridge_v1.provenance import verify_source; import sys; print(verify_source(sys.argv[1],sys.argv[2]))", str(source / BRIDGE_SEAL), str(source / V2_SEAL)])
    (destination / "raw").mkdir()
    copied = {}
    for label, path in (("formal002", args.run), ("audit002", args.audit), ("preserved-v2", args.preserved)):
        copied[label] = copy_tree(path, destination / "raw" / label)
    for label in ("credit-build-launch001", "credit-formal-launch002", "credit-audit-launch002"):
        copied[label] = copy_tree(args.original_cost_root / label, destination / "raw" / label)
    shutil.copy2(frozen / "GIT_OBJECT_PROOF.json", destination / "raw/ORIGINAL_GIT_OBJECT_PROOF.json")
    copied["signed-build"] = copy_tree(args.build, destination / "build/signed")
    owner_build = original_owner_build(args.v2_archive, destination / "build/owner", source)
    write(destination / "build/OWNER_BUILD_RECONSTRUCTION.json", owner_build)
    runtime = destination / "runtime"
    runtime.mkdir()
    inputs = load(args.run / "INPUTS.json")
    for kind in ("owner", "signed"):
        original = Path(inputs[kind + "_binary"])
        if sha(original) != inputs[kind + "_binary_sha256"]:
            raise ValueError("Original binary mismatch: " + kind)
        shutil.copy2(original, runtime / kind)
    shutil.copy2(Path(__file__), destination / "REPLAY.py")
    (destination / "README.md").write_text(
        "# Fresh signed-credit formal002 portable evidence\n\n"
        "This is a new 16-episode run with new local research signing keys after environment recovery. "
        "It is not restoration of the lost formal001 raw evidence and not an additional efficacy comparison.\n\n"
        "`raw/` preserves all original paths and bytes. `source/` contains 228 sealed inputs and the explicitly partial Git proof. "
        "`runtime/` contains exact Linux executables; the original owner and bridge build receipts retain their original paths.\n\n"
        "## Replay\n\n"
        "Use the exact Python executable identity and dependency versions in `source/experiments/adaptive_credit_bridge_v1/results/formal001/SOURCE_SEAL.json`. "
        "The requirements are NumPy 2.3.5, SciPy 1.17.0 and cryptography 50.0.2. Python, Git, the Rust toolchain and Python wheels are prerequisites, not bundled here.\n\n"
        "```sh\npython3 REPLAY.py replay --bundle . --destination /new/working-replay --receipt /new/replay-launch\n```\n\n"
        "Replay copies the raw run and changes only INPUTS executable paths, two research permit allowed_root values and terminal owner_request model/calibration paths. "
        "HOST_PATH_RELOCATION.json lists every edit. The unchanged frozen audit verifies all 16 episodes, independent signatures, stopping, resource accounting and idempotent native retries.\n\n"
        "## Offline native rebuild inputs\n\n"
        "`build/signed/` and `build/owner/` retain Cargo.toml, Cargo.lock, exact source composition and checked vendor packages. "
        "Use rustc/cargo 1.95.0 from the original receipts; the toolchain itself is not included. Build in a new copy so evidence remains unchanged.\n\n"
        "```sh\n# From a copy of build/signed:\ncargo build --offline --locked --release -j 1 -p hepta-research-signed-credit-bridge\n"
        "# From a copy of build/owner:\ncargo build --offline --locked --release -j 1 -p codex-hepta-neuron --example adaptive_neuron_host\n```\n\n"
        "Replay checks binary hashes; export does not claim it performed another rebuild. Original complete v2 archive remains separately preserved. "
        "The bundled synthetic keys are research fixture material and confer no production authority. "
        "Outer launch CPU includes all child stages; nested audit/build/RPC costs explain it and must not be added again. "
        "The small launcher's own interpreter startup is outside its recorded interval; child Python startup is inside.\n"
    )
    receipt = {"schema": "hepta.signed-credit.recovery-export.v1", "new_run": "formal002", "restores_formal001_raw": False,
               "source_commit": sealed["source_commit"], "source_seal_sha256": sha(source / BRIDGE_SEAL),
               "verified_source_inputs": len(sealed["inputs"]), "copied_original_groups": copied,
               "original_run_root": str(args.run.resolve()), "original_audit_root": str(args.audit.resolve()),
               "original_evidence_unchanged": True, "local_only": True,
               "owner_binary_sha256": sha(runtime / "owner"), "signed_binary_sha256": sha(runtime / "signed")}
    write(destination / "EXPORT.json", receipt)
    write(destination / "PAYLOAD_MANIFEST.json", {"schema": "hepta.portable-payload.v1", "files": inventory(destination)})
    return receipt


def verify_bundle(bundle):
    payload = load(bundle / "PAYLOAD_MANIFEST.json")["files"]
    actual = inventory(bundle)
    protected = {name: identity for name, identity in actual.items()
                 if name not in {"PAYLOAD_MANIFEST.json", "ARCHIVE_MANIFEST.json"} and not name.startswith("delivery/")}
    if protected != payload:
        raise ValueError("Portable payload manifest mismatch")
    if (bundle / "ARCHIVE_MANIFEST.json").exists():
        declared = load(bundle / "ARCHIVE_MANIFEST.json")["files"]
        if {k: v for k, v in actual.items() if k != "ARCHIVE_MANIFEST.json"} != declared:
            raise ValueError("Full archive manifest mismatch")


def replay(args):
    bundle, destination = args.bundle.resolve(), args.destination.resolve()
    verify_bundle(bundle)
    destination.mkdir(parents=True, exist_ok=False)
    original = bundle / "raw/formal002"
    before = inventory(original)
    working = destination / "working"
    copy_tree(original, working)
    mutations = []

    def relocate(relative, changes):
        path = working / relative
        value = load(path)
        prior = deepcopy(value)
        declared = []
        for keys, after in changes:
            parent = value
            for key in keys[:-1]:
                parent = parent[key]
            old = parent[keys[-1]]
            if not isinstance(old, str) or not Path(old).is_absolute():
                raise ValueError("Expected one original absolute host path")
            parent[keys[-1]] = str(after)
            declared.append({"json_path": keys, "before": old, "after": str(after)})
        original_sha256 = sha(path)
        path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        restored = deepcopy(value)
        for change in declared:
            parent = restored
            for key in change["json_path"][:-1]:
                parent = parent[key]
            parent[change["json_path"][-1]] = change["before"]
        if restored != prior:
            raise ValueError("Relocation modified more than declared host paths")
        mutations.append({"relative_path": relative, "original_sha256": original_sha256,
                          "relocated_sha256": sha(path), "changed_host_paths_only": declared})

    relocate("INPUTS.json", [([kind + "_binary"], bundle / "runtime" / kind) for kind in ("owner", "signed")])
    for kind in ("owner", "signed"):
        relocate(kind + "/RESEARCH_PERMIT.json", [(["allowed_root"], working / kind)])
    for path in sorted((working / "terminal").glob("*.json")):
        relocate(path.relative_to(working).as_posix(), [(["owner_request", key], working / filename)
                 for key, filename in (("model", "MODEL.json"), ("calibration", "CALIBRATION.json"))])
    if len(mutations) != 19:
        raise ValueError("Expected exactly INPUTS, two permits and 16 terminal documents")
    after = inventory(working)
    changed = {name for name in before if before[name] != after[name]}
    if set(before) != set(after) or changed != {row["relative_path"] for row in mutations}:
        raise ValueError("Undeclared changed file in replay copy")
    write(destination / "HOST_PATH_RELOCATION.json", {"schema": "hepta.host-path-relocation.v1",
          "declared_mutations": mutations, "unchanged_other_files": len(before) - len(changed),
          "original_root": str(original), "relocated_root": str(working), "original_manifest_sha256": inventory_digest(before)})
    source = bundle / "source"
    source_command(source, ["-m", "experiments.adaptive_credit_bridge_v1.audit", "--run", str(working),
                   "--destination", str(destination / "audit"), "--source-seal", str(source / V2_SEAL),
                   "--bridge-seal", str(source / BRIDGE_SEAL)])
    audit = load(destination / "audit/AUDIT.json")
    if not audit["passed"] or audit["episodes"] != 16 or audit["signed_facts"] != 48 or not audit["original_evidence_unchanged"]:
        raise ValueError("Relocated audit did not prove the full formal run")
    if inventory(original) != before or inventory(working) != after:
        raise ValueError("Audit changed evidence bytes")
    verify_bundle(bundle)
    receipt = {"passed": True, "episodes": 16, "signed_facts": 48, "independent_snn_prefixes": audit["independent_snn_prefixes"],
               "audit_sha256": sha(destination / "audit/AUDIT.json"), "original_evidence_unchanged": True,
               "all_changes_declared": True, "relocation_sha256": sha(destination / "HOST_PATH_RELOCATION.json")}
    write(destination / "REPLAY_VERIFICATION.json", receipt)
    return receipt


def package(args):
    bundle = args.bundle.resolve()
    verify_bundle(bundle)
    for label, source in (("portable-replay002", args.replay), ("export-launch002", args.export_receipt), ("replay-launch002", args.replay_receipt)):
        copy_tree(source, bundle / "delivery" / label)
    declared = inventory(bundle)
    write(bundle / "ARCHIVE_MANIFEST.json", {"schema": "hepta.full-local-archive.v1", "files": declared})
    expected = inventory(bundle)
    args.archive.parent.mkdir(parents=True, exist_ok=True)
    with args.archive.open("xb") as output:
        with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
            for name in expected:
                archive.add(bundle / name, arcname=bundle.name + "/" + name, recursive=False)
    seen = {}
    with tarfile.open(args.archive) as archive:
        for member in archive.getmembers():
            prefix = bundle.name + "/"
            if not member.isfile() or not member.name.startswith(prefix) or ".." in PurePosixPath(member.name).parts:
                raise ValueError("Unsafe delivered archive member")
            name = member.name.removeprefix(prefix)
            if name in seen:
                raise ValueError("Duplicate delivered archive member")
            data = archive.extractfile(member).read()
            seen[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if seen != expected or inventory(bundle) != expected:
        raise ValueError("Delivered archive does not match retained source files")
    receipt = {"passed": True, "archive_path": str(args.archive.resolve()), "archive_sha256": sha(args.archive),
               "archive_bytes": args.archive.stat().st_size, "verified_archive_members": len(seen),
               "uncompressed_bytes": sum(item["bytes"] for item in seen.values()),
               "manifest_sha256": sha(bundle / "ARCHIVE_MANIFEST.json"), "local_only": True,
               "new_run": "formal002", "original_raw_formal001_restored": False,
               "source_commit": load(bundle / "EXPORT.json")["source_commit"],
               "portable_replay_entrypoint": bundle.name + "/REPLAY.py"}
    write(args.archive.with_suffix(args.archive.suffix + ".json"), receipt)
    return receipt


def outer(args):
    started = time.perf_counter()
    own_before = resource.getrusage(resource.RUSAGE_SELF)
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.receipt.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", *sys.argv[1:]]
    write(args.receipt / "START.json", {"schema": "hepta.recovery.outer-launch.v1", "stage": args.mode,
          "command": command, "started_at_utc": datetime.now(timezone.utc).isoformat(),
          "scope": "Includes child interpreter startup, full stage and descendant processes; excludes this launcher's own interpreter startup. Nested receipts are explanatory and not additive."})
    with (args.receipt / "stdout.log").open("xb") as stdout, (args.receipt / "stderr.log").open("xb") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr)
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"stage": args.mode, "exit_code": result.returncode, "complete": result.returncode == 0,
               "wall_seconds": time.perf_counter() - started,
               "self_cpu_seconds": own.ru_utime + own.ru_stime - own_before.ru_utime - own_before.ru_stime,
               "child_cpu_seconds": children.ru_utime + children.ru_stime - children_before.ru_utime - children_before.ru_stime,
               "nested_costs_not_additive": True, "stdout_sha256": sha(args.receipt / "stdout.log"),
               "stderr_sha256": sha(args.receipt / "stderr.log")}
    write(args.receipt / ("COMPLETE.json" if result.returncode == 0 else "FAILED.json"), receipt)
    print(json.dumps(receipt, sort_keys=True))
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    modes = parser.add_subparsers(dest="mode", required=True)
    fields = {
        "export": ("source-root", "run", "audit", "build", "preserved", "v2-archive", "original-cost-root", "destination"),
        "replay": ("bundle", "destination"),
        "package": ("bundle", "replay", "export-receipt", "replay-receipt", "archive"),
    }
    for name, names in fields.items():
        sub = modes.add_parser(name)
        for field in (*names, "receipt"):
            sub.add_argument("--" + field, required=True, type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(globals()[args.mode](args), indent=2, sort_keys=True))
        return 0
    return outer(args)


if __name__ == "__main__":
    raise SystemExit(main())
