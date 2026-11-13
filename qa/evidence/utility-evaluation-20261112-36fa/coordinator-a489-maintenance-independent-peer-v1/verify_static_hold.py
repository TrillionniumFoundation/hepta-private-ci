#!/usr/bin/env python3
"""Pure fixed-input review: AST, bytes and JSON only. Never imports or executes reviewed controls."""
import ast
import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUTHOR = Path("/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1")
MATERIALIZATION = Path("/tmp/hepta-36fa-coordinator-a489-materializer-independent-peer-v1/inputs/packet.original")
NEW_REPO = "/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1"
NEW_CONTROL = "/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1"
NEW_RUN = "/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/run"
NEW_HEAD = "d25675445c39f76db69a7bd8e71a1a72e1cd5b9f"
NEW_TREE = "a489b394666b8141840275128a780605b024cde0"

def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def freeze(name, raw):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, ("immutable output differs", str(path))
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return {"path": str(path), **identity(raw)}

def load_bytes(path, blob, byte_count=None, digest=None):
    raw = path.read_bytes()
    pin = identity(raw)
    assert pin["git_blob"] == blob, (str(path), pin)
    assert byte_count is None or pin["bytes"] == byte_count
    assert digest is None or pin["sha256"] == digest
    return raw

def nodes(source):
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    selected = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert n.name not in selected
            start = min([n.lineno] + [x.lineno for x in getattr(n, "decorator_list", [])])
            selected[n.name] = (n, "".join(lines[start-1:n.end_lineno]).encode())
    return tree, selected

def consts(tree):
    result = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            try:
                result[n.targets[0].id] = ast.literal_eval(n.value)
            except (ValueError, TypeError):
                pass
    return result

def changes(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), ("unexpected config keys", path, set(a) ^ set(b))
        result = []
        for k in a:
            result.extend(changes(a[k], b[k], path + "/" + k))
        return result
    if a == b:
        return []
    return [{"path": path, "before": a, "after": b}]

old_raw = load_bytes(HERE/"inputs/DRIVER_3A0F6.original.py",
                     "3a0f6dec8127aa9587129d6e0f24bad55837ca13", 68496,
                     "d47231764a8d85cf60bba499411a08b316798ac6835ae8e7eae95967a79d5259")
new_raw = load_bytes(AUTHOR/"driver-maintenance.HOLD.py",
                     "59461030d4160f7ad6a978df5a7b6aaeb33fb2a6", 68520,
                     "2e8501f584a6905a07124f04bb623c2674c1ec77299b89fbc76ef06610c589ed")
cfg_old_raw = load_bytes(HERE/"inputs/CONFIG_D27DD8.original.json",
                        "d27dd8ee763c75eb5a0f195bb034fc9ca32b727e", 13768,
                        "ccf92346644f428bc66e634c8e4aebe871ed6dcaac354538c1e35862ea83aacf")
cfg_raw = load_bytes(AUTHOR/"WAITING_CONFIG.json",
                    "e9308cb6cc5e7fd949236ded84f593ec81143795", 10895,
                    "a67115ebbd521c5637212f22308808fac33e9efa48f60b6981a5a804dc202994")
mat_raw = load_bytes(MATERIALIZATION, "b05c78c478bbd55219fea7869b1c7871617509c7", 14404)
old, new = old_raw.decode(), new_raw.decode()
old_tree, old_defs = nodes(old)
new_tree, new_defs = nodes(new)
old_constants, new_constants = consts(old_tree), consts(new_tree)
old_cfg, cfg, mat = json.loads(cfg_old_raw), json.loads(cfg_raw), json.loads(mat_raw)

replacements = [
    ('REPO=pathlib.Path("/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1")',
     'REPO=pathlib.Path("' + NEW_REPO + '")'),
    ('EVIDENCE=pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-maintenance-v1")',
     'EVIDENCE=pathlib.Path("' + NEW_CONTROL + '")'),
    ('HEAD="0c59aaca0b4932507f068c723f73da2f96729b3d"', 'HEAD="' + NEW_HEAD + '"'),
    ('TREE="4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09"', 'TREE="' + NEW_TREE + '"'),
    ('NATIVE_INVENTORY={"bytes":3541985,"git_blob":"68342846200b9ba15f0483d89e28bfcf4c499a44","sha256":"686c516814839ce12a3de6a8907a8efd5f27d4d39d9d4b14e380137698faa1f4"}',
     'NATIVE_INVENTORY={"bytes":3543409,"git_blob":"7647480c5ed06525e1661ac451d0ac0ff2b23ea7","sha256":"69cab8dc5e68f6c9ebd8e8bd98ee54565fbbf112f1a1c61113c3413b77e3173b"}'),
    ('SUCCESSOR_INVENTORY={"bytes":5629701,"filesystem_entries":15237,"git_blob":"a596ae68859e3263a9ee58e2b5d7334ac9314c34","sha256":"affce692432a4fa61521561e6717a84984f679f3535190b6b88c92cb0f725f44","tracked_entries":15237}',
     'SUCCESSOR_INVENTORY={"bytes":5631947,"filesystem_entries":15243,"git_blob":"f1e2d72f99093581403a2dcc91b55da22a33f905","sha256":"0463522b45970d8ae9dbf5f4560e1b15e61768ec7c9ec164848019009c4643f0","tracked_entries":15243}'),
    ('LEAVES=15237', 'LEAVES=15243'),
    ('observed.get("new_objects_fully_verified")==16652',
     'observed.get("new_objects_fully_verified")==16661'),
]
forward = old
for before, after in replacements:
    assert forward.count(before) == 1 and new.count(after) == 1, before
    forward = forward.replace(before, after)
assert forward.encode() == new_raw
inverse = new
for before, after in reversed(replacements):
    assert inverse.count(after) == 1
    inverse = inverse.replace(after, before)
assert inverse.encode() == old_raw
assert ast.dump(ast.parse(inverse), include_attributes=False) == ast.dump(old_tree, include_attributes=False)
assert old_defs.keys() == new_defs.keys() and len(old_defs) == 51
definition_rows = []
for name, (old_node, old_body) in old_defs.items():
    new_node, new_body = new_defs[name]
    definition_rows.append({
        "name": name, "type": type(old_node).__name__,
        "before": identity(old_body), "after": identity(new_body),
        "byte_equal": old_body == new_body,
        "ast_equal": ast.dump(old_node, include_attributes=False) == ast.dump(new_node, include_attributes=False),
    })
changed_defs = [x["name"] for x in definition_rows if not x["byte_equal"]]
assert changed_defs == ["validate_materialization"]
old_body = old_defs["validate_materialization"][1]
new_body = new_defs["validate_materialization"][1]
assert new_body.replace(b'==16661', b'==16652') == old_body

expected_cfg = copy.deepcopy(old_cfg)
expected_cfg.update({
    "status": "HOLD_ACTUAL_MATERIALIZATION_AND_ROOT_EXACT_REVIEW_REQUIRED",
    "root_execution_approved": False,
    "driver_sha256": identity(new_raw)["sha256"],
    "driver_git_blob": identity(new_raw)["git_blob"],
    "source_repo": NEW_REPO, "source_commit": NEW_HEAD, "source_tree": NEW_TREE,
    "source_inventory": new_constants["SUCCESSOR_INVENTORY"],
    "formal_approved_config_created": False,
})
expected_cfg["materialization"] = {
    "job_id": None, "result_path": NEW_RUN + "/RESULT.json", "result": None,
    "supervisor_path": NEW_CONTROL + "/MATERIALIZATION_SUPERVISOR.original.json",
    "supervisor": None, "git_state": None, "index": None, "git_metadata": None,
    "git_metadata_gzip": None,
    "records": {name: None for name in ("command_records", "mutation_records", "input_records", "artifact_records")},
}
expected_cfg["coordination_lock"]["stat"] = None
expected_cfg["archive_restoration"]["supervisor_path"] = NEW_CONTROL + "/V8_RESTORATION_SUPERVISOR.original.json"
expected_cfg["waiting_for_actual_records"] = (
    "HOLD. The d256 materialization original job must reach normal terminal and provide complete RESULT, "
    "four original records, raw index/Git metadata, coordination and all three final audits. "
    "Exact staging and maintenance require separate Root approval. No source qualification is inherited."
)
expected_cfg["source_inventory_observation"] = (
    "Expected source inventory and native projection only at this preparation snapshot; no actual d256 success is claimed. "
    "Future configuration must bind the original materialization complete actual pins, and maintenance must reread "
    "all current bytes and actual Git-file stat before any fix/fmt."
)
assert expected_cfg == cfg, "config changes exceed explicit identity/proof-clearing/HOLD whitelist"
cfg_changes = changes(old_cfg, cfg)
assert mat["current"]["commit"] == NEW_HEAD and mat["current"]["tree"] == NEW_TREE
assert mat["destination_repo"] == NEW_REPO and mat["current"]["parents"] == cfg["parents"]
assert mat["current"]["native_inventory"] == new_constants["NATIVE_INVENTORY"]
assert mat["current"]["inventory"] == {k: cfg["source_inventory"][k] for k in ("bytes", "git_blob", "sha256")}
assert mat["current"]["leaves"] == new_constants["LEAVES"] == cfg["source_inventory"]["filesystem_entries"] == cfg["source_inventory"]["tracked_entries"]
assert mat["object_scope"]["union_objects"] == 16661 and mat["object_scope"]["reused_donor_objects"] == 16449
assert mat["format_base"]["commit"] == new_constants["C0F"] and mat["format_base"]["tree"] == new_constants["C0F_TREE"]
assert mat["donor"]["commit"] == new_constants["DONOR_HEAD"] and mat["donor"]["tree"] == new_constants["DONOR_TREE"]

budgets = {"FIX_SECONDS": 7200, "FMT_SECONDS": 900, "PREFLIGHT_SECONDS": 600,
           "RECORD_SECONDS": 300, "MAXIMUM_LOG_BYTES": 64 * 1024 * 1024}
for key, value in budgets.items():
    if key == "MAXIMUM_LOG_BYTES":
        # Read this literal multiplication without executing any reviewed module.
        assignment = next(n for n in new_tree.body if isinstance(n, ast.Assign) and
                          isinstance(n.targets[0], ast.Name) and n.targets[0].id == key)
        assert ast.dump(assignment.value, include_attributes=False) == ast.dump(ast.parse("64*1024*1024", mode="eval").body, include_attributes=False)
    else:
        assert old_constants[key] == new_constants[key] == value
fix = ["just", "fix", "-p", "codex-hepta-intelligence-eval", "-p",
       "codex-hepta-agentd", "-p", "codex-hepta-learning-ledger"]
fmt = ["just", "fmt", "--base", "c0f78493f815780f68b9bf5e390a21314d79311f"]
assert old_constants["FIX"] == new_constants["FIX"] == cfg["fix_argv"] == old_cfg["fix_argv"] == fix
assert cfg["fmt_argv"] == old_cfg["fmt_argv"] == fmt
for key, value in {"fix_seconds":7200, "fmt_seconds":900, "preflight_seconds":600,
                   "record_seconds":300, "outer_timeout_seconds":9300,
                   "minimum_target_free_bytes":34359738368,
                   "create_target_if_absent":False, "test_commands_authorized":False,
                   "remote_ref_updates_authorized":False}.items():
    assert old_cfg[key] == cfg[key] == value
for key in ("environment", "inherited_source_environment", "tool_files", "v8_files",
            "formatter_tool_files", "runtime_restoration", "historical_known_runtime_blockers",
            "tool_identity_projection", "parents"):
    assert old_cfg[key] == cfg[key], key
archive = copy.deepcopy(cfg["archive_restoration"])
archive["supervisor_path"] = old_cfg["archive_restoration"]["supervisor_path"]
assert archive == old_cfg["archive_restoration"]
assert cfg["coordination_lock"]["path"] == old_cfg["coordination_lock"]["path"]
assert cfg["coordination_lock"]["mode"] == old_cfg["coordination_lock"]["mode"] == "LOCK_EX"

main_node, main_raw = new_defs["main"]
stage_calls = [n for n in ast.walk(main_node) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name) and n.func.id == "stage"]
assert [ast.unparse(n) for n in stage_calls] == [
    "stage('fix', FIX, FIX_SECONDS)", "stage('fmt', FMT, FMT_SECONDS)"]
assert b"flock" not in new_raw and b"fcntl" not in new_raw
assert old_defs["main"][1] == main_raw
assert cfg["root_execution_approved"] is False
assert cfg["formal_approved_config_created"] is False
assert cfg["status"] != "ROOT_APPROVED_TO_EXECUTE"
pending = ["/materialization/" + k for k, v in cfg["materialization"].items() if v is None]
pending += ["/materialization/records/" + k for k, v in cfg["materialization"]["records"].items() if v is None]
pending += ["/coordination_lock/stat"]
assert len(pending) == 12

freeze("inputs/DRIVER_594610.HOLD.py", new_raw)
freeze("inputs/WAITING_CONFIG.E9308.json", cfg_raw)
proof = {
    "format": "hepta-a489-maintenance-independent-fixed-byte-review-v1",
    "status": "STATIC_FIXED_HOLD_DELTA_MATCHES_ONLY",
    "input_identities": {
        "predecessor_driver": identity(old_raw), "successor_driver": identity(new_raw),
        "predecessor_config": identity(cfg_old_raw), "waiting_config": identity(cfg_raw),
        "already_frozen_materialization_packet": identity(mat_raw),
    },
    "performed": "Pure Python AST/UTF-8 bytes/JSON comparison; no reviewed function was imported or invoked.",
    "executed_native_or_project_code": False, "H_calls": 0, "source_writes": 0,
    "exact_replacements": [{"before": a, "after": b} for a, b in replacements],
    "forward_full_bytes_equal": True, "inverse_full_bytes_equal": True, "inverse_full_ast_equal": True,
    "top_level_definitions": len(definition_rows),
    "byte_and_ast_identical_count": sum(x["byte_equal"] and x["ast_equal"] for x in definition_rows),
    "changed_definitions": changed_defs, "definitions": definition_rows,
    "only_changed_function_inverse_full_bytes_equal": True,
    "config_changes": cfg_changes,
    "config_exact_explicit_whitelist_equal": True,
    "expected_identity_matches_prior_actual_git_materialization_packet": True,
    "materialization_packet_scope": "Expected object/inventory contracts only, not proof of a native materialization outcome.",
    "commands": {"fix": fix, "fmt": fmt, "main_stage_calls": [ast.unparse(n) for n in stage_calls]},
    "budgets": {**budgets, "outer_seconds": 9300, "minimum_target_free_bytes": 34359738368},
    "history_current_separation": {
        "runtime_restoration_fields_exact_old": True,
        "archive_restoration_only_supervisor_copy_path_changes": True,
        "actual_prior_candidate_materialization_fields_removed": True,
        "candidate_full_inventory_and_native_projection_are_distinct": True,
        "historical_donor_seed_fmt_anchors_unchanged": True,
    },
    "lock_boundary": {
        "same_cooperative_lock_path": cfg["coordination_lock"]["path"],
        "maintenance_main_unchanged_and_no_flock": True,
        "separate_original_inheritable_EX_launcher_required": True,
        "new_launcher_or_request_reviewed_in_this_snapshot": False,
        "actual_lock_stat_present": False,
    },
    "actual_proof_fields_still_null": pending,
    "HOLD_config_rejected_by_original_approval_predicate": True,
    "future_root_approval_and_exact_launch_required": True,
    "remaining": [
        "Independent original new materialization normal/complete RESULT with all three verified audits.",
        "Exact four bound original records; raw Git metadata and gzip/index/lock proof with producer schema agreement.",
        "Separate immutable actual-bound config; retain this HOLD snapshot.",
        "Exact six-input create-only staging and original sole inheritable EX launcher/main request, with budgets unchanged.",
        "Maintenance must reread full physical inventory and complete raw Git files/stat before any stage.",
    ],
    "qualification": False,
}
raw = (json.dumps(proof, indent=2, ensure_ascii=False) + "\n").encode()
out = freeze("FROZEN_HOLD_BYTE_REVIEW.json", raw)
print(json.dumps({"report": out, "definitions": len(definition_rows), "identical": 50,
                  "replacements": 8, "pending_actual_fields": len(pending),
                  "status": proof["status"], "qualification": False}))
