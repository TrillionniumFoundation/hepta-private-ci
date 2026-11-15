"""Run the complete original and actual owner at the identical fixture pathname."""
import collections
import json
import os
from pathlib import Path
import subprocess

from patch_effects_oracle import observations as effects
from . import corpus, validation

require = effects.require
digest = effects.digest
save = effects.save


def observe(binary, side, case, request, directory, fixture, producer, env, contract):
    directory.mkdir()
    require(not fixture.exists() and not fixture.is_symlink(), "shared owned fixture path is occupied")
    effects.safe_fixture_root(fixture)
    stdout_path, stderr_path = directory / "stdout.bin", directory / "stderr.bin"
    process = {"valid": False, "argv": [str(binary), str(fixture)], "cwd": str(producer),
        "request_sha256": digest(request), "fixture_at_execution": str(fixture),
        "retained_fixture": str(directory / "fixture"), "timed_out": False}
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            try:
                result = subprocess.run(process["argv"], input=request, stdout=stdout,
                    stderr=stderr, cwd=producer, env=env, timeout=30)
                process.update(returncode=result.returncode,
                               signal=(-result.returncode if result.returncode < 0 else None))
            except subprocess.TimeoutExpired:
                process.update(returncode=None, signal=None, timed_out=True)
                raise
        raw, errors = stdout_path.read_bytes(), stderr_path.read_bytes()
        require(process["returncode"] == 0 and not errors, "actual application observer process failed")
        values = validation.parse(raw)
        validation.validate_fields(values, case, request, fixture)
        operations = effects.verify_events(values, case)
        writer_errors = validation.writer_events(values)
        native = validation.native_trace(values, case["entry"], side == "native", contract)
        actual = effects.actual_tree(fixture)
        emitted = [validation.unhex(values[f"after_{i}_hex"]).decode()
                   for i in range(validation.number(values["after_entries"]))]
        require(actual == emitted, "independent actual filesystem differs from the public observer")
        save(directory / "independent-after-tree.json", actual)
        common = validation.public_bytes(raw)
        (directory / "public.stdout").write_bytes(common)
        process.update(valid=True, status=values["status"], delta_exact=values["delta_exact"],
            delta_changes=validation.number(values["delta_changes"]),
            filesystem_events=validation.number(values["fs_events"]),
            filesystem_operations=dict(operations), writer_errors=writer_errors,
            actual_native_calls=validation.number(values["native_calls"]), native_actions=native["actions"],
            native_transitions=native["transitions"],
            independent_final_tree_verified=True, public_stdout_sha256=digest(common),
            final_tree_sha256=digest(json.dumps(actual, separators=(",", ":")).encode()))
        return process, common, values, actual
    except Exception as error:
        process["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        for label, path in (("stdout", stdout_path), ("stderr", stderr_path)):
            if path.exists():
                data = path.read_bytes()
                process[label + "_bytes"] = len(data)
                process[label + "_sha256"] = digest(data)
        # Keep every naturally produced file even on a failed invocation. This
        # is a rename inside this new gate's own directory, never a rollback.
        if fixture.exists() or fixture.is_symlink():
            fixture.rename(directory / "fixture")
        save(directory / "process.json", process)


def run(binaries, producer, env, output, contract):
    output.mkdir()
    cases = corpus.matrix()
    require(len(cases) == 1468 and len({corpus.wire(case) for case in cases}) == 1468,
            "the fixed application public corpus changed")
    for case in cases:
        decoded = corpus.decode(corpus.wire(case))
        require(all(decoded[key] == case[key] for key in decoded), "request does not round-trip")
    save(output / "cases.json", cases)
    fixture = output / "same-owned-fixture"
    baselines, action_counts, outcomes = {}, collections.Counter(), collections.Counter()
    transition_counts = collections.Counter()
    report = {"schema": "codex.hia.patch-application-public-observations.v1", "passed": False,
        "defined_pairs": len(cases), "compared_pairs": 0, "actual_processes": 0,
        "skipped": 0, "mismatches": 0, "actual_native_calls": 0,
        "cases": [], "relational_checks": collections.Counter(),
        "controlled_pending_or_cancellation_qualified": False,
        "comparison": "Exact complete public stdout after removing only the separately validated native-symbol trace; same fixture pathname, no path/error/content normalization.",
        "filesystem_scope": "Owned natural fixtures only. All ExecutorFileSystem callbacks forward real LOCAL_FS objects/results unchanged. No injected filesystem errors.",
        "context_scope": "None, real disabled typed context, and real restricted context without a configured sandbox runtime; no operating-system sandbox qualification.",
        "downcast_scope": "Returned error chains and writer precedence are public observations. Native CLASSIFY action ordering is separately checked from real transition frames; no direct probe into Rust downcast_ref is claimed."}
    try:
        for case in cases:
            directory = output / str(case["id"])
            directory.mkdir()
            request = corpus.wire(case)
            (directory / "request.bin").write_bytes(request)
            pair = {**case, "request_sha256": digest(request), "observations": {}, "matched": False}
            report["cases"].append(pair)
            common, values, trees = {}, {}, {}
            for side in ("original", "native"):
                result, common[side], values[side], trees[side] = observe(
                    binaries[side], side, case, request, directory / side, fixture,
                    producer, env, contract)
                pair["observations"][side] = result
                report["actual_processes"] += 1
                report["actual_native_calls"] += result["actual_native_calls"]
                action_counts.update(result["native_actions"])
                transition_counts.update(result["native_transitions"])
            pair["matched"] = common["original"] == common["native"]
            if not pair["matched"]:
                report["mismatches"] += 1
            require(pair["matched"], "complete public application mismatch: " + str(case))
            require(trees["original"] == trees["native"], "actual final fixture trees differ")
            original = values["original"]
            key = (case["case"], case["entry"], case["mode"], case["follow_symlinks"], case["context"])
            if case["writer_profile"] == "normal":
                baselines[key] = {"status": original["status"], "kind": original.get("kind"),
                    "delta": original["delta_debug_hex"], "tree": trees["original"]}
            else:
                base = baselines[key]
                require(original["delta_debug_hex"] == base["delta"] and
                        trees["original"] == base["tree"],
                        "writer behavior changed already-committed filesystem/delta effects")
                report["relational_checks"]["writer_preserves_committed_delta_and_tree"] += 1
                if base["status"] == "success" and original["status"] == "error":
                    require(not validation.unhex(original["stderr_hex"]),
                            "summary failure unexpectedly emitted an effects diagnostic")
                    report["relational_checks"]["summary_failure_keeps_committed_delta"] += 1
                if original["status"] == "error" and base["kind"] == "ParseError":
                    require(original["delta_changes"] == "0" and original["delta_exact"] == "true"
                            and original["fs_events"] == "0", "parse failure performed filesystem effects")
                    if original["kind"] == "IoError":
                        report["relational_checks"]["parse_diagnostic_error_overrides_parse_error"] += 1
                if base["status"] == "error" and base["kind"] != "ParseError":
                    if b"application writer sentinel" in validation.unhex(original["display_hex"]):
                        report["relational_checks"]["effects_diagnostic_error_overrides_effects_error"] += 1
            outcomes[(case["entry"], case["context"], original["status"], original.get("kind", "success"))] += 1
            report["compared_pairs"] += 1
            save(directory / "pair.json", pair)
        require(report["actual_processes"] == 2936 and report["compared_pairs"] == 1468,
                "not all fixed public pairs executed")
        require(set(action_counts) == set(range(1, 14)), "not all native semantic actions were observed")
        expected_transitions = {":".join(str(row[key]) for key in ("entry", "phase", "event"))
                                for row in contract["transitions"]}
        require(set(transition_counts) == expected_transitions and len(transition_counts) == 25,
                "the public corpus did not actually observe all 25 native transitions")
        for name in ("summary_failure_keeps_committed_delta", "parse_diagnostic_error_overrides_parse_error",
                     "effects_diagnostic_error_overrides_effects_error"):
            require(report["relational_checks"][name] > 0, "a required public error branch was not exercised")
        report.update(passed=True, native_action_counts=dict(action_counts),
            native_transition_counts=dict(transition_counts),
            outcomes=[{"entry": key[0], "context": key[1], "status": key[2], "kind": key[3], "count": count}
                      for key, count in sorted(outcomes.items())])
        return report
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        save(output / "report.json", report)
