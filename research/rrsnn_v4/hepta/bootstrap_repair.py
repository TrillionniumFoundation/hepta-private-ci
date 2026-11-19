"""Crash/recovery proof with independently pinned, still-pending fixture intent.

The supervisor is the trusted lifecycle authority only for its own fresh test
processes. Its pins are not production owner signatures or permission receipts.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time

import native_components as native

ROOT = native.ROOT
PATCHED = ROOT / "patched_upstream/codex-rs"
BUILD = ROOT / "native_repair_build"
RESULTS = ROOT / "bootstrap_repair_results"


def durable_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Controller:
    """Retain current trusted frontier in this supervisor, outside worker stores."""
    def __init__(self, directory, intent_path):
        self.directory = directory
        self.intent_path = intent_path
        self.intent_pin = native.sha(intent_path)
        self.events = []
        self.record("pending_first_publication", "fresh owner launch retained by supervisor")

    def record(self, state, evidence):
        path = self.directory / f"lifecycle-{len(self.events):02}.json"
        value = {"state": state, "evidence": evidence, "intent_sha256": self.intent_pin,
                 "previous_record_sha256": self.events[-1]["sha256"] if self.events else None,
                 "monotonic_ns": time.monotonic_ns()}
        durable_json(path, value)
        self.events.append({"path": str(path), "sha256": native.sha(path), "state": state})

    def initial_command(self, binary, run_root, metadata, phase="none"):
        current = self.events[-1]
        if native.sha(current["path"]) != current["sha256"]:
            raise ValueError("ControllerLifecyclePinMismatch")
        if current["state"] != "pending_first_publication":
            raise ValueError("InitializationAlreadyPublished")
        return [str(binary), "recover-initial", str(run_root), str(metadata),
                str(self.intent_path), self.intent_pin, phase]


def source_manifest():
    native.upstream_identity()
    changed = []
    for crate in ["hepta-types", "hepta-infer-core", "hepta-neuron"]:
        for original in sorted((native.UPSTREAM / crate).rglob("*")):
            if original.is_file():
                relative = original.relative_to(native.UPSTREAM)
                copied = PATCHED / relative
                if native.sha(original) != native.sha(copied):
                    changed.append(str(relative))
    assert changed == ["hepta-neuron/src/runtime.rs"], changed
    original = native.UPSTREAM / changed[0]
    copied = PATCHED / changed[0]
    patch = "".join(difflib.unified_diff(original.read_text().splitlines(True),
                  copied.read_text().splitlines(True), fromfile="a/codex-rs/" + changed[0],
                  tofile="b/codex-rs/" + changed[0]))
    (ROOT / "bootstrap_recovery.patch").write_text(patch)
    report = {"base_commit": native.UPSTREAM_SHA, "path": "codex-rs/" + changed[0],
              "before_sha256": native.sha(original), "after_sha256": native.sha(copied),
              "changed_crate_files": changed, "added_method": "recover_bootstrap_anchored",
              "existing_formats_changed": False, "trusted_current_initialization_frontier_required": True,
              "derive_anchor_from_journal_forbidden": True, "old_intent_does_not_prove_freshness": True}
    native.write_json(ROOT / "bootstrap_recovery_source.json", report)
    return report


def build():
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / ".cargo").mkdir(exist_ok=True)
    (BUILD / ".cargo/config.toml").write_text(
        '[source.crates-io]\nreplace-with="vendored"\n[source.vendored]\ndirectory='
        + json.dumps(str(native.UPSTREAM / "vendor")) + '\n[net]\noffline=true\n')
    manifest = '[package]\nname="codex-rrsnn-bootstrap-repair"\nversion="0.1.0"\nedition="2024"\n[workspace]\n[dependencies]\nserde_json="=1.0.149"\n'
    for crate in ["hepta-types", "hepta-infer-core", "hepta-neuron"]:
        manifest += 'codex-' + crate + '={path=' + json.dumps(str(PATCHED / crate)) + '}\n'
    manifest += '[[bin]]\nname="rrsnn-native-bootstrap-repair"\npath=' + json.dumps(str(ROOT / "native_owner/src/repair.rs")) + '\n[profile.release]\ndebug=false\ncodegen-units=1\n'
    (BUILD / "Cargo.toml").write_text(manifest)
    binary = native.BUILD / "target/release/rrsnn-native-bootstrap-repair"
    (BUILD / "justfile").write_text(
        'fmt:\n    cargo fmt --manifest-path Cargo.toml\n\nbuild:\n    cargo build --release --locked --offline --manifest-path Cargo.toml\n\n'
        'test:\n    ' + json.dumps(sys.executable) + ' ' + json.dumps(str(Path(__file__).resolve()))
        + ' --test-only --binary ' + json.dumps(str(binary)) + '\n')
    env = dict(os.environ)
    env.update(PATH=str(native.RUST) + os.pathsep + env["PATH"], RUSTC=str(native.RUST / "rustc"),
               RUSTDOC=str(native.RUST / "rustdoc"), CARGO_HOME=str(native.BUILD / "cargo_home"),
               CARGO_TARGET_DIR=str(native.BUILD / "target"), CARGO_BUILD_JOBS="1")
    before = shutil.disk_usage(ROOT).free
    if before < 180_000_000:
        raise RuntimeError("Insufficient bounded build free space; no automatic cleanup")
    steps = []
    for command in [["cargo", "generate-lockfile", "--offline"], [str(native.JUST), "fmt"],
                    [str(native.JUST), "build"], [str(native.JUST), "test"]]:
        start = time.perf_counter()
        result = subprocess.run(command, cwd=BUILD, env=env, capture_output=True, text=True)
        steps.append({"command": command, "code": result.returncode, "seconds": time.perf_counter() - start,
                      "stdout": result.stdout, "stderr": result.stderr})
        native.write_json(RESULTS / "build.json", {"steps": steps, "disk_free_before": before,
            "disk_free_after": shutil.disk_usage(ROOT).free, "all_passed": all(x["code"] == 0 for x in steps)})
        print(json.dumps({"step": command, "code": result.returncode, "tail": (result.stdout + result.stderr)[-3000:]}), flush=True)
        if result.returncode:
            raise RuntimeError("repair build/validation failed")
    native.write_json(RESULTS / "build.json", {"steps": steps, "all_passed": True,
        "disk_free_before": before, "disk_free_after": shutil.disk_usage(ROOT).free,
        "source": source_manifest(), "binary_sha256": native.sha(binary),
        "lock_sha256": native.sha(BUILD / "Cargo.lock"), "production_qualified": False})
    return binary


def invoke(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)["result"]


def kill_at(command, phase, sequence):
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    ready, _, _ = select.select([process.stdout], [], [], 30)
    if not ready:
        process.kill()
        process.wait()
        raise RuntimeError("fault barrier not reached in time")
    line = process.stdout.readline()
    if not line:
        raise RuntimeError(process.stderr.read())
    barrier = json.loads(line)
    assert barrier == {"ready": phase, "sequence": sequence}, barrier
    process.kill()
    code = process.wait(timeout=10)
    assert code == -9, code
    return {"barrier": barrier, "actual_sigkill_returncode": code}


def stores_hash(root):
    return {path.name: native.sha(path) for path in root.iterdir() if path.is_file()}


def reject(command, root, category):
    before = stores_hash(root)
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2, (command, result.returncode, result.stdout, result.stderr)
    error = json.loads(result.stderr)["error"]
    assert category in error, (category, error)
    assert stores_hash(root) == before, (category, "rejection modified journal or witness")
    return {"expected": category, "actual": error, "stores_unchanged": True}


def validate(binary):
    directory = RESULTS / ("proof-" + str(time.time_ns()))
    directory.mkdir(parents=True)
    metadata = directory / "host.json"
    durable_json(metadata, native.environment())
    intent = invoke([str(binary), "intent", str(directory / "never-created-owner"), str(metadata)])
    assert not (directory / "never-created-owner").exists()
    intent_path = directory / "independent-intent.json"
    durable_json(intent_path, intent)
    pin = native.sha(intent_path)
    checkpoints = intent["expected_checkpoints"]
    recovered, negatives, controllers = [], [], []
    snapshots = {}

    def continuation(result, sequence):
        assert result["recovered_sequence"] == sequence
        assert result["recovered_digest"] == checkpoints[sequence - 1]
        assert result["next_checkpoint"] == checkpoints[sequence]
        assert result["model_calls_during_recovery"] == 0
        assert result["next_model_calls"] == 1
        assert not result["authority_granted"]

    for sequence in [1, 2]:
        for phase in ["before_witness", "after_witness"]:
            label = f"owner-{sequence}-{phase}"
            controller = Controller(directory / (label + "-controller"), intent_path)
            root = directory / label
            crash = kill_at([str(binary), "crash", str(root), str(metadata), phase, str(sequence), "clean"], phase, sequence)
            snapshot = directory / (label + "-snapshot")
            shutil.copytree(root, snapshot)
            snapshots[(sequence, phase)] = snapshot
            published = phase == "after_witness" or sequence > 1
            if published:
                controller.record("published", f"observed supervised {phase} marker at sequence {sequence}")
                try:
                    controller.initial_command(binary, root, metadata)
                    raise AssertionError("published generation reused initial intent")
                except ValueError as error:
                    assert str(error) == "InitializationAlreadyPublished"
                    negatives.append({"expected": str(error), "intent_still_present": intent_path.exists(), "native_recovery_not_invoked": True})
                command = [str(binary), "recover-anchored", str(root), str(metadata)]
            else:
                command = controller.initial_command(binary, root, metadata)
            result = invoke(command)
            continuation(result, sequence)
            controller.record("published", "validated recovered first frontier and exact continuation")
            recovered.append({"case": label, **crash, "result": result})
            controllers.append(controller.events)

    base = snapshots[(1, "before_witness")]
    def copy_case(name, source=base):
        target = directory / name
        shutil.copytree(source, target)
        return target
    def initial_command(root, path=intent_path, expected_pin=pin, phase="none"):
        return [str(binary), "recover-initial", str(root), str(metadata), str(path), expected_pin, phase]

    root = copy_case("missing-intent")
    negatives.append(reject(initial_command(root, directory / "missing.json"), root, "MissingInitializationIntent"))
    root = copy_case("wrong-pin")
    negatives.append(reject(initial_command(root, expected_pin="f" * 64), root, "InitializationIntentPinMismatch"))
    tampered = directory / "tampered-intent.json"
    tampered.write_text(intent_path.read_text().replace("expected_checkpoints", "untrusted_checkpoints"))
    root = copy_case("tampered-intent")
    negatives.append(reject(initial_command(root, tampered), root, "InitializationIntentPinMismatch"))
    wrong_context = json.loads(intent_path.read_text())
    wrong_context["context"]["generation"] = 2
    context_path = directory / "wrong-context.json"
    durable_json(context_path, wrong_context)
    root = copy_case("wrong-context")
    negatives.append(reject(initial_command(root, context_path, native.sha(context_path)), root, "InitializationIntentBindingMismatch"))
    wrong_anchor = json.loads(intent_path.read_text())
    wrong_anchor["expected_checkpoints"][0] = "1" * 64
    anchor_path = directory / "wrong-anchor.json"
    durable_json(anchor_path, wrong_anchor)
    root = copy_case("wrong-anchor-before-tail-repair")
    with (root / "journal-0.bin").open("ab") as stream:
        stream.write(b"partial-tail")
    negatives.append(reject(initial_command(root, anchor_path, native.sha(anchor_path)), root, "AnchorMismatch"))
    root = copy_case("existing-witness", snapshots[(1, "after_witness")])
    negatives.append(reject(initial_command(root), root, "BootstrapWitnessPresent"))
    root = copy_case("no-automatic-fallback")
    negatives.append(reject([str(binary), "recover-anchored", str(root), str(metadata)], root, "NoPublishedAnchorNoAutomaticFallback"))
    root = copy_case("later-history-missing-witness", snapshots[(2, "before_witness")])
    (root / "witness-0.bin").write_bytes((base / "witness-0.bin").read_bytes())
    negatives.append(reject(initial_command(root), root, "RecoveryWitnessMismatch"))
    forged = directory / "valid-forged-input-journal"
    forgery_crash = kill_at([str(binary), "crash", str(forged), str(metadata), "before_witness", "1", "drift"], "before_witness", 1)
    negatives.append({**reject(initial_command(forged), forged, "AnchorMismatch"),
                      "journal_created_by_real_native_commit_with_valid_checksums": True, **forgery_crash})

    for phase in ["before_witness", "after_witness"]:
        root = copy_case("repair-crash-" + phase)
        controller = Controller(directory / ("repair-controller-" + phase), intent_path)
        crash = kill_at(controller.initial_command(binary, root, metadata, phase), phase, 1)
        if phase == "after_witness":
            controller.record("published", "observed successful repair witness publication before SIGKILL")
            command = [str(binary), "recover-anchored", str(root), str(metadata)]
        else:
            command = controller.initial_command(binary, root, metadata)
        result = invoke(command)
        continuation(result, 1)
        recovered.append({"case": "repair-" + phase, **crash, "result": result})
        controller.record("published", "validated crash-resumed recovery and continuation")
        controllers.append(controller.events)

    controller = Controller(directory / "controller-tamper", intent_path)
    controller.record("published", "first witness publication already observed")
    rolled_back = copy_case("both-stores-rolled-back-to-first-unpublished")
    rollback_bytes = stores_hash(rolled_back)
    try:
        controller.initial_command(binary, rolled_back, metadata)
        raise AssertionError("old intent plus both rolled-back stores authorized recovery")
    except ValueError as error:
        assert str(error) == "InitializationAlreadyPublished"
        assert stores_hash(rolled_back) == rollback_bytes
        negatives.append({"expected": str(error), "native_recovery_not_invoked": True,
                          "both_stores_rolled_back": True, "old_matching_intent_still_available": True,
                          "rejected_by_independent_current_controller_frontier": True})
    current = Path(controller.events[-1]["path"])
    current.write_text(current.read_text().replace('"published"', '"pending_first_publication"'))
    try:
        controller.initial_command(binary, base, metadata)
        raise AssertionError("tampered published lifecycle accepted")
    except ValueError as error:
        assert str(error) == "ControllerLifecyclePinMismatch"
        negatives.append({"expected": str(error), "native_recovery_not_invoked": True})

    report = {"schema": "rrsnn.conditional-bootstrap-recovery-proof.v1", "all_passed": True,
              "positive_recoveries": recovered, "negative_checks": negatives,
              "independent_intent_sha256": pin, "intent_created_before_any_faulting_owner": True,
              "expected_anchor_derived_from_journal": False, "controller_histories": controllers,
              "binary_sha256": native.sha(binary), "source": source_manifest(),
              "source_failure_retained_at": str(native.RESULTS / "validation_latest.json"),
              "production_owner_intent": False, "production_qualified": False,
              "scope": "explicit first-publication repair conditioned on independently trusted current initialization frontier",
              "unresolved": ["real owner current lifecycle proof", "independent protected production intent", "dot identity", "actual production Cell workload", "trained RR profile and calibration", "independent future utility"],
              "not_proven": "checksum does not authenticate intent; old intent cannot detect rollback of both journal and witness"}
    native.write_json(directory / "proof.json", report)
    native.write_json(RESULTS / "proof_latest.json", report)
    print(json.dumps({"positive_recoveries": len(recovered), "negative_checks": len(negatives),
                      "all_passed": True, "production_qualified": False}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-only", action="store_true")
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    if 8 in os.sched_getaffinity(0):
        os.sched_setaffinity(0, {8})
    if args.test_only:
        validate(args.binary.resolve())
    else:
        build()
