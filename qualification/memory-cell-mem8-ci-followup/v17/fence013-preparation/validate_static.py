from pathlib import Path
import ast
import copy
import difflib
import hashlib
import json
import subprocess
import yaml

HERE = Path(__file__).resolve().parent
source = HERE / "source/.github/workflows/hepta-mem-fence013-qualification.yml"
original = (HERE / "reference/ORIGINAL_BLOB_WORKFLOW.yml").read_bytes()
candidate = source.read_bytes()
before = yaml.safe_load(original)
after = yaml.safe_load(candidate)
assert before[True] == {"workflow_call": None}
assert after[True] == {"push": {"branches": ["codex/mem8-fence013-qualification-20261111-ed353817"]}}
assert after["permissions"] == before["permissions"] == {"contents": "read"}
assert list(after["jobs"]) == ["check"]
old = before["jobs"]["check"]
new = after["jobs"]["check"]
for key in ["timeout-minutes", "name", "runs-on", "permissions"]:
    assert old[key] == new[key]
assert new["timeout-minutes"] == 30 and new["runs-on"] == "ubuntu-24.04"
original_ids = ["fence", "checkout", "range", "policy_tests", "policy_check", "clean"]
preserved = []
for step in new["steps"]:
    if step.get("id") not in original_ids:
        continue
    item = copy.deepcopy(step)
    if item["id"] != "range":
        del item["id"]
    if item.get("uses", "").startswith("openai/fence@"):
        assert item["uses"] == "openai/fence@c7675fea986c29f1d655753a7a61fd6b4141be8f"
        item["uses"] = "openai/fence@e6b39c80c51cb2b2a39448ddeff74b3b886c0a63"
    preserved.append(item)
assert preserved == old["steps"], "Original steps changed beyond Fence pin and observation IDs"
assert not any("continue-on-error" in step for step in new["steps"])
assert not any("secrets" in step for step in new["steps"])
assert "workflow_dispatch" not in after[True]
helper = (HERE / "capture.py").read_bytes()
ast.parse(helper)
preflight = new["steps"][0]["run"]
embedded = preflight.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0].encode() + b"\n"
assert embedded == helper
scripts = []
for index, step in enumerate(new["steps"]):
    if "run" not in step:
        continue
    # Expressions are string tokens before runner expansion; original ones were not rewritten.
    result = subprocess.run(["bash", "-n"], input=step["run"].encode(), capture_output=True)
    assert result.returncode == 0, (index, result.stderr.decode())
    scripts.append(index)
def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}
diff = "".join(difflib.unified_diff(original.decode().splitlines(True), candidate.decode().splitlines(True),
                                  fromfile="reference/blob-size-policy.yml", tofile="candidate/hepta-mem-fence013-qualification.yml")).encode()
(HERE / "ORIGINAL_JOB_TO_HARNESS.patch").write_bytes(diff)
report = {"schema": "mem-fence013-qualification-static-v1", "status": "STATIC_ONLY_UNADMITTED",
          "source_anchor": "c89540598693697577cda8cba31cb07f6ce65317",
          "source_tree": "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae", "single_source_path": source.relative_to(HERE / "source").as_posix(),
          "candidate": pin(candidate), "embedded_capture": pin(helper), "original_workflow": pin(original), "diff": pin(diff),
          "checks": {"yaml_parse": True, "embedded_python_ast": True, "bash_n_scripts": scripts,
                     "one_job": True, "branch_limited_push_only": True,
                     "all_six_original_step_objects_preserved_except_pin_and_observation_ids": True,
                     "original_job_timeout_platform_permissions": True,
                     "original_fence_inputs_exact_audit_only": True,
                     "original_range_tests_allowlist_threshold_clean_and_post_unmodified": True,
                     "no_continue_on_error_or_new_secrets": True},
          "not_executed": ["GitHub Actions", "Fence", "native tests", "models", "provider", "host commands"],
          "refs_changed": False, "execution_contract": "The new branch must be anchored at source and then CAS advanced to its one-path child. First create-at-child events with zero before are rejected.",
          "terminal_requirement": "Artifact is collected before action post hooks. Final acceptance requires original complete job metadata and full raw log with the unmodified Fence post result."}
(HERE / "STATIC_VALIDATION.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(report, sort_keys=True))
