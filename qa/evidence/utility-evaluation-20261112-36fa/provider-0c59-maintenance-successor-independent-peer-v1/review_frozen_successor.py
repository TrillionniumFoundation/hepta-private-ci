#!/usr/bin/env python3
"""Pure frozen-byte/schema audit; no source, subprocess, preflight, main or gates."""
import ast
import gzip
import hashlib
import json
import pathlib
import stat

HERE = pathlib.Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
AUTHOR = pathlib.Path("/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1")

def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def body(name):
    raw = (INPUTS / name).read_bytes()
    sdk = json.loads((INPUTS / (name + ".GET.original.json")).read_bytes())
    assert sdk["structuredContent"]["content"].encode() == raw
    return raw

def definitions(raw):
    text = raw.decode()
    return {n.name: {"bytes": ast.get_source_segment(text, n).encode(),
                     "ast": ast.dump(n, include_attributes=False), "line": n.lineno}
            for n in ast.parse(text).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

driver = body("driver-maintenance.HOLD.py")
config_raw = body("MAINTENANCE_CONFIG.HOLD.json")
launcher = body("LAUNCHER.HOLD.py")
cfg = json.loads(config_raw)
assert identity(driver)["git_blob"] == "3a0f6dec8127aa9587129d6e0f24bad55837ca13"
assert identity(config_raw)["git_blob"] == "f2092840e7e59ba94d86709cdbe9d995b681f826"
assert identity(launcher)["git_blob"] == "9a2262f1e5cc36a587ea10c32c102f894ea1cfbb"
old = (AUTHOR / "inputs/DRIVER_6632.original.py").read_bytes()
assert identity(old)["git_blob"] == "6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735"
old_def, new_def = definitions(old), definitions(driver)
same = [k for k in old_def if k in new_def and
        old_def[k]["bytes"] == new_def[k]["bytes"] and old_def[k]["ast"] == new_def[k]["ast"]]
changed = [k for k in old_def if k in new_def and k not in same]
assert len(old_def) == 50 and len(new_def) == 51 and len(same) == 45
assert changed == ["validate_materialization", "validate_runtime_restoration", "validate_config", "initial_preflight"]
assert set(old_def) - set(new_def) == {"validate_source_advance"}
assert set(new_def) - set(old_def) == {"validate_archive_restoration", "validate_materialization_current"}
old_launcher = (AUTHOR / "inputs/ACTUAL_V5_LAUNCHER.original.py").read_bytes()
old_l, new_l = definitions(old_launcher), definitions(launcher)
assert set(old_l) == set(new_l) == {"need", "sha", "oid", "read", "save"}
assert all(old_l[k]["bytes"] == new_l[k]["bytes"] and old_l[k]["ast"] == new_l[k]["ast"] for k in old_l)
old_cfg_raw = (AUTHOR / "inputs/APPROVED_OLD_CONFIG.original.json").read_bytes()
assert identity(old_cfg_raw)["git_blob"] == "a66ab71a3504f29240da6048ca2c45ca3735e89b"
old_cfg = json.loads(old_cfg_raw)
preserved_cfg = [k for k in old_cfg if k in cfg and old_cfg[k] == cfg[k]]
for key in ("environment", "tool_files", "v8_files", "formatter_tool_files", "runtime_restoration",
            "inherited_source_environment", "tool_identity_projection", "fmt_argv", "fix_seconds",
            "fmt_seconds", "preflight_seconds", "record_seconds", "minimum_target_free_bytes",
            "create_target_if_absent", "test_commands_authorized", "remote_ref_updates_authorized"):
    assert key in preserved_cfg
assert cfg["fix_argv"] == old_cfg["fix_argv"] + ["-p", "codex-hepta-learning-ledger"]
assert cfg["outer_timeout_seconds"] == 9300
assert cfg["status"] == "HOLD_PENDING_ROOT_EXACT_EXECUTION_APPROVAL" and cfg["root_execution_approved"] is False

# Extract only these exact pure predicates. Never import the original module,
# initialize its global main state, call preflight/main, or read its native paths.
selected = {"check", "nodup", "parse", "sha256", "oid", "pin_bytes", "jbytes",
            "project_runtime_file", "parse_supervisor", "validate_materialization",
            "validate_runtime_restoration", "validate_archive_restoration"}
tree = ast.parse(driver.decode())
pure = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in selected], type_ignores=[])
assert {n.name for n in pure.body} == selected
ns = {"hashlib": hashlib, "json": json, "pathlib": pathlib, "gzip": gzip, "stat": stat, "cfg": cfg, "result": {}}
constant_names = {"REPO", "MATERIALIZATION_DONOR", "HISTORICAL_RUNTIME_REPO", "HEAD", "TREE", "PARENTS",
                  "DONOR_HEAD", "DONOR_TREE", "COORDINATION_LOCK", "NATIVE_INVENTORY", "SUCCESSOR_INVENTORY",
                  "LEAVES", "DEPOT", "TARGET", "C0F", "A96", "SEED_HEAD", "SEED_TREE", "SEED_PARENTS"}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in constant_names:
        # These frozen constant expressions contain only literals, Path, and prior constants.
        assert not any(isinstance(x, (ast.Lambda, ast.Await, ast.Yield, ast.NamedExpr, ast.ListComp, ast.DictComp)) for x in ast.walk(node.value))
        for call in [x for x in ast.walk(node.value) if isinstance(x, ast.Call)]:
            assert isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
            assert call.func.value.id == "pathlib" and call.func.attr == "Path"
        ns[node.targets[0].id] = eval(compile(ast.Expression(node.value), "<frozen-constants>", "eval"), ns)
exec(compile(pure, "<exact-selected-proof-predicates>", "exec"), ns)

memory_inputs, retained = {}, {}
proof_inputs = []
def put(remote_path, name, pin):
    raw = body(name)
    ns["pin_bytes"](raw, pin, name)
    assert str(remote_path) not in memory_inputs
    memory_inputs[str(remote_path)] = raw
    proof_inputs.append({"name": name, **identity(raw)})

mat = cfg["materialization"]
put(mat["result_path"], "MATERIALIZATION_RESULT.original.json", mat["result"])
put(mat["supervisor_path"], "MATERIALIZATION_SUPERVISOR.original.json", mat["supervisor"])
mat_parent = pathlib.PurePosixPath(mat["result_path"]).parent
for key, remote, local in (("command_records", "COMMANDS.json", "MATERIALIZATION_COMMANDS.original.json"),
                           ("mutation_records", "MUTATION_INTENTS.json", "MATERIALIZATION_MUTATIONS.original.json"),
                           ("input_records", "INPUT_IDENTITIES.before.json", "MATERIALIZATION_INPUTS.original.json"),
                           ("artifact_records", "ARTIFACTS.json", "MATERIALIZATION_ARTIFACTS.original.json")):
    put(mat_parent / remote, local, mat["records"][key])
metadata = body("MATERIALIZATION_GIT_METADATA.original.json")
ns["pin_bytes"](metadata, mat["git_metadata"], "actual original Git metadata")
compressed = gzip.compress(metadata, mtime=0)
ns["pin_bytes"](compressed, mat["git_metadata_gzip"], "exact reconstructed gzip, not a second native read")
memory_inputs[str(mat_parent / "final.git-metadata.json.gz")] = compressed
for group, names in (("runtime_restoration", (("result", "HISTORICAL_RUNTIME_RESULT.original.json"),
                                             ("supervisor", "HISTORICAL_RUNTIME_NORMAL.original.json"),
                                             ("environment", "HISTORICAL_ENV8B62.original.json"))),
                     ("archive_restoration", (("result", "RESTORE_V3_RESULT.original.json"),
                                              ("supervisor", "RESTORE_V3_NORMAL.original.json"),
                                              ("archive_readback", "ARCHIVE_READBACK.original.json"),
                                              ("artifacts", "RESTORE_V3_ARTIFACTS.original.json")))):
    for key, name in names:
        put(cfg[group][key + "_path"], name, cfg[group][key])

def memory_read_input(path, pin, maximum=40000000):
    raw = memory_inputs[str(path)]
    assert len(raw) <= maximum
    return ns["pin_bytes"](raw, pin, str(path))

def memory_write(name, raw):
    assert name not in retained
    retained[name] = bytes(raw)
    return {"name": name, **identity(raw)}

ns["read_input"], ns["write"] = memory_read_input, memory_write
observed = ns["validate_materialization"]()
runtime = ns["validate_runtime_restoration"]()
assert retained["MATERIALIZATION_GIT_METADATA.original.json"] == metadata
assert runtime["explicit_environment"] == cfg["environment"]
for name, actual in cfg["tool_files"].items():
    assert ns["project_runtime_file"](runtime["tool_and_material_files"]["tool_" + name]) == actual
for name, role in (("RUSTY_V8_ARCHIVE", "v8-sandbox-archive"), ("RUSTY_V8_SRC_BINDING_PATH", "v8-sandbox-bindings")):
    assert ns["project_runtime_file"](runtime["tool_and_material_files"][role]) == cfg["v8_files"][name]
assert runtime["inherited_source_environment"] == cfg["inherited_source_environment"]

# Schema projection only. No pack/index bytes or filesystem stat are invented:
# each projected record is derived from the actual producer's original metadata.
rows = json.loads(metadata)
stat_keys = {"st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"}
projected, rebuilt = [], []
assert len(rows) == 6 and len({r["path"] for r in rows}) == 6
for row in rows:
    s = row["stat"]
    assert set(s) == stat_keys and stat.S_ISREG(s["st_mode"]) and s["st_nlink"] == 1
    assert row["bytes"] == s["st_size"]
    projected.append({"path": row["path"], "mode": stat.S_IMODE(s["st_mode"]), "device": s["st_dev"],
                      "inode": s["st_ino"], "nlink": s["st_nlink"], "mtime_ns": s["st_mtime_ns"],
                      "ctime_ns": s["st_ctime_ns"], "kind": "file", "bytes": row["bytes"], "sha256": row["sha256"]})
    rebuilt.append({k: row[k] for k in ("path", "bytes", "sha256", "git_blob", "stat")})
assert ns["jbytes"](rebuilt) == metadata

report = {
    "format": "hepta-independent-maintenance-successor-frozen-dataflow-v1",
    "status": "FROZEN_PROOF_SCHEMA_AND_BYTE_DELTA_CONSISTENT_NOT_EXECUTION",
    "driver": identity(driver), "hold_config": identity(config_raw), "launcher": identity(launcher),
    "original_driver": identity(old), "original_launcher": identity(old_launcher),
    "old_definition_count": len(old_def), "new_definition_count": len(new_def),
    "unchanged_definitions_byte_and_ast": same, "changed_definitions": changed,
    "removed_definitions": sorted(set(old_def) - set(new_def)), "new_definitions": sorted(set(new_def) - set(old_def)),
    "five_launcher_helpers_byte_and_ast_equal": sorted(old_l),
    "preserved_config_sections": preserved_cfg, "only_fix_argv_addition": ["-p", "codex-hepta-learning-ledger"],
    "exact_selected_pure_functions": sorted(selected), "actual_original_proof_inputs": proof_inputs,
    "materialization_predicates_accept_actual_pins": True,
    "historical_runtime_and_separate_archive_v3_predicates_accept_actual_pins": True,
    "runtime_environment_tools_v8_source_env_projections_equal": True,
    "actual_materialization_commands": len(json.loads(memory_inputs[str(mat_parent / "COMMANDS.json")])) ,
    "actual_materialization_mutations": len(json.loads(memory_inputs[str(mat_parent / "MUTATION_INTENTS.json")])) ,
    "original_metadata": identity(metadata), "exact_recovered_gzip": identity(compressed),
    "metadata_stat_schema_keys": sorted(stat_keys), "metadata_file_paths": [r["path"] for r in rows],
    "producer_rows_to_maintenance_file_projection": projected,
    "metadata_original_serializer_roundtrip_equal": True,
    "original_metadata_scope": "All six regular Git files and their original nine stat fields; not a historical directory-stat snapshot.",
    "future_current_continuity_required": "Unexecuted validate_materialization_current must full-read all six native files, stat-match them, reproduce 2234 original bytes, authenticate commit and match actual complete source/raw Git. Original metadata_inventory adds full directories and final whole-.git byte equality.",
    "in_memory_retained_names": sorted(retained),
    "scope_limits": {"entire_driver_imported": False, "preflight_or_main_called": False,
                     "native_paths_opened": False, "git_or_subprocess_called": False,
                     "H_called": False, "source_changed": False, "Cargo_formatter_QA_tests": 0,
                     "future_maintenance_or_qualification_pass": False,
                     "gzip_reconstruction_is_second_native_payload_read": False}}
target = HERE / "FROZEN_DATAFLOW.json"
with target.open("xb") as stream:
    stream.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
print(json.dumps({"report": str(target), **identity(target.read_bytes()), "unchanged_definitions": len(same),
                  "actual_materialization_commands": report["actual_materialization_commands"],
                  "actual_materialization_mutations": report["actual_materialization_mutations"],
                  "pure_proof_predicates": "accepted", "future_execution": False}, sort_keys=True))
