"""Actual runtime cancellation from a committed pending-read boundary.

Forced actions are explicit engineering coverage, not learned-policy benefit.
Every case clones excluded engineering files and leaves original fixtures and
all scientific data untouched. The due packet is absent during cancellation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import time

from . import joint_task as task

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); source = args.qualification.resolve(); out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time(); child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    content = HERE.parent/"round9_20261031/native/fixtures/fullhx.json"
    qualifier = json.loads((source/"SUMMARY.json").read_bytes())
    assert sha(content) == qualifier["content_sha256"]
    calls, cases = [], []
    for family in ("renewal", "full_markov", "affine_markov", "gru"):
        for missing in (0, 1):
            original = source/f"engineering_prior0.375_missing{missing}"
            for action in (0, 4, 5):
                directory = out/f"{family}_missing{missing}_cancel{action}"; directory.mkdir()
                folder = directory/"world"; shutil.copytree(original, folder)
                public = json.loads((folder/"public.json").read_bytes()); snapshot = directory/"owner.json"
                policy = source/"models"/(family+".json")
                command = [str(args.binary.resolve()), "--public", str(folder/"public.json"),
                    "--policy", str(policy), "--content-model", str(content), "--controller", "fixed",
                    "--seed", "991181", "--snapshot", str(snapshot), "--mode", "qualification", "--steps", "1"]

                def run(extra):
                    result = subprocess.run(command+extra, cwd=REPO, capture_output=True, text=True, timeout=45)
                    row = dict(command=command+extra, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
                    (directory/f"invocation_{len(calls):03d}.json").write_text(json.dumps(row, sort_keys=True)+"\n")
                    calls.append(row)
                    if result.returncode:
                        raise AssertionError((family, missing, action, result.stderr[-2000:]))
                    return json.loads(result.stdout)

                prefix = run(["--forced-actions", "READ"])
                before = prefix["after"]["task"]
                assert before["pending"] == dict(source_tick=0, due_tick=2)
                assert not before["history"] and prefix["receipts"][0]["actual_content_calls"] == 0
                due = folder/public["packets"][1]
                if due.exists(): due.unlink()
                actual = run(["--ack", prefix["acknowledged_sha256"], "--forced-actions", task.ACTIONS[action]])
                expected = task.successor(public, before, action)
                assert actual["before"] == prefix["after"] and actual["external_ack_verified"]
                assert actual["after"]["task"] == expected
                receipt = actual["receipts"][0]
                assert receipt["due_source"] is None and receipt["completion"] is None and receipt["content"] is None
                assert receipt["actual_content_calls"] == 0 and not receipt["attempted_packet_paths"] and not receipt["opened_packet_paths"]
                assert receipt["duration"] == 0 and receipt["charges"] == 0
                assert expected["pending"] is None and expected["terminal"]
                assert actual["after"]["content"] == prefix["after"]["content"]
                assert actual["after"]["cell"] == prefix["after"]["cell"]
                assert sha(snapshot) == actual["acknowledged_sha256"]
                cases.append(dict(family=family, original_missing=bool(missing), action=task.ACTIONS[action],
                                  future_packet_absent=True, exact_task_match=True, no_read_effect=True,
                                  logical_time_and_fee_increment_zero=True, resume_ack_verified=True))
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = dict(schema="joint-native-pending-cancel-independent-audit-v1", passed=True,
                  cases=len(cases), subprocesses=len(calls), details=cases,
                  binary_sha256=sha(args.binary), content_sha256=sha(content),
                  qualification_sha256=sha(source/"SUMMARY.json"),
                  source_sha256={n:sha(HERE/n) for n in ("joint_native_cancel_audit.py", "joint_task.py", "joint_native_task.rs")},
                  wall_seconds=time.perf_counter()-wall, parent_cpu_seconds=time.process_time()-cpu,
                  child_cpu_seconds=child_after.ru_utime+child_after.ru_stime-child_before.ru_utime-child_before.ru_stime,
                  formal_worlds_generated=0,
                  scope="forced READ then forced STOP/SUBMIT on excluded cloned fixtures; no learned routing, mid-action crash or physical exactly-once claim")
    (out/"SUMMARY.json").write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    destination = HERE/"evidence/joint_native_cancel_independent_audit.json"
    destination.write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k != "details"}, sort_keys=True))


if __name__ == "__main__":
    main()
