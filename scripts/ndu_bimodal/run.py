"""Frozen-source auxiliary qualification; never promotes a production candidate."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import time
import traceback
import unittest

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "scripts/ndu_bimodal"
RUST_SOURCE = REPO / "codex-rs/hepta-infer-worker-host/src/bin/hepta-joint-propose.rs"
for directory in (REPO, REPO / "scripts"):
    sys.path.insert(0, str(directory))
TEST_MODULES = tuple(
    "ndu_bimodal.test_" + name
    for name in (
        "finite",
        "lifecycle",
        "learning",
        "native",
    )
)
ROLLBACK_TEST = (
    "ndu_bimodal.test_lifecycle.LifecycleTests."
    "test_checkpoint_cold_reload_and_real_cas_rollback"
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _inventory(root, paths):
    result = {}
    for path in sorted(set(paths)):
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Inventory refuses symlinked artifacts/sources")
        raw = path.read_bytes()
        result[path.relative_to(root).as_posix()] = {
            "sha256": _sha(raw),
            "bytes": len(raw),
        }
    return result


def _source_identity(expected):
    from ndu_bimodal.candidate import source_identity

    return source_identity(REPO, expected)


def _command(arguments, prefix, timeout=180):
    started = time.perf_counter()
    receipt = {
        "argv": [str(a) for a in arguments],
        "exit_code": None,
        "timeout_seconds": timeout,
        "status": "running",
    }
    try:
        with prefix.with_suffix(".stdout.log").open("wb") as stdout:
            with prefix.with_suffix(".stderr.log").open("wb") as stderr:
                process = subprocess.run(
                    receipt["argv"],
                    cwd=REPO,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout,
                    check=False,
                )
        receipt.update(
            exit_code=process.returncode,
            status="passed" if process.returncode == 0 else "failed",
        )
    except BaseException as error:
        receipt.update(
            status="timeout"
            if isinstance(error, subprocess.TimeoutExpired)
            else "execution_error",
            error_type=type(error).__name__,
            error=str(error),
        )
        raise
    finally:
        receipt["wall_seconds"] = time.perf_counter() - started
        _json(prefix.with_suffix(".command.json"), receipt)
    if process.returncode:
        raise RuntimeError("Command failed; see " + str(prefix))
    return receipt


def _test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _test_ids(test)
        else:
            yield test.id()


def _python_tests(output, modules=None):
    suite = unittest.TestSuite()
    counts = {}
    for name in TEST_MODULES if modules is None else modules:
        part = unittest.defaultTestLoader.loadTestsFromName(name)
        counts[name] = part.countTestCases()
        if not counts[name]:
            raise RuntimeError("Empty required test module: " + name)
        suite.addTests(part)
    identifiers = list(_test_ids(suite))
    if ROLLBACK_TEST not in identifiers:
        raise RuntimeError("Required public-API rollback protocol test is missing")
    with (output / "unittest.log").open("w") as stream:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    receipt = {
        "loaded_by_module": counts,
        "test_ids": identifiers,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "successful": result.wasSuccessful(),
    }
    _json(output / "unittest.json", receipt)
    if not result.wasSuccessful() or result.skipped:
        raise RuntimeError("Required tests failed or skipped; see unittest.log")
    return receipt


def _checkpoint_check(output, baseline, candidate, training):
    from ndu_bimodal.lifecycle import CheckpointStore
    from ndu_bimodal.native import load_generator

    (output / "baseline.weights").write_bytes(baseline)
    (output / "candidate.weights").write_bytes(candidate)
    _json(output / "content-training.json", training)
    root = output / "checkpoint-store"
    store = CheckpointStore(root)
    original = store.install({"weights.bin": baseline}, provenance="baseline")
    before = store.initialize(original)
    pending = store.install({"weights.bin": candidate}, provenance="fixture")
    store.stage(pending)
    decision = store.activate(
        {
            "kind": "fixture",
            "fixture": True,
            "synthetic": True,
            "candidate_sha256": pending,
            "evidence_sha256": _sha((output / "content-training.json").read_bytes()),
        },
        before["pointer_sha256"],
    )
    cold = CheckpointStore(root)
    restored = cold.load(cold.pointer()["active"])["weights.bin"]
    if (
        decision["decision"] != "no-update"
        or cold.pointer() != before
        or restored != baseline
    ):
        raise AssertionError("Fixture activation changed the baseline")
    if load_generator(restored).export_weights() != baseline:
        raise AssertionError("Cold generator bytes differ from the frozen baseline")
    return {
        "baseline_bundle_sha256": original,
        "candidate_bundle_sha256": pending,
        "candidate_decision": decision,
        "active_pointer_unchanged": True,
        "cold_baseline_bytes_identical": True,
        "cold_generator_load_passed": True,
        "production_candidate_rollback": "HOLD_NOT_ADMITTED",
        "rollback_protocol_test": ROLLBACK_TEST,
        "rollback_scope": "manufactured test evidence verifies mechanism only; no scientific admission or new admitted-version rollback",
    }


def _native_demo(
    output, binary, candidate, training, *, prompt="Describe the colour in the image."
):
    from ndu_bimodal.generator_training import colour_card
    from ndu_bimodal.lifecycle import CostLedger, Limits, Packet, PacketInbox
    from ndu_bimodal.native import NativeSession, encode_input

    root = output / "native-demo"
    root.mkdir()
    started, cpu = time.perf_counter(), time.process_time()
    before_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    ledger = CostLedger(Limits(32 * 1024 * 1024, 32, 90, 4, 1))
    session = None
    try:
        ledger.retain("generator-weight-packet", len(candidate))
        with ledger.operation("observation"):
            # Sources are created only after content training returns frozen bytes.
            _, initial = colour_card(9_100_001)
            public = encode_input(prompt, initial)
            ledger.retain("initial-input", len(initial) + len(prompt.encode()))
            ledger.retain(
                "public-tensor-payload",
                sum(t.numel() * t.element_size() for t in public.values()),
            )
            (root / "initial.ppm").write_bytes(initial)
            (root / "prompt.txt").write_text(prompt)
        session = NativeSession(
            candidate,
            binary,
            public,
            wall_seconds=90,
            call_seconds=3,
            reserve_seconds=4,
            max_calls=32,
            ledger=ledger,
        )
        ledger.retain("candidate-native-state", len(session.native_state))
        repair_text = session.repair("text")
        ledger.retain("candidate-native-state", len(session.native_state))
        with ledger.operation("coordination"):
            _, future = colour_card(9_100_002)
            if (
                _sha(initial) in training["training_sources"]
                or _sha(future) in training["training_sources"]
            ):
                raise AssertionError(
                    "Diagnostic source overlaps content-training sources"
                )
            now = time.time_ns()
            packet = Packet(
                "future-image",
                "image",
                now,
                now + 1_000_000_000,
                now + 15_000_000_000,
                _sha(future),
                len(future),
                sequence=1,
            )
        loader_calls = []

        def loader(packet_id, maximum):
            if packet_id != packet.packet_id or len(future) > maximum:
                raise ValueError("Loader contract mismatch")
            loader_calls.append(packet_id)
            return future

        inbox = PacketInbox([packet], loader, ledger)
        try:
            inbox.read(packet.packet_id)
        except RuntimeError as error:
            if str(error) != "future observation is unavailable":
                raise
        else:
            raise AssertionError(
                "Future observation was available before READ admission"
            )
        if loader_calls:
            raise AssertionError("Future loader ran before arrival")
        if not inbox.wait(packet.packet_id, max_sleep_s=1.1):
            raise AssertionError("Bounded WAIT did not reach the declared arrival")
        released = inbox.read(packet.packet_id)
        with ledger.operation("observation"):
            following = encode_input(prompt, released)
            (root / "read.ppm").write_bytes(released)
        replay = session.read(following)
        ledger.retain(
            "public-tensor-payload",
            sum(t.numel() * t.element_size() for t in following.values()),
        )
        ledger.retain("candidate-native-state", len(session.native_state))
        repair_image = session.repair("image")
        ledger.retain("candidate-native-state", len(session.native_state))
        delivered = session.finish(submit=True, output=root / "delivery")
        ledger.retain(
            "candidate-native-state", len(session.native_state) + len(session.prefix)
        )
        (root / "final-state.bin").write_bytes(session.native_state)
        (root / "final-prefix.bin").write_bytes(session.prefix)
        (root / "final-public.bin").write_bytes(session.public_bytes)
    except BaseException as error:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        _json(
            root / "failed-native-costs.json",
            {
                "status": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
                "ledger": ledger.summary(),
                "native_calls": session.calls if session else [],
                "session_construction_completed": session is not None,
                "whole_demo_parent_cpu_seconds": time.process_time() - cpu,
                "whole_demo_child_cpu_seconds": after.ru_utime
                + after.ru_stime
                - before_child.ru_utime
                - before_child.ru_stime,
                "provider_money": None,
                "energy_joules": None,
                "production_update": "no-update",
            },
        )
        raise
    after_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "scope": "procedural 16x16 colour-card diagnostic; not semantic efficacy",
        "generator_sha256": _sha(candidate),
        "training_identity": training["training_identity"],
        "postfreeze_source_seeds": [9_100_001, 9_100_002],
        "future_packet": packet.public(),
        "prearrival_read_rejected": True,
        "loader_calls": loader_calls,
        "repair_text": repair_text,
        "read_replay": replay,
        "repair_image": repair_image,
        "delivery": delivered,
        "ledger": ledger.summary(),
        "whole_demo_wall_seconds": time.perf_counter() - started,
        "whole_demo_parent_cpu_seconds": time.process_time() - cpu,
        "whole_demo_child_cpu_seconds": (
            after_child.ru_utime
            + after_child.ru_stime
            - before_child.ru_utime
            - before_child.ru_stime
        ),
        "provider_money": None,
        "energy_joules": None,
        "accounting": "whole-demo and ledger clocks overlap; do not sum. Child CPU is separate from parent CPU.",
        "residency_scope": "logical named payload bytes, not complete Python/Torch/native heap or RSS",
        "call_scope": "local loader/native requests; not provider invoice events",
        "production_update": "no-update",
    }
    _json(root / "report.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--rustc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execution-label", default="auxiliary-desktop")
    parser.add_argument("--epochs", type=int, default=240)
    parser.add_argument("--future-sources", type=int, default=48)
    args = parser.parse_args(argv)
    if not 1 <= len(args.execution_label.strip()) <= 128:
        parser.error(
            "--execution-label must describe the executor in 1..128 characters"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        parser.error("--source-commit must be a full lowercase Git commit")
    if not 1 <= args.epochs <= 2000 or not 2 <= args.future_sources <= 512:
        parser.error("epochs/future-sources exceed this bounded qualification profile")
    output = args.output.expanduser().resolve()
    if output == REPO or REPO in output.parents:
        parser.error("--output must be outside the checkout")
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "hepta.bimodal.qualification.v1",
        "execution_status": "running",
        "project_cloud_environment_verified": False,
        "execution_label": args.execution_label,
        "execution_scope": "auxiliary executor; no project-specific environment attestation",
        "scientific_acceptance": "HOLD_NO_GO",
        "production_update": "no-update",
        "runtime": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
        },
    }
    failed = False
    try:
        result["source_before"] = _source_identity(args.source_commit)
        version = subprocess.check_output(
            [args.rustc, "--version", "--verbose"], text=True, timeout=10
        )
        (output / "rustc-version.txt").write_text(version)
        if not re.match(r"rustc 1\.96\.\d+\b", version):
            raise RuntimeError(
                "Qualification requires the declared Rust 1.96 toolchain"
            )
        binary, tests_binary = (
            output / "hepta-joint-propose",
            output / "hepta-joint-propose-tests",
        )
        print("Compiling frozen native source and existing Rust tests", flush=True)
        result["rust_build"] = _command(
            [args.rustc, "--edition=2024", "-O", RUST_SOURCE, "-o", binary],
            output / "rust-build",
        )
        _command(
            [
                args.rustc,
                "--edition=2024",
                "-O",
                "--test",
                RUST_SOURCE,
                "-o",
                tests_binary,
            ],
            output / "rust-test-build",
        )
        _command([tests_binary], output / "rust-tests")
        rust_log = (output / "rust-tests.stdout.log").read_text()
        match = re.search(
            r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;", rust_log
        )
        if not match or int(match[1]) == 0 or int(match[2]) or int(match[3]):
            raise RuntimeError("Rust tests were empty, failed, or ignored")
        result["rust_test_count"] = int(match[1])
        os.environ["JOINT_V4_NATIVE_BINARY"] = str(binary)
        result["python_tests"] = _python_tests(output)
        from ndu_bimodal import evaluation, generator_training

        print("Running frozen finite-model study", flush=True)
        finite = evaluation.run_study(
            output / "finite-study",
            seeds=(11, 29, 47),
            epochs=args.epochs,
            future_sources=args.future_sources,
        )
        result["finite_study"] = {
            "decision": finite["decision"],
            "production_adoption": finite["production_adoption"],
            "report": "finite-study/report.json",
            "scope": finite["future_source_scope"],
        }
        if finite["decision"] != "no-update" or finite["production_adoption"]:
            raise AssertionError(
                "Finite evidence cannot authorize real-model promotion"
            )
        print(
            "Training numerical content model and checking retained baseline",
            flush=True,
        )
        baseline, candidate, training = generator_training.train(seed=41, steps=12)
        result["checkpoint"] = _checkpoint_check(output, baseline, candidate, training)
        _native_demo(output, binary, candidate, training)
        result["native_demo"] = {
            "report": "native-demo/report.json",
            "production_update": "no-update",
        }
        result["source_after"] = _source_identity(args.source_commit)
        if result["source_after"] != result["source_before"]:
            raise RuntimeError("Source identity changed during qualification")
        result["execution_status"] = "passed_auxiliary_checks"
    except BaseException as error:
        failed = True
        result["execution_status"] = "failed"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        (output / "failure.log").write_text(traceback.format_exc())
    try:
        result["artifact_sha256_inventory"] = _inventory(
            output,
            [
                p
                for p in output.rglob("*")
                if p.is_file() and p != output / "qualification.json"
            ],
        )
    except BaseException as error:
        failed = True
        result["execution_status"] = "failed"
        result["artifact_inventory_error"] = str(error)
        with (output / "failure.log").open("a") as stream:
            stream.write(traceback.format_exc())
    result["artifact_inventory_excludes"] = ["qualification.json"]
    _json(output / "qualification.json", result)
    print(str(output / "qualification.json"), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
