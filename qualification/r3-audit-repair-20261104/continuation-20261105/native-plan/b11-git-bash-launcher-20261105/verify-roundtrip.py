from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

import yaml


ROOT = Path(__file__).resolve().parent
rows = json.loads((ROOT / "source-map.json").read_text())
commands = []


def identity(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


with tempfile.TemporaryDirectory(prefix="b11-shell-roundtrip-") as temporary:
    work = Path(temporary)
    for row in rows:
        path = work / row["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(row["preimage_file"]).read_bytes())
    for argv in (["git", "init", "--quiet"], ["git", "apply", "--check", str(ROOT / "full.patch")],
                 ["git", "apply", str(ROOT / "full.patch")]):
        result = subprocess.run(argv, cwd=work, capture_output=True, check=False)
        commands.append({"argv": argv, "cwd": str(work), "exit": result.returncode,
                         "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
        assert result.returncode == 0
    for row in rows:
        assert identity((work / row["path"]).read_bytes()) == row["postimage"]
    for argv in (["git", "apply", "--reverse", "--check", str(ROOT / "full.patch")],
                 ["git", "apply", "--reverse", str(ROOT / "full.patch")]):
        result = subprocess.run(argv, cwd=work, capture_output=True, check=False)
        commands.append({"argv": argv, "cwd": str(work), "exit": result.returncode,
                         "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
        assert result.returncode == 0
    for row in rows:
        assert identity((work / row["path"]).read_bytes()) == row["preimage"]

workflow = ".github/workflows/hepta-windows-token-mechanism-probe.yml"
pre = yaml.load((ROOT / "source" / workflow).read_text(), Loader=yaml.BaseLoader)
post = yaml.load((ROOT / "candidate" / workflow).read_text(), Loader=yaml.BaseLoader)
pre_steps = pre["jobs"]["token-mechanism-observations"]["steps"]
post_steps = post["jobs"]["token-mechanism-observations"]["steps"]
changed = []
for index, (before, after) in enumerate(zip(pre_steps, post_steps)):
    if before != after:
        assert set(before) == set(after) and {key for key in before if before[key] != after[key]} == {"run"}
        assert before["name"] in {"Check the ACL identity counterfactual and restore its source",
                                  "Run the original setup helper target after exact restoration"}
        changed.append(before["name"])
        post_steps[index]["run"] = before["run"]
assert len(changed) == 2 and pre == post
(ROOT / "roundtrip-verification.json").write_text(json.dumps({
    "role": "CLOUD_ISOLATED_GIT_ROUNDTRIP_AND_YAML_STRUCTURE_ONLY", "commands": commands,
    "all_three_postimages_exact": True, "all_three_preimages_exact_after_reverse": True,
    "yaml_only_two_run_scalars_change": changed, "all_other_workflow_fields_equal": True,
    "executed_project_tests_or_windows_commands": False,
}, indent=2) + "\n")
print(json.dumps({"commands": len(commands), "all_exit_zero": True, "changed_workflow_runs": changed}))
