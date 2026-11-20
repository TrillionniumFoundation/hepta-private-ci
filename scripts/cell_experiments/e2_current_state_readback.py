"""Read pinned A source snapshots; reconstruct existing corrections without execution."""

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import xml.etree.ElementTree as ET

SOURCE = "ef096991a2632d04758d5a577ea9fbdf54209d31"
BASE = Path("qualification/cell-upstream-raw-function-learning-20261119")
EVAL = "evaluation-20261120/"
MODES = ("document_evidence", "native_feedback")
PINNED = {
    "prepared/DATASET.json": "45fa351bb2232501d1760b34b2c11a8667cf149b31658294a8567fb3fea02f1c",
    "prepared/CPU_CONTROLS.json": "4d6d7d0fedb54ab58d85e7daf15f1e4a6dd53a9a073f3d1680b3df4e1c204e8c",
    EVAL
    + "READOUT.json": "efef59d8d016beb5b7be333136e8077fac2dad8fc59caaff9037a4dff20e321e",
    EVAL
    + "archives/ARCHIVES_A.json": "5414b1f21ccf17053e8eff56a3b14a0926d84523a6d36f98b973c802755594fe",
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def read_inputs(root):
    pinned = {}
    for name, expected in PINNED.items():
        raw = (root / BASE / name).read_bytes()
        require(sha(raw) == expected, "pinned input differs: " + name)
        pinned[name] = json.loads(raw)
    manifest = pinned[EVAL + "archives/ARCHIVES_A.json"]
    members, archives = {}, []
    for mode in MODES:
        name = "A-" + mode + ".tar.gz"
        entry = [e for e in manifest["archives"] if e["archive"].endswith("/" + name)]
        require(len(entry) == 1, "ambiguous archive identity")
        entry = entry[0]
        raw = (root / BASE / EVAL / "archives" / name).read_bytes()
        require(
            len(raw) == entry["bytes"] and sha(raw) == entry["sha256"],
            "archive bytes differ: " + name,
        )
        expected = {e["path"]: e for e in entry["files"]}
        require(len(expected) == len(entry["files"]), "duplicate indexed member")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            items = archive.getmembers()
            require(
                len(items) == len(expected) == len({m.name for m in items}),
                "archive member set differs",
            )
            for item in items:
                require(
                    item.isfile()
                    and not PurePosixPath(item.name).is_absolute()
                    and ".." not in PurePosixPath(item.name).parts,
                    "nonregular or unsafe member",
                )
                require(
                    item.name in expected and item.name not in members,
                    "unexpected or duplicate member",
                )
                data = archive.extractfile(item).read()
                spec = expected[item.name]
                require(
                    len(data) == spec["bytes"] and sha(data) == spec["sha256"],
                    "member bytes differ: " + item.name,
                )
                members[item.name] = data
        archives.append(
            {"name": name, "bytes": len(raw), "members": len(items), "sha256": sha(raw)}
        )
    require(len(members) == 578, "original A archive coverage differs")
    return pinned, members, archives


def span(text, node):
    lines = text.splitlines(keepends=True)
    first = (
        min([node.lineno, *[d.lineno for d in getattr(node, "decorator_list", [])]]) - 1
    )
    start, end = len("".join(lines[:first])), len("".join(lines[: node.end_lineno]))
    return start, end, text[start:end]


def constant_name(node):
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def reconstruct(snapshot, target, binding):
    answer = target["final_answer"]
    require(
        answer.startswith("```python\n") and answer.endswith("\n```"),
        "original target fence differs",
    )
    body = answer[len("```python\n") : -len("```")]
    old = snapshot.decode("utf-8")
    before, after = ast.parse(old), ast.parse(body)
    name = binding["function"]
    old_fn = [
        n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == name
    ]
    new_fn = [
        n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == name
    ]
    require(len(old_fn) == len(new_fn) == 1, "ambiguous target function")
    left, right, _ = span(old, old_fn[0])
    edits = [(left, right, span(body, new_fn[0])[2])]
    extra = binding["optional_constant"]
    if extra:
        new_constants = [n for n in after.body if constant_name(n) == extra]
        old_constants = [n for n in before.body if constant_name(n) == extra]
        require(
            len(new_constants) == 1 and len(old_constants) <= 1,
            "constant identity differs",
        )
        replacement = span(body, new_constants[0])[2]
        if old_constants:
            left, right, _ = span(old, old_constants[0])
        else:
            anchor = binding["constant_slot"]["anchor_old"]
            require(old.count(anchor) == 1, "ambiguous constant slot")
            left = right = old.index(anchor)
        edits.append((left, right, replacement))
    for left, right, replacement in sorted(edits, reverse=True):
        old = old[:left] + replacement + old[right:]
    result = sha(old.encode("utf-8"))
    require(
        result == target["reference_exact_after_sha256"],
        "reconstruction differs from existing verified AFTER",
    )
    return result


def readback(root):
    pinned, members, archives = read_inputs(root)
    dataset = pinned["prepared/DATASET.json"]
    references = {
        r["project_id"]: r for r in pinned["prepared/CPU_CONTROLS.json"]["references"]
    }
    budget = pinned[EVAL + "READOUT.json"]
    require(
        budget["new_generations"] == 56 and budget["new_training_updates"] == 0,
        "completed original evaluation budget differs",
    )
    require(
        budget["original_completed_training_updates_reused"]
        == dict.fromkeys(MODES, 32),
        "completed original training budget differs",
    )
    require(len(dataset) == len(references) == 4, "original A panel differs")
    require(
        all(row["observed_actor"] == "P" for row in dataset),
        "completed training observation actor differs",
    )

    def obj(path):
        return json.loads(members[path])

    rows, first_refusals, models = [], [], {}
    counts = dict(
        calls=0, native_children=0, admission_refusals=0, successful_executions=0
    )
    for mode in MODES:
        prefix = "evaluation-A/" + mode
        model = obj(prefix + "/MODEL_LOADED.json")
        models[mode] = {
            "model_digest": model["model_digest"],
            "record_sha256": sha(members[prefix + "/MODEL_LOADED.json"]),
        }
        for index, target in enumerate(dataset):
            reference = references[target["project_id"]]
            require(
                reference["success"]
                and sha(target["final_answer"].encode())
                == reference["conversion"]["raw_answer_sha256"]
                == target["reference_payload_sha256"],
                "existing A correction identity differs",
            )
            require(
                reference["admission"]["patched_source_sha256"]
                == target["reference_exact_after_sha256"],
                "existing verified AFTER identity differs",
            )
            for attempt in (0, 1):
                path = prefix + "/current/" + str(index) + "/" + str(attempt)
                task, request, output, feedback, verification = [
                    obj(path + "/" + f + ".json")
                    for f in (
                        "ORIGINAL_TASK",
                        "REQUEST",
                        "OUTPUT",
                        "FEEDBACK",
                        "VERIFICATION",
                    )
                ]
                require(
                    task["project_id"] == target["project_id"]
                    and request["record_id"] == task["record_id"],
                    "current-policy task differs",
                )
                require(
                    output["loaded_model_manifest_digest"] == model["model_digest"],
                    "current-policy actor differs",
                )
                require(
                    sha(output["answer"].encode()) == verification["raw_answer_sha256"],
                    "current-policy action differs",
                )
                require(
                    sha(canonical(verification)) == feedback["verification_digest"],
                    "current-policy feedback differs",
                )
                expected_messages = task["task"]["messages"]
                if attempt == 1:
                    previous = prefix + "/current/" + str(index) + "/0/"
                    expected_messages = expected_messages + [
                        {
                            "role": "assistant",
                            "content": obj(previous + "OUTPUT.json")["answer"],
                        },
                        {
                            "role": "tool",
                            "content": obj(previous + "FEEDBACK.json")["content"],
                        },
                    ]
                require(
                    request["task"]["messages"] == expected_messages,
                    "own-policy history differs",
                )
                counts["calls"] += 1
                counts["successful_executions"] += int(verification["success"])
                native_path = path + "/verify/original-verifier/native/"
                if not verification["actual_native_child"]:
                    counts["admission_refusals"] += 1
                    require(
                        not verification["success"]
                        and native_path + "PATCHED_SOURCE.py" not in members,
                        "refusal incorrectly has native execution",
                    )
                    if attempt == 0:
                        original = verification.get(
                            "original_verification", verification
                        )
                        first_refusals.append(
                            {
                                "record": path,
                                "project": task["project_id"],
                                "mode": mode,
                                "stage": verification["stage"],
                                "reason": original["reason"],
                                "request_sha256": sha(members[path + "/REQUEST.json"]),
                                "output_sha256": sha(members[path + "/OUTPUT.json"]),
                                "feedback_sha256": sha(
                                    members[path + "/FEEDBACK.json"]
                                ),
                                "verification_sha256": sha(
                                    members[path + "/VERIFICATION.json"]
                                ),
                                "native_source_snapshot_exists": False,
                            }
                        )
                    continue
                counts["native_children"] += 1
                native, case, attestation = [
                    obj(native_path + f)
                    for f in (
                        "RESULT.json",
                        "CASE.json",
                        "sandbox-output/SANDBOX_ATTESTATION.json",
                    )
                ]
                require(
                    native["success"] == verification["success"],
                    "native outcome differs",
                )
                snapshot = members[native_path + "PATCHED_SOURCE.py"]
                require(
                    sha(snapshot)
                    == native["patched_source_sha256"]
                    == case["source_sha256"]
                    == attestation["source_sha256"],
                    "actual source state differs",
                )
                require(
                    target["original_tests_sha256"]
                    == task["original_tests_sha256"]
                    == case["test_sha256"]
                    == attestation["test_sha256"]
                    == native["original_test_sha256"],
                    "original oracle differs",
                )
                require(
                    sha(members[native_path + "CASE.json"]) == native["case_sha256"]
                    and sha(members[native_path + "sandbox-output/junit.xml"])
                    == native["junit_sha256"],
                    "original case/JUnit bytes differ",
                )
                cases = [
                    c.attrib["name"]
                    for c in ET.fromstring(
                        members[native_path + "sandbox-output/junit.xml"]
                    ).iter("testcase")
                ]
                require(
                    cases == [c["name"] for c in native["cases"]]
                    and len(cases) == native["tests"]
                    and native["same_original_case_set"],
                    "original ordered cases differ",
                )
                if verification["success"]:
                    continue
                binding = obj(path + "/verify/BINDING.json")
                require(
                    binding["original_source_sha256"]
                    == target["original_source_sha256"]
                    == task["original_source_sha256"],
                    "original source binding differs",
                )
                rows.append(
                    {
                        "record": path,
                        "project": task["project_id"],
                        "mode": mode,
                        "attempt": attempt,
                        "request_sha256": sha(members[path + "/REQUEST.json"]),
                        "output_sha256": sha(members[path + "/OUTPUT.json"]),
                        "feedback_sha256": sha(members[path + "/FEEDBACK.json"]),
                        "verification_sha256": sha(
                            members[path + "/VERIFICATION.json"]
                        ),
                        "state_sha256": sha(snapshot),
                        "original_source_sha256": target["original_source_sha256"],
                        "case_descriptor_sha256": native["case_sha256"],
                        "ordered_case_names_sha256": sha(canonical(cases)),
                        "native_result_sha256": sha(
                            members[native_path + "RESULT.json"]
                        ),
                        "existing_target_sha256": target["reference_payload_sha256"],
                        "existing_verified_after_sha256": target[
                            "reference_exact_after_sha256"
                        ],
                        "reconstructed_after_sha256": reconstruct(
                            snapshot, target, binding
                        ),
                    }
                )
    require(
        counts
        == dict(
            calls=16, native_children=12, admission_refusals=4, successful_executions=4
        ),
        "original own-policy denominator differs",
    )
    first_native = [r["record"] for r in rows if r["attempt"] == 0]
    require(
        len(rows) == 8 and len(first_native) == 4 and len(first_refusals) == 2,
        "original failure coverage differs",
    )
    return {
        "schema": "hepta.A-current-policy-material-readback.v1",
        "source_commit": SOURCE,
        "input_sha256": PINNED,
        "archives": archives,
        "models": models,
        "original_budget_spent": {
            "evaluation_generations": 56,
            "training_updates_per_arm": dict.fromkeys(MODES, 32),
            "additional_budget_granted": False,
        },
        "completed_training_observation_actor": "P",
        "current_student_states_used_by_completed_training": False,
        "original_own_policy_counts": counts,
        "first_native_failure_records": first_native,
        "first_admission_refusals": first_refusals,
        "failed_native_state_reconstructions": rows,
        "distinct_failed_states": len({r["state_sha256"] for r in rows}),
        "structural_exact_AFTER_reconstructions": 8,
        "new_execution": dict(
            model_loads=0,
            forwards=0,
            generations=0,
            optimizer_updates=0,
            native_revalidations=0,
        ),
        "qualification": dict(
            training_admitted=False,
            correction_learning_gain=False,
            retention_established=False,
            independent_confirmation=False,
            native_adoption=False,
        ),
        "future_task_or_answer_files_read": False,
        "original_scores_and_NoUpdate_unchanged": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(readback(args.source_root)).decode())
