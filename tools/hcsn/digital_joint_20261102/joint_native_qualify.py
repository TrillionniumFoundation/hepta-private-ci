"""Abrupt native/IO/publication crashes, real cold retries, and refusal checks.

Fixtures copy old validation worlds into an explicitly excluded engineering
namespace; they are not fresh scientific confirmation. Success/failure, delayed
pending actions and prepared receipt reuse are tested with actual processes.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from . import joint_native_owner as owner

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--train", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(); out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    invocations, cases, baseline_failures = [], [], []
    content = HERE.parent/"round9_20261031/native/fixtures/fullhx.json"
    policy = a.train/"fit_11/ordinary_bank.json"

    def invoke(command, expected=(0,)):
        result = subprocess.run(command, cwd=REPO, text=True, capture_output=True, timeout=90)
        row = dict(command=command, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        owner.save(out/f"invocation_{len(invocations):04d}.json", row); invocations.append(row)
        if result.returncode not in expected:
            raise AssertionError(f"unexpected process status {result.returncode}: {result.stderr[-2000:]}")
        return json.loads(result.stdout) if result.returncode == 0 else None

    def wrapper(root, config, op, request, ack=None, fault=None, expected=(0,), steps=1):
        command = [sys.executable, "-m", "tools.hcsn.digital_joint_20261102.joint_native_owner", op,
                   "--root", str(root), "--request-id", request, "--steps", str(steps)]
        for name, value in config.items():
            command += ["--"+name, str(value)]
        if ack is not None:
            command += ["--ack", ack]
        if fault is not None:
            command += ["--fault", fault]
        return invoke(command, expected)

    def prefix(root, config, delay):
        initialized = wrapper(root, config, "init", "genesis")
        if delay == 2:
            initialized = wrapper(root, config, "step", "start-read", initialized["ack"])
            assert initialized["result"]["after"]["task"]["pending"] is not None
        return initialized

    def child_count(root):
        return len(list(root.rglob("child_process.json")))

    def physical_calls(root):
        count = 0
        for path in root.rglob("child_process.json"):
            row = json.loads(path.read_bytes())
            if row["returncode"] == 0:
                result = json.loads(row["stdout"])
                count += sum(x["actual_content_calls"] for x in result["receipts"])
            elif (path.parent/"payload/owner.json.fault.json").exists():
                count += json.loads((path.parent/"payload/owner.json.fault.json").read_bytes())["model_executions"]
        return count

    fixtures = []
    for delay in (1, 2):
        candidates = sorted((a.train/"fit_11").glob("validation_*/public.json"))
        original = next(path for path in candidates if json.loads(path.read_bytes())["read_delay"][0] == delay
                        and (path.parent/json.loads(path.read_bytes())["packets"][0]).exists())
        for missing in (False, True):
            folder = out/f"engineering_delay{delay}_missing{int(missing)}"
            shutil.copytree(original.parent, folder)
            public = json.loads((folder/"public.json").read_bytes())
            if missing:
                (folder/public["packets"][0]).unlink()
            fixtures.append(dict(folder=folder, delay=delay, missing=missing, original=str(original), original_sha256=owner.digest(original)))
    for fi, fixture in enumerate(fixtures):
        config = dict(binary=a.binary.resolve(), public=fixture["folder"]/"public.json", policy=policy.resolve(),
                      content=content, controller="fixed", seed=978181)
        normal_root = out/f"normal_{fi}"
        initialized = prefix(normal_root, config, fixture["delay"])
        expected = wrapper(normal_root, config, "step", "due-action", initialized["ack"])
        assert expected["result"]["receipts"][0]["due_source"] == 0
        for fault in ("after_native_tick", "after_due_read", "after_child_commit", "after_io_receipt", "after_generation_move", "after_publish"):
            root = out/f"fault_{fi}_{fault}"; before = prefix(root, config, fixture["delay"])
            pointer_before = (root/"CURRENT.json").read_bytes()
            wrapper(root, config, "step", "due-action", before["ack"], fault, (1,) if fault.startswith("after_native") or fault in ("after_due_read", "after_child_commit") else (87,))
            if fault != "after_publish":
                assert (root/"CURRENT.json").read_bytes() == pointer_before
            calls_before = physical_calls(root); children_before = child_count(root)
            durable_before_retry = fault in ("after_io_receipt", "after_generation_move", "after_publish")
            unavailable = None
            if durable_before_retry and not fixture["missing"]:
                source = fixture["folder"]/json.loads(config["public"].read_bytes())["packets"][0]
                unavailable = source.with_suffix(".unavailable")
                source.rename(unavailable)
            recovered = wrapper(root, config, "step", "due-action", before["ack"])
            assert recovered["result"]["after"] == expected["result"]["after"]
            if durable_before_retry:
                assert child_count(root) == children_before and physical_calls(root) == calls_before
                assert recovered["duplicate"] if fault == "after_publish" else recovered["recovered_prepared"]
            pointer_after = (root/"CURRENT.json").read_bytes(); children_after = child_count(root)
            duplicate = wrapper(root, config, "step", "due-action", before["ack"])
            assert duplicate["duplicate"] and duplicate["ack"] == recovered["ack"]
            assert (root/"CURRENT.json").read_bytes() == pointer_after and child_count(root) == children_after
            if unavailable is not None:
                unavailable.rename(source)
            wrapper(root, config, "step", "other", None, expected=(1,))
            wrapper(root, config, "step", "other", "0"*64, expected=(1,))
            wrapper(root, config, "step", "due-action", before["ack"], expected=(1,), steps=2)
            wrapper(root, config, "step", "due-action", recovered["ack"], expected=(1,))
            assert (root/"CURRENT.json").read_bytes() == pointer_after
            calls = physical_calls(root)
            if not fixture["missing"] and fault in ("after_due_read", "after_child_commit"):
                assert calls == 2  # an explicitly observed repeat of the read-only effect
            cases.append(dict(fixture=fi, delay=fixture["delay"], missing=fixture["missing"], fault=fault,
                              physical_fullhx_executions=calls, prepared_reused=recovered["recovered_prepared"],
                              committed_reply_reused=recovered["duplicate"], child_attempts=child_count(root),
                              prepared_recovered_without_source=unavailable is not None,
                              task_state_and_fee_once=True, matches_no_fault_native_pair=True))
        # Real fault-instrumented raw owner: no transaction wrapper. The same
        # old ACK cannot recover after the native frontier/IO advanced.
        for fault in ("after_native_tick", "after_due_read", "after_child_commit"):
            raw = out/f"raw_{fi}_{fault}"; raw.mkdir(); snapshot=raw/"owner.json"
            command=[str(config["binary"]), "--public", str(config["public"]), "--policy", str(config["policy"]),
                     "--content-model", str(content), "--controller", "fixed", "--seed", str(config["seed"]),
                     "--mode", "qualification", "--snapshot", str(snapshot)]
            genesis = invoke(command+["--steps", "0"])
            if fixture["delay"] == 2:
                genesis = invoke(command+["--steps", "1", "--ack", genesis["acknowledged_sha256"]])
            crash_command=[sys.executable, "-c", "import os,subprocess,sys; os.environ['HEPTA_JOINT_CRASH_AT']=sys.argv[1]; sys.exit(subprocess.run(sys.argv[2:]).returncode)",fault,*command,"--steps","1","--ack",genesis["acknowledged_sha256"]]
            invoke(crash_command, (86,))
            invoke(command+["--steps","1","--ack",genesis["acknowledged_sha256"]],(2,))
            baseline_failures.append(dict(fixture=fi,fault=fault,unacknowledged_raw_recovery_rejected=True))
        print(json.dumps(dict(stage="joint_native_crashes",fixture=fi,cases=len(cases))),flush=True)
    # A durable receipt that is changed is rejected before retrying any effect.
    fixture=fixtures[0]; config.update(public=fixture["folder"]/"public.json")
    corrupt=out/"corrupt_prepared"; before=prefix(corrupt,config,fixture["delay"])
    wrapper(corrupt,config,"step","due-action",before["ack"],"after_io_receipt",(87,))
    prepared=next(corrupt.glob("staging-*/result.json")); prepared.write_bytes(prepared.read_bytes()+b" ")
    count=child_count(corrupt); pointer=(corrupt/"CURRENT.json").read_bytes()
    wrapper(corrupt,config,"step","due-action",before["ack"],expected=(1,))
    assert child_count(corrupt)==count and (corrupt/"CURRENT.json").read_bytes()==pointer
    summary=dict(schema="joint-native-unacknowledged-crash-qualification-v1",cases=cases,
                 baseline_raw_failures=baseline_failures,invocations=len(invocations),
                 success=True,prepared_receipt_tamper_refused=True,
                 sources={p.name:owner.digest(p) for p in (HERE/"joint_native_owner.py",HERE/"joint_native_qualify.py")},
                 binary_sha256=owner.digest(a.binary),content_sha256=owner.digest(content),policy_sha256=owner.digest(policy),
                 logical_once_scope="one published task successor and fee ledger per request id",
                 physical_effect_scope="read-only packet opens and FullHX may repeat before durable IO receipt; after receipt/commit retries reuse it",
                 durability_scope="process abrupt exit on one local filesystem with real file/directory fsync and atomic rename; not arbitrary remote side effects or hardware power-loss proof",
                 fixtures=[{**f,"folder":str(f["folder"])} for f in fixtures])
    owner.save(out/"SUMMARY.json",summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ("cases","fixtures","baseline_raw_failures")}),flush=True)


if __name__ == "__main__":
    main()
