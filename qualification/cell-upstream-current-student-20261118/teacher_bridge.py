"""Dispatch frozen teacher outputs through the unchanged actual upstream sandbox."""
import argparse, hashlib, json, pathlib, resource, sys, time

ROOT = pathlib.Path("/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b")
CODE = ROOT / "execution-code"
assert hashlib.sha256((CODE / "native_sandbox.py").read_bytes()).hexdigest() == "49cced4d3eb61ee86b1f55a11ca097be7618a0fc9b59e515f1b1d7676bec671c"
sys.path.insert(0, str(CODE))
import native_sandbox as native

def main(stage):
    started, cpu = time.perf_counter(), time.process_time()
    payload_path = ROOT / ("teacher-" + stage + "-input.json")
    payload = json.loads(payload_path.read_bytes())
    assert payload["stage"] == stage
    assert payload["teacher_freeze_sha256"] == "c9e7b72fb1bd196b32bb7022d6743054e234e1b7de1f08233e93939e3ff33094"
    assert native.sha((ROOT / "prepared/TASKS.json").read_bytes()) == "b30229f6fe886a0d23151b3e761592e3e11eeb333bdaf7e79c606eb6f85a08de"
    tasks = native.read(ROOT / "prepared/TASKS.json")
    assert len(tasks) == len(payload["outputs"]) == 4
    destination = ROOT / ("teacher-verification-" + stage + "-1")
    destination.mkdir(exist_ok=False)
    native.write(destination / "INPUT_BINDING.json", {
        "source_commit": "dfc4e24ba68fa983f4dbdaca1de6c2d54a4df950",
        "teacher_freeze_published_commit": "9cfa4995c5d08aa0af00cdda6ef1fa67e49b6d1e",
        "native_verifier_sha256": native.sha((CODE / "native_sandbox.py").read_bytes()),
        "bridge_sha256": native.sha(pathlib.Path(__file__).read_bytes()),
        "input_payload_sha256": native.sha(payload_path.read_bytes()),
        "teacher_freeze_sha256": payload["teacher_freeze_sha256"],
        "stage": stage,
        "remote_originals": [{"path": x["path"], "sha256": x["sha256"]} for x in payload["outputs"]],
        "desktop_background": "Sibling may run two nice19 Rust workers after the student's completed GPU window; native verifier timings are this observed host window, no model-net attribution.",
        "new_model_calls": 0,
        "at_ns": time.time_ns(),
    })
    result = []
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    for index, (task, file) in enumerate(zip(tasks, payload["outputs"])):
        assert native.sha(file["text"].encode()) == file["sha256"]
        original = json.loads(file["text"])
        assert original["project_id"] == task["project_id"] and original["record_id"] == task["record_id"]
        assert original["freeze_sha256"] == payload["teacher_freeze_sha256"]
        native.write(destination / ("ORIGINAL_OUTPUT-" + str(index) + ".json"), file["text"].encode())
        receipt = native.verify(task["project_id"], original["answer"], destination / str(index))
        feedback = native.feedback(receipt)
        row = {"project_id":task["project_id"],"verification":receipt,"verification_digest":native.sha(native.canonical(receipt)),"feedback":feedback,"feedback_digest":native.sha(feedback.encode())}
        result.append(row)
        print(json.dumps({"project_id":task["project_id"],"stage":receipt["stage"],"success":receipt["success"],"reason":receipt.get("reason"),"native_child":receipt["actual_native_child"],"tests":receipt.get("tests"),"failures":receipt.get("failures")}),flush=True)
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    native.write(destination / (stage.upper() + "_VERIFICATIONS.json"), result)
    native.write(destination / "COMPLETE.json", {
        "stage":stage,"actual_verifier_calls":len(result),
        "actual_native_children":sum(row["verification"]["actual_native_child"] for row in result),
        "success":sum(row["verification"]["success"] for row in result),
        "wall_seconds":time.perf_counter()-started,
        "self_cpu_seconds":time.process_time()-cpu,
        "completed_children_cpu_seconds":child_after.ru_utime+child_after.ru_stime-child_before.ru_utime-child_before.ru_stime,
        "new_model_calls":0,"new_training_updates":0,"full_system_cost_known":False,
        "verification_bundle_sha256":native.sha((destination/(stage.upper()+"_VERIFICATIONS.json")).read_bytes()),
        "research_NoUpdate_retained":True,
    })

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("stage",choices=("first","second"));main(parser.parse_args().stage)
