#!/usr/bin/env python3
"""Pure offline review. Never imports or executes a native/admission driver."""
from pathlib import Path
import ast
import hashlib
import json

OUT = Path(__file__).resolve().parent
PATHS = {
    "v5": "/tmp/hepta-36fa-successor-maintenance-v5/driver-v5.py",
    "admission": "/tmp/hepta-36fa-cc57-admission-successor-v2/qualification-admission.cc57.HOLD.py",
    "native_wrapper": "/tmp/hepta-36fa-final-qualification-hold-v1/native-wrapper.HOLD.py",
    "runtime_result": "/tmp/hepta-36fa-checkpoint1867-recovery/runtime-v2-result.original.json",
    "runtime_environment": "/tmp/hepta-36fa-checkpoint1867-recovery/runtime-v2-environment.original.json",
    "runtime_inputs": "/tmp/hepta-36fa-native-runtime-v2-recovery-20261112/INPUT_IDENTITIES.json",
    "seed_inventory": "/tmp/hepta-36fa-a96-recovery/MATERIALIZED_86DD_INVENTORY.recovered.json",
    "cc57_inventory": "/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json",
    "qualification_input": "/tmp/hepta-36fa-cc57-qualification-root-inputs-v1/APPROVED_FINAL_QUALIFICATION_INPUT.json",
}
EXPECTED = {
    "v5": "6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735",
    "admission": "a8be08b6cb00536817e2d68c42fa4b90d1e9ff72",
    "runtime_result": "7832ed48200e8361ae4a7dd5ca8b7b5f7f289b09",
    "runtime_environment": "8b62ac16f554c1f34ee72974637752f5a3b58aec",
    "seed_inventory": "e7efbbc915cf80db9f873a2b5f9bf162daf4308c",
    "cc57_inventory": "7f94788b70546a8b8030dfd2b9182a7d9287c537",
}
SEED_REPO = "/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    raw = {name: Path(path).read_bytes() for name, path in PATHS.items()}
    pins = {name: {"path": PATHS[name], **identity(body)} for name, body in raw.items()}
    for name, expected in EXPECTED.items():
        assert pins[name]["git_blob"] == expected, (name, pins[name])
    v5 = raw["v5"].decode()
    admission = raw["admission"].decode()
    v5_ast = ast.parse(v5)
    source_pins = next(ast.literal_eval(node.value) for node in v5_ast.body
                       if isinstance(node, ast.Assign) and len(node.targets) == 1
                       and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id == "SOURCE_PINS")
    seed = json.loads(raw["seed_inventory"])
    current = json.loads(raw["cc57_inventory"])
    seed_files = {row["path"]: row for row in seed["files"]}
    current_files = {row["path"]: row for row in current["files"]}
    historical_inputs = json.loads(raw["runtime_inputs"])
    same_dependency_inputs = []
    for path, pin in historical_inputs.items():
        if not path.startswith(SEED_REPO + "/"):
            continue
        relative = path[len(SEED_REPO) + 1:]
        old, new = seed_files[relative], current_files[relative]
        assert old == new
        assert pin == {"bytes": new["bytes"], "sha256": new["sha256"], "git_blob": new["working_blob"]}
        same_dependency_inputs.append({"path": relative, **pin, "complete_inventory_row_equal": True})
    assert len(same_dependency_inputs) == 16
    for pin in source_pins:
        new = current_files[pin["path"]]
        assert pin["bytes"] == new["bytes"] and pin["sha256"] == new["sha256"]
        assert pin["git_blob"] == new["working_blob"]
        assert seed_files[pin["path"]] == new
    runtime = json.loads(raw["runtime_result"])
    environment = json.loads(raw["runtime_environment"])
    cfg = json.loads(raw["qualification_input"])
    assert runtime["source_repo"] == SEED_REPO
    assert runtime["source_commit"] == "86dd56a930277e0d1aef3e475e35c2b5d60b43b7"
    assert environment["inherited_source_environment"] == {"CODEX_REPO_ROOT": None, "PYTHONPATH": None}
    assert cfg["runtime_guard"]["inherited_source_environment"] == environment["inherited_source_environment"]
    assert cfg["runtime_guard"]["environment"] == environment["explicit_environment"]
    commands = runtime["commands"]
    assert len(commands) == 6
    assert all(row["original_command_terminal"] == "observed" and row["returncode"] == 0
               and row["timed_out"] is False and row["output_limit_exceeded"] is False for row in commands)
    material_rows = []
    for role, value in environment["tool_and_material_files"].items():
        assert not value["path"].startswith(SEED_REPO + "/")
        assert not value["resolved"].startswith(SEED_REPO + "/")
        material_rows.append({"role": role, "path": value["path"], "resolved": value["resolved"]})
    assert "and observed.get(\"source_repo\")==str(REPO)" in v5
    assert "check(str(m.REPO) == cfg['repo']" in admission
    assert "and final_format['source_repo'] == cfg['repo']" in admission
    assert "and aligned['source_repo'] == cfg['repo']" in admission
    assert "check(self.initial_git == after['git_state']" in admission
    assert 'CODEX_REPO_ROOT=str(repo),PYTHONPATH=str(repo/"scripts")' in raw["native_wrapper"].decode()
    report = {
        "schema": "hepta.isolated-source.v5-environment-independent-review.v1",
        "status": "STATIC_RELOCATION_SEAMS_IDENTIFIED_NO_NATIVE_EXECUTION",
        "inputs": pins,
        "scope": "Pinned V5 environment, a8be admission call sites, historical runtime proof, and source-dependency identity only. Not a new recovery/control implementation.",
        "source_dependency_identity": {
            "runtime_source_input_count": 16,
            "all_16_equal_to_seed_and_cc57_complete_inventory_rows": True,
            "runtime_source_inputs": same_dependency_inputs,
            "v5_source_entry_count": len(source_pins),
            "all_6_source_entries_equal_to_seed_and_cc57": True,
            "v5_source_entries": source_pins,
            "evidence_limit": "The two exact recovered inventories are immutable historical/canonical evidence. This comparison is not a fresh physical observation of any new source directory.",
        },
        "historical_environment": {
            "source_repo": SEED_REPO,
            "source_commit": runtime["source_commit"],
            "source_tree": runtime["source_tree"],
            "six_original_runtime_commands_observed_normal_zero": True,
            "inherited_source_environment": environment["inherited_source_environment"],
            "all_16_recorded_tool_material_path_pairs_external_to_historical_repo": True,
            "tool_material_paths": material_rows,
            "external_environment_is_reusable_only_after_current_file_and_resource_checks": True,
        },
        "concrete_relocation_seams": [
            {"function": "V5.validate_runtime_restoration", "current_predicate": "observed.source_repo == str(REPO)",
             "requirement": "Keep the exact historical 86dd source path as a separately pinned historical identity; a new current REPO must not rewrite or relax the original proof. Keep all SEED commit/tree/parents, six commands, three audits and exact result/environment/supervisor bytes unchanged."},
            {"function": "Admission.__init__", "current_predicate": "str(m.REPO) == cfg.repo",
             "requirement": "An explicitly reviewed current-repo binding is necessary. Merely changing cfg.repo fails; merely rebinding m.REPO makes the V5 historical predicate fail. Keep TARGET/DEPOT and runtime tool pins fixed."},
            {"function": "Admission.acquire_and_validate / historical format and alignment", "current_predicate": "final_format.source_repo == cfg.repo and aligned.source_repo == cfg.repo",
             "requirement": "Validate both originals against their actual historical source path, then require an actual create-only new-source materialization proof referencing the same exact cc57 tree/commit and complete inventory. Do not claim those old jobs ran in the new directory."},
            {"function": "Admission.acquire_and_validate / current Git state", "current_predicate": "self.initial_git == old aligned.after.git_state",
             "requirement": "A newly initialized repository has its own exact raw index/config/HEAD/refs baseline. Bind actual current Git bytes to its actual successful materialization result, and retain exact before/after equality during qualification. Keep detached HEAD, zero refs, complete tree/index/physical-source requirements; do not reuse old metadata or weaken equality."},
        ],
        "must_remain_current_checks": [
            "Complete current 15188-file physical inventory and cc57/B7 exact identity, including the seven archives missing from the old source.",
            "The same real coordination-lock policy and fresh current Git byte baseline; old missing-file/ref/index scene remains untouched.",
            "Actual current full bytes/path/resolved/mode of six tools, V8 pair and venv Python/Ruff, using the original exact five-field projection.",
            "External accessible current-user target/depot/venv/cache directories, target already present and live free space at least 34359738368 bytes.",
            "Original global same-UID active/unreadable Cargo/formatter rejection, with BUILD_PROCESS_PREFLIGHT recorded before rejection; no foreign-job exception.",
            "Exact inherited source environment (both null in the original observation), no unknown UV/RUFF names and no Git identity/object environment overrides.",
            "Original environment, all original gate/test argv, budgets, 8MiB stack/test deadline, executor, raw/postimage retention and failure/Unknown semantics.",
        ],
        "source_path_execution_behavior": "Before native execution, the original wrapper sets CODEX_REPO_ROOT=cfg.repo and PYTHONPATH=cfg.repo/scripts, then chdir(cfg.repo/codex-rs). Keep this current-source behavior; do not invent historical inherited non-null values.",
        "not_proved": [
            "No actual new source directory or native object-store availability observed.",
            "No new current tool, cache, target capacity, process, lock, file-mode or Git-state observation performed.",
            "No Cargo, H, original driver main, qualification gate, download, tool install or original-source/ref/index write performed.",
            "This does not identify who changed the old index/retired-artifacts ref or removed seven tracked archives, and does not reclassify old 1cd4.",
        ],
    }
    data=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
    with (OUT / "REVIEW.json").open("xb") as stream:
        stream.write(data)
    print(json.dumps({"review": str(OUT / "REVIEW.json"), **identity(data), "runtime_source_inputs_equal": 16,
                      "v5_source_entries_equal": 6, "native_execution": False},sort_keys=True))


if __name__ == "__main__":
    main()
