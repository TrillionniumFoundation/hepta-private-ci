"""Small artificial filesystem checks; never reads or moves formal outputs."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("preservation_helper", HERE / "preserve_cross_serialization_failure.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else helper.encoded(value))


def fixture(base):
    repo = base / "hepta"
    study = repo / helper.STUDY
    run = study / "results/formal_03"
    (run / "attempts").mkdir(parents=True)
    for name in ("preserve_cross_serialization_failure.py", "cross_serialization_adapter.py"):
        put(study / "publication" / name, (HERE / name).read_bytes())
    freeze = {}
    for index in range(36):
        path = f"experiments/artificial_source_{index:02d}.py"
        data = f"# TEST FIXTURE {index}\n".encode()
        put(repo / path, data)
        freeze[path] = hashlib.sha256(data).hexdigest()
    put(run / "SOURCE_FREEZE.json", {"files": freeze})
    put(run / "PROTOCOL.json", {"tasks": ["recall", "binding"], "seeds": list(range(15131, 15139))})
    for name in ("train_execution_cross.py", "online_confirm.py"):
        data = ("# TEST FIXTURE " + name + "\n").encode()
        put(study / name, data)
        directory = "train_execution_cross" if name.startswith("train") else "full_online_confirmation"
        put(run / directory / "source_snapshot" / name, data)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    online = {"source_snapshot": "source_snapshot/online_confirm.py", "source_sha256": digest(study / "online_confirm.py")}
    put(run / "full_online_confirmation/SELF_REGISTRATION.json", online)
    put(run / "train_execution_cross/SELF_REGISTRATION.json", {
        "source_snapshot": "source_snapshot/train_execution_cross.py",
        "source_sha256": digest(study / "train_execution_cross.py"),
        "parent_source_freeze_sha256": digest(run / "SOURCE_FREEZE.json"),
        "parent_protocol_sha256": digest(run / "PROTOCOL.json"),
        "parent_online_registration_sha256": digest(run / "full_online_confirmation/SELF_REGISTRATION.json"),
        "inherited_actual_executor_sha256": online["source_sha256"],
    })
    for task in ("recall", "binding"):
        for seed in range(15131, 15139):
            name = f"{task}_s{seed}_light"
            group = run / "train_execution_cross/groups" / name
            put(group / "ordinary_distribution_iid_LV.npz", b"TEST FIXTURE opaque bytes; not an array archive\n")
            put(group / "ordinary_distribution_iid_LV.json", b'{"incomplete":')
            receipt = run / "receipts/train_execution_cross" / name
            put(receipt.with_suffix(".json"), dict(name=name, task=task, seed=seed, train_mode="light", exit_code=1,
                cpu_user_seconds=1.0, cpu_system_seconds=.25, command=["TEST_FIXTURE_ONLY"]))
            put(receipt.with_suffix(".stdout.log"), b"")
            put(receipt.with_suffix(".stderr.log"), b"TypeError: Object of type float32 is not JSON serializable\n")
    put(run / "receipts/train_execution_cross/TOTAL.json", dict(stage="train_execution_cross", jobs=16, failed=16, process_cpu_seconds=20.0))
    put(run / "operational_addendum_guarded_01/FAILURE.json", {"fixture": True, "all_exit_zero": False})
    return repo, run


def run_checks():
    free_before = shutil.disk_usage(HERE).free
    checks = []
    temporary = None
    try:
        temporary = tempfile.mkdtemp(prefix="hcsn-cross-preserve-fixture-", dir="/tmp")
        repo, run = fixture(Path(temporary) / "normal")
        plan = helper.make_plan(run, repo)
        pin = hashlib.sha256(helper.encoded(plan)).hexdigest()
        checks.append(dict(name="exact_81_files_and_16_processes", passed=len(plan["files"]) == 81 and len(plan["process_attempts"]) == 16))
        try:
            helper.preserve(run, "0" * 64, repo)
        except ValueError:
            checks.append(dict(name="wrong_pin_refuses_before_move", passed=(run / "train_execution_cross/groups").is_dir() and not (run / "attempts" / helper.ATTEMPT).exists()))
        else:
            raise AssertionError("Wrong pin accepted")
        source = repo / plan["scientific_sources"][0]["path"]
        original = source.read_bytes()
        source.write_bytes(original + b"# changed\n")
        try:
            helper.preserve(run, pin, repo)
        except ValueError:
            checks.append(dict(name="changed_source_refuses_before_move", passed=(run / "train_execution_cross/groups").is_dir()))
        else:
            raise AssertionError("Changed scientific source accepted")
        source.write_bytes(original)
        outcome = helper.preserve(run, pin, repo)
        record = json.loads(Path(outcome["path"]).read_bytes())
        checks.append(dict(name="all_81_bytes_and_hashes_preserved", passed=all(
            len((run / row["archive_path"]).read_bytes()) == row["bytes"] and hashlib.sha256((run / row["archive_path"]).read_bytes()).hexdigest() == row["sha256"] for row in plan["files"])))
        checks.append(dict(name="only_two_closed_directories_moved", passed=not (run / "train_execution_cross/groups").exists() and not (run / "receipts/train_execution_cross").exists() and (run / "train_execution_cross/SELF_REGISTRATION.json").is_file()))
        checks.append(dict(name="complete_record_last_and_total_not_double_counted", passed=record["complete"] and not record["launcher_total"]["counted_separately"] and record["plan_sha256"] == pin))
        try:
            helper.preserve(run, pin, repo)
        except ValueError:
            checks.append(dict(name="repeat_refuses_existing_attempt", passed=True))
        else:
            raise AssertionError("Repeated preservation accepted")
        repo, run = fixture(Path(temporary) / "interrupted")
        plan = helper.make_plan(run, repo)
        pin = hashlib.sha256(helper.encoded(plan)).hexdigest()
        original_rename = os.rename
        calls = []
        def fail_second(source, target):
            calls.append(str(source))
            if len(calls) == 2:
                raise OSError("TEST FIXTURE second rename failure")
            return original_rename(source, target)
        try:
            with patch.object(helper.os, "rename", side_effect=fail_second):
                helper.preserve(run, pin, repo)
        except OSError:
            attempt = run / "attempts" / helper.ATTEMPT
            checks.append(dict(name="partial_move_retains_every_byte_and_failure_record", passed=(attempt / "groups").is_dir() and (run / "receipts/train_execution_cross").is_dir() and (attempt / "PRESERVATION_FAILURE.json").is_file() and not (attempt / "PRESERVATION.json").exists() and all(
                hashlib.sha256((run / (row["archive_path"] if row["original_path"].startswith("train_execution_cross/groups/") else row["original_path"])).read_bytes()).hexdigest() == row["sha256"] for row in plan["files"])))
        else:
            raise AssertionError("Injected failure not raised")
    except Exception as error:
        return dict(schema="hcsn.r15.cross-preservation.selfcheck.v1", label="TEST FIXTURE ONLY", passed=False,
            checks=checks, error=repr(error), errno=getattr(error, "errno", None), retained_fixture_root=temporary,
            visible_free_bytes_before=free_before, prestart_space_threshold_used=False, free_space_mocked=False,
            helper_sha256=hashlib.sha256((HERE / "preserve_cross_serialization_failure.py").read_bytes()).hexdigest(),
            selfcheck_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            formal_data_read=False, formal_directories_moved=False,
            note="Failed or partial artificial fixture is retained; this is not a passing check.")
    shutil.rmtree(temporary)
    return dict(schema="hcsn.r15.cross-preservation.selfcheck.v1", label="TEST FIXTURE ONLY", passed=all(x["passed"] for x in checks),
        checks=checks, helper_sha256=hashlib.sha256((HERE / "preserve_cross_serialization_failure.py").read_bytes()).hexdigest(),
        selfcheck_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), formal_data_read=False, formal_directories_moved=False,
        visible_free_bytes_before=free_before, prestart_space_threshold_used=False, free_space_mocked=False,
        successful_fixture_root=temporary, successful_fixture_cleaned=True,
        note="Only synthetic file bytes and registered-shape metadata; opaque fixture .npz names are not scientific arrays.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_checks()
    try:
        args.output.parent.mkdir(parents=True, exist_ok=False)
        helper.atomic_json(args.output, result)
    except OSError as error:
        print(json.dumps(dict(selfcheck_result=result, receipt_write_failed=repr(error), errno=getattr(error, "errno", None)), sort_keys=True), flush=True)
        raise
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
