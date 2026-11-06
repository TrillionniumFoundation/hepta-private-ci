#!/usr/bin/env python3
"""Read only closed r18 inputs; write independent audit outputs beside this script.

Uses Python standard library only. Does not invoke Git, Cargo, Rust, or a test runner.
The archived Git modes, not tar or extracted filesystem permissions, build the tree.
"""
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json
import re
import tarfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
CHECKPOINT = ROOT / "native-validation-results/checkpoint-r18"
FORMAL_ROOT = ROOT / "hepta-cell/qualification/cell-unification-20261106/native-evidence"
FORMAL = FORMAL_ROOT / "r18-workspace-checkpoint"
BASE_COMMIT = "bef6fa7645df9df12b69fda499e97eed25de6c75"
BASE_TREE = "ce997fd958b8073d99b1e5bc302b7a0188fb4c3b"
TARGET_COMMIT = "2d7ad1d60019f35fc13d84138ceb2755d914f434"
TARGET_TREE = "ffa0a37f4616c5563169c7f0a9305bf6c982d58b"
ARCHIVE_PIN = json.loads((OUT / "input/ARCHIVE-PIN.json").read_bytes())
ARCHIVE_SHA = ARCHIVE_PIN["sha256"]
BASE_INPUT_SHA = "56f7a3076b782105db36509abe860d9872c27bfa41685fb80b31e68b1a5abda1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_hash(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def serialized(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def write_json(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(serialized(value))


def file_pin(path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "bytes": len(data), "sha256": sha(data)}


def tree_hash(entries):
    data = bytearray()
    for name, entry in sorted(entries.items(), key=lambda item: item[0].encode() + (b"/" if item[1]["type"] == "tree" else b"")):
        mode = "40000" if entry["type"] == "tree" else entry["mode"].lstrip("0")
        data.extend(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(entry["sha"]))
    return git_hash("tree", bytes(data))


archive_path = ROOT / "native-validation-results/checkpoint-r18-closed.tar.gz"
archive_raw = archive_path.read_bytes()
require((len(archive_raw), sha(archive_raw)) == (ARCHIVE_PIN["bytes"], ARCHIVE_SHA), "closed archive size/SHA mismatch")
with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as archive:
    members = archive.getmembers()
    require(len(members) == 196, "archive member count")
    require(len({m.name for m in members}) == len(members), "duplicate tar member")
    for member in members:
        path = PurePosixPath(member.name)
        require(member.isfile() and not path.is_absolute() and ".." not in path.parts, "nonregular or unsafe member: " + member.name)
    blobs = {m.name: archive.extractfile(m).read() for m in members}
    tar_modes = {m.name: format(m.mode, "o") for m in members}

index_raw = blobs["INDEX.json"]
require(index_raw == (CHECKPOINT / "INDEX.json").read_bytes(), "INDEX extracted bytes differ")
index = json.loads(index_raw)
require(index["source_tree"] == TARGET_TREE and index["source_commit"] == TARGET_COMMIT, "INDEX source identity")
listed = {e["path"]: e for e in index["files"]}
require(len(listed) == 195 and set(listed) == set(blobs) - {"INDEX.json"}, "INDEX membership")
member_readback = []
for name, raw in blobs.items():
    require(raw == (CHECKPOINT / name).read_bytes(), "extracted archive bytes differ: " + name)
    if name != "INDEX.json":
        entry = listed[name]
        require((len(raw), sha(raw)) == (entry["bytes"], entry["sha256"]), "member size/hash: " + name)
        if name.startswith("source/"):
            require(entry["mode"] in ("100644", "100755"), "INDEX Git mode")
            require((int(entry["mode"], 8) & 0o777) == int(tar_modes[name], 8), "source permission bits differ from Git mode: " + name)
    member_readback.append({"path": name, "bytes": len(raw), "sha256": sha(raw), "archive_mode": tar_modes[name], "extracted_bytes_equal": True})

source_raw = blobs["evidence/native-candidate-r17-source.json"]
source = json.loads(source_raw)
require(source["source_tree"] == TARGET_TREE and source["source_commit"] == TARGET_COMMIT and source["applied_stage"] == 46 and BASE_COMMIT in source["parent_identities"], "native source identity")
source_entries = {e["path"]: e for e in source["changed_files"]}
require(len(source_entries) == 180, "changed source count")
require({"source/" + p for p in source_entries} == {p for p in blobs if p.startswith("source/")}, "source inventory membership")
require({str(p.relative_to(CHECKPOINT / "source")) for p in (CHECKPOINT / "source").rglob("*") if p.is_file()} == set(source_entries), "extracted source has extra or missing files")
computed_sources = []
for name, entry in source_entries.items():
    data = blobs["source/" + name]
    blob = git_hash("blob", data)
    require((len(data), sha(data), blob) == (entry["bytes"], entry["sha256"], entry["git_blob"]), "source raw/hash/blob mismatch: " + name)
    require(blob == listed["source/" + name]["git_blob"], "archive Git blob differs: " + name)
    require(entry["mode"] in ("100644", "100755") and entry["mode"] == listed["source/" + name]["mode"], "unsupported or mismatched Git source mode")
    computed_sources.append({"path": name, "mode": entry["mode"], "type": "blob", "sha": blob, "bytes": len(data), "sha256": sha(data)})

base_path = OUT / "input/original-base-direct-map.json.gz"
base_raw = gzip.decompress(base_path.read_bytes())
require(sha(base_raw) == BASE_INPUT_SHA, "retained original-base input SHA")
base_input = json.loads(base_raw)
require(base_input["source_base_commit"] == BASE_COMMIT and base_input["base_tree"] == BASE_TREE and not base_input["base_listing_truncated"], "original base identity")
base = {e["path"]: dict(e) for e in base_input["base_entries"]}
require(len(base) == len(base_input["base_entries"]), "duplicate base path")
fetch_manifest = json.loads((OUT / "input/base-tree-fetch-manifest.json").read_bytes())
directory_paths = {"codex-mcp": "codex-rs/codex-mcp", "codex-mcp-src": "codex-rs/codex-mcp/src", "session": "codex-rs/core/src/session", "tools": "codex-rs/core/src/tools", "runtimes": "codex-rs/core/src/tools/runtimes", "zsh-fork": "codex-rs/core/src/tools/runtimes/zsh_fork", "common": "codex-rs/core/tests/common"}
base_additions = []
for fetch in fetch_manifest["files"]:
    data = (OUT / fetch["path"]).read_bytes()
    require((len(data), sha(data)) == (fetch["bytes"], fetch["sha256"]), "fetch retained bytes")
    tree = json.loads(data)
    directory = directory_paths[fetch["name"]]
    require(directory in base and base[directory]["sha"] == fetch["sha"] == tree["sha"], "base direct tree pin: " + directory)
    require(tree["truncated"] is False, "truncated direct tree")
    children = {}
    for child in tree["tree"]:
        require("/" not in child["path"] and child["path"] not in (".", "..", ""), "nondirect child")
        require(child["path"] not in children, "duplicate direct child")
        children[child["path"]] = {k: child[k] for k in ("mode", "type", "sha")}
        full_path = directory + "/" + child["path"]
        new_entry = {"path": full_path, **children[child["path"]]}
        if full_path in base:
            require(base[full_path] == new_entry, "conflicting base addition")
        base[full_path] = new_entry
    computed = tree_hash(children)
    require(computed == tree["sha"], "GitData direct tree content hash")
    base_additions.append({"path": directory, "direct_children": len(children), "requested_sha": fetch["sha"], "computed_sha": computed, "response_file": fetch["path"], "response_sha256": fetch["sha256"], "url": fetch["url"]})

children = defaultdict(dict)
for path, entry in base.items():
    parent, _, name = path.rpartition("/")
    children[parent][name] = {k: entry[k] for k in ("mode", "type", "sha")}
base_verified = [{"path": "", "sha": tree_hash(children[""])}]
require(base_verified[0]["sha"] == BASE_TREE, "original top-level tree failed independent hash")
for pin in base_input["existing_directory_pins"]:
    computed = tree_hash(children[pin["path"]])
    require(computed == pin["sha"], "original base child tree hash: " + pin["path"])
    base_verified.append({"path": pin["path"], "sha": computed})

ancestors = {""}
for entry in computed_sources:
    parent, _, name = entry["path"].rpartition("/")
    children[parent][name] = {k: entry[k] for k in ("mode", "type", "sha")}
    while parent:
        ancestors.add(parent)
        parent = parent.rpartition("/")[0]
require(len(ancestors) == 65, "r18 dynamic ancestor count")
rebuild = []
for directory in sorted(ancestors, key=lambda p: (p.count("/") + bool(p), p), reverse=True):
    computed = tree_hash(children[directory])
    rebuild.append({"path": directory, "computed_tree": computed, "direct_children": len(children[directory])})
    if directory:
        parent, _, name = directory.rpartition("/")
        children[parent][name] = {"mode": "040000", "type": "tree", "sha": computed}
computed_tree = tree_hash(children[""])
require(computed_tree == TARGET_TREE, "independent r18 tree differs")

# Closed r18 phase-specific readback follows once the original archive is available.

# Closed r18 phase-specific checks; no commands outside Python are invoked.
environment=json.loads(blobs["evidence/native-workspace-r18-environment.json"])
scope=json.loads(blobs["evidence/native-workspace-r18-scope.json"])
metadata_raw=blobs["evidence/native-workspace-r18-metadata.json"]
metadata=json.loads(metadata_raw)
receipt=json.loads(blobs["evidence/native-workspace-r18-tests-receipt.json"])
raw_log=blobs["evidence/native-workspace-r18-tests.log"]
resources=blobs["evidence/native-workspace-r18-tests-resources.txt"]
review=json.loads(blobs["evidence/native-workspace-r18-result-review.json"])
post=json.loads(blobs["evidence/native-workspace-r18-source-post-verification.json"])
terminal=json.loads(blobs["evidence/native-workspace-r18-terminal-process-status.json"])
command=["just","test","--locked","--retries","0"]
require(receipt["command"]==index["command"]==review["command"]==command,"original no-p command")
require(receipt["exit_code"]==review["exit_code"]==terminal["exit_code"]==101,"terminal exit101")
require(receipt["source_tree"]==environment["source_tree"]==review["source_tree"]==post["source_tree"]==TARGET_TREE,"phase trees")
require(receipt["source_commit"]==review["source_commit"]==post["source_commit"]==TARGET_COMMIT,"phase commits")
require(receipt["source_manifest"]==environment["source_manifest"]=="native-candidate-r17-source.json","source manifest reference")
require(environment["source_manifest_sha256"]==review["source_manifest_sha256"]==sha(source_raw),"manifest rawhash")
require(len(raw_log)==56496 and sha(raw_log)==receipt["log_sha256"]==review["log_sha256"]=="cedada3433e2c782b423857f8abeff744fdf45c3de4523c3c312d2e15586d3ad","full rawlog")
require(sha(resources)==receipt["resources_sha256"]==review["resources_sha256"],"resources rawhash")
require(receipt["elapsed_seconds"]==review["elapsed_seconds"]==1130.7959480285645,"elapsed receipt")
require(abs(receipt["end_unix"]-receipt["start_unix"]-receipt["elapsed_seconds"])<1e-9,"elapsed arithmetic")
require(re.findall(rb"^[ \t]*Exit status: (\d+)\s*$",resources,re.M)==[b"101"],"resource exit")
require(b'Command being timed: "just test --locked --retries 0"' in resources,"resource command")
require(receipt["retries"]==0 and receipt["features"]=="unchanged_defaults" and receipt["filters"]=="no_additions","selection")
require(not terminal["cancelled"] and not terminal["timed_out"] and not terminal["automatic_retry"] and terminal["state"]=="failed","natural failure")
require(terminal["output_complete"] and terminal["output_durable"] and terminal["terminal_publication_confirmed"],"durable terminal")
require(terminal["job_id"]==review["job_id"]=="1a1b0205999-fc05-6e4e","job identity")
require(post["changed_source_count"]==len(source_entries) and post["unstaged_changed_paths"]==[] and post["untracked_paths"]==[],"post source")
require(post["lock_sha256"]==source["lock_sha256"]=="4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c","lock")
require(scope["metadata_command"]==["cargo","metadata","--locked","--no-deps","--format-version","1"] and scope["metadata_sha256"]==sha(metadata_raw),"metadata binding")
member_ids=metadata["workspace_members"];default_ids=metadata["workspace_default_members"]
packages={p["id"]:p["name"] for p in metadata["packages"]}
require(len(member_ids)==len(set(member_ids))==len(default_ids)==len(set(default_ids))==193 and set(member_ids)==set(default_ids),"193 unique defaults")
require(scope["workspace_members"]==[{"id":p,"name":packages[p]} for p in member_ids],"metadata member names")
require(scope["workspace_default_members"]==[{"id":p,"name":packages[p]} for p in default_ids],"metadata default names")
require(environment["workspace_member_count"]==environment["workspace_default_member_count"]==review["workspace_member_count"]==review["workspace_default_member_count"]==193,"reported count")
selection=environment["selection"]
require(selection["CARGO_PROFILE_TEST_DEBUG"]==selection["CARGO_PROFILE_DEV_DEBUG"]=="0" and selection["CARGO_BUILD_JOBS"]==selection["NEXTEST_TEST_THREADS"]=="2","recorded profile")
require(selection["HEPTA_NEXTTEST_FULL_METADATA"] is None and selection["CARGO_BUILD_TARGET"] is None and selection["RUSTFLAGS"] is None,"default target and selection")
absence={n:len(re.findall(p,raw_log,re.M)) for n,p in {
 "nextest_starting_lines":rb"^[ \t]*Starting \d+ tests across ",
 "nextest_summary_lines":rb"^[ \t]*Summary \[",
 "nextest_execution_rows":rb"^[ \t]*(PASS|FAIL|TIMEOUT|SKIP)[ \t]+\[[^\r\n]+\][ \t]+\S+[ \t]+[^\r\n]+",
 "libtest_running_lines":rb"^[ \t]*running \d+ tests?",
 "libtest_result_lines":rb"^[ \t]*test result: "}.items()}
require(all(n==0 for n in absence.values()),"unexpected execution evidence")
errors=list(re.finditer(rb"^error\[(E\d+)\]: ([^\r\n]+)",raw_log,re.M))
require(len(errors)==1 and errors[0][1]==b"E0308","single source compiler error")
start=errors[0].start();end=raw_log.index(b"warning: build failed, waiting for other jobs to finish...",start)
primary=raw_log[start:end];full=review["error_block"].encode()
require(raw_log[start:start+len(full)]==full,"full compiler block raw bytes")
require(b"app-server/tests/suite/v2/process_exec.rs:251:9" in primary and b"this expression has type `()`" in primary and b"expected `()`, found `JSONRPCMessage`" in primary,"actual mismatch")
require(b"cargo test --no-run --message-format json-render-diagnostics --locked" in full,"no-run phase")
require(review["compiler_error_count"]==1 and review["compiler_error_code"]=="E0308" and not review["test_execution_started"] and review["executed_test_count"] is None,"review agrees")
require(index["outcome"]==review["outcome"]=="COMPILATION_FAILED" and not index["test_execution_started"],"index outcome")
blocks=[{"code":"E0308","path":"codex-rs/app-server/tests/suite/v2/process_exec.rs","line":251,"primary":{"byte_range_half_open":[start,end],"bytes":len(primary),"sha256":sha(primary),"excerpt":primary.decode()},"including_terminal_wrappers":{"byte_range_half_open":[start,start+len(full)],"bytes":len(full),"sha256":sha(full),"excerpt":full.decode()},"aggregate_lines_not_counted_as_additional_source_errors":True}]
blocker=json.loads(blobs["evidence/native-workspace-r18-app-server-blocker-input.json"])
with tarfile.open(fileobj=io.BytesIO(blobs["evidence/native-workspace-r18-app-server-blocker-input.tar.gz"]),mode="r:gz") as nested:
 ms=nested.getmembers()
 require(len(ms)==6 and all(m.isfile() and not PurePosixPath(m.name).is_absolute() and ".." not in PurePosixPath(m.name).parts for m in ms),"nested regular inputs")
 inner={m.name:nested.extractfile(m).read() for m in ms}
 require(len(inner)==6,"nested duplicate")
require(inner["source-manifest.json"]==blobs["evidence/native-workspace-r18-app-server-blocker-input.json"],"nested manifest raw")
for e in blocker["files"]:
 b=inner["source/"+e["path"]]
 require((len(b),sha(b),git_hash("blob",b))==(e["bytes"],e["sha256"],e["git_blob"]),"blocker original "+e["path"])
 require(e["unchanged_from_bef"] and e["base_blob"]==e["git_blob"],"base blocker identity")
require(blocker["source_tree"]==TARGET_TREE and blocker["source_commit"]==TARGET_COMMIT and blocker["nearest_instructions"]==["AGENTS.md"],"blocker source and instructions")
prereqs=[]
for e in environment["project_gate_prerequisites"]:
 raw=blobs["evidence/"+e["path"]];d=json.loads(raw)
 require(sha(raw)==e["sha256"] and d["source_tree"]==e["source_tree"]==TARGET_TREE and d["exit_code"]==e["exit_code"]==0 and d["log_sha256"]==e["log_sha256"],"prior project prerequisite")
 prereqs.append({"receipt":e["path"],"sha256":sha(raw),"exit_code":0,"transferred_as_r18_result":False})
require(len(prereqs)==2,"prior project receipts")
formal=[]
for name in sorted(n for n in blobs if n.startswith("evidence/")):
 filename=name.split("/",1)[1];paths=[p for p in [FORMAL/filename,FORMAL/(filename+".gz")] if p.is_file()]
 require(len(paths)==1,"formal attachment "+filename)
 p=paths[0];stored=p.read_bytes();raw=gzip.decompress(stored) if p.name.endswith(".gz") and not filename.endswith(".gz") else stored
 require(raw==blobs[name],"formal raw bytes "+filename)
 formal.append({**file_pin(p),"original_member":name,"original_bytes":len(raw),"original_sha256":sha(raw),"lossless_gzip":raw!=stored,"exact":True})
require(len(formal)==15,"fifteen original evidence files")
write_json("ARCHIVE-MEMBER-READBACK.json",{"schema":"hepta.r18-independent-archive-readback.v1","archive":file_pin(archive_path),"regular_members":len(members),"index_entries":len(listed),"members":member_readback,"mode_semantics":"Source INDEX Git mode100644 includes file type; tar mode644 is permission bits. Evidence INDEX has no mode. The Git tree uses native Git mode, not tar mode."})
write_json("TREE-REBUILD.json",{"schema":"hepta.r18-independent-source-tree.v1","base_commit":BASE_COMMIT,"base_tree":BASE_TREE,"base_input_decompressed_sha256":sha(base_raw),"base_direct_trees_verified":base_verified,"supplemental_original_base_trees":base_additions,"source_commit":TARGET_COMMIT,"source_files":computed_sources,"source_count":len(computed_sources),"dynamic_ancestor_count":len(ancestors),"rebuilt_directories":rebuild,"computed_tree":computed_tree,"expected_tree":TARGET_TREE,"exact":True,"root_target_tree_output_used_as_input":False})
write_json("COMPILER-FAILURE-BLOCKS.json",{"schema":"hepta.r18-independent-compiler-blocks.v1","raw_log_sha256":sha(raw_log),"source_error_count":1,"blocks":blocks,"executed_test_failure_blocks":[],"test_execution_started":False})
write_json("TEST-EXECUTION-ABSENCE.json",{"schema":"hepta.r18-independent-test-execution-absence.v1","log_bytes":len(raw_log),"log_sha256":sha(raw_log),"matched_line_counts":absence,"test_execution_started":False,"test_terminal_counts":None,"reason":"cargo test --no-run failed before nextest execution; zero observed execution rows are not a completed zero-PASS gate."})
write_json("WORKSPACE-SCOPE.json",{"schema":"hepta.r18-independent-workspace-scope.v1","metadata_sha256":sha(metadata_raw),"command":command,"workspace_members":193,"default_members":193,"default_equals_all_members":True,"members":[{"id":p,"name":packages[p]} for p in member_ids],"selection":selection,"execution_qualified":False})
resource_values={}
for key,pattern in {"user_seconds":rb"User time \(seconds\): ([\d.]+)","system_seconds":rb"System time \(seconds\): ([\d.]+)","maximum_resident_set_kbytes":rb"Maximum resident set size \(kbytes\): (\d+)","wall_time_text":rb"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([^\r\n]+)"}.items():
 m=re.search(pattern,resources);require(m is not None,"resource field "+key);resource_values[key]=m[1].decode()
report={"schema":"hepta.r18-independent-closed-readback.v1","status":"READBACK_COMPLETE_GATE_COMPILE_FAILED_TEST_EXECUTION_NOT_STARTED","source_commit":TARGET_COMMIT,"source_tree":computed_tree,
"archive":file_pin(archive_path),"archive_regular_members":len(members),"archive_index_entries":len(listed),"source_files":len(computed_sources),"original_evidence_files":15,
"source_reconstruction":{"method":"Offline Git blob/tree hashing from original framework base direct children plus seven immutable original-base direct responses; no root target tree output or Git command used.","base_commit":BASE_COMMIT,"base_tree":BASE_TREE,"computed_tree":computed_tree,"exact":True,"git_modes_not_tar_modes_used":True},
"source_phase_binding":{"pre_manifest":file_pin(CHECKPOINT/"evidence/native-candidate-r17-source.json"),"environment_source_hash_exact":True,"all180_raw_sha_blob_mode_verified":True,"post":file_pin(CHECKPOINT/"evidence/native-workspace-r18-source-post-verification.json"),"post_unstaged_and_untracked_empty":True,"lock_sha256":post["lock_sha256"],"harness":file_pin(CHECKPOINT/"evidence/native-workspace-r18-command.sh"),"harness_not_executed_by_auditor":True},
"workspace_scope":{"command":command,"package_selector_added":False,"members":193,"default_members":193,"independent_full_metadata_parse":True,"retries":0,"features":"Cargo defaults","platform":"native Linux target","execution_qualified":False},
"terminal":{"job_id":terminal["job_id"],"exit_code":101,"elapsed_seconds":receipt["elapsed_seconds"],"raw_log_bytes":len(raw_log),"raw_log_sha256":sha(raw_log),"resources_sha256":sha(resources),"receipt_log_resources_exit_match":True,"cancelled":False,"timed_out":False,"automatic_retry":False,"test_execution_started":False,"test_terminal_counts":None,"observed_execution_rows":0,"starting_lines":0,"summary_lines":0,"zero_row_count_is_not_zero_PASS_run":True},
"compiler_failure":{"source_error_count":1,"code":"E0308","package":"codex-app-server","target":"test all","source_path":"codex-rs/app-server/tests/suite/v2/process_exec.rs","source_line":251,"primary_byte_range_half_open":[start,end],"full_error_byte_range_half_open":[start,start+len(full)],"nested_input_files_verified":blocker["files"]},
"resources":{"original":file_pin(CHECKPOINT/"evidence/native-workspace-r18-tests-resources.txt"),"parsed_original_values":resource_values,"shared_filesystem_free_before":environment["free_bytes_before"],"shared_filesystem_free_at_gate_end":receipt["free_bytes_after"],"shared_filesystem_free_at_archive_packaging":post["free_bytes_at_archive_verification"],"samples_are_separate_shared_filesystem_observations":True,"delta_not_interpreted_as_exclusive_gate_cost":True},
"prior_project_prerequisites":prereqs,"formal_original_readback":formal,
"artifacts":{n:file_pin(OUT/n) for n in ["ARCHIVE-MEMBER-READBACK.json","TREE-REBUILD.json","COMPILER-FAILURE-BLOCKS.json","TEST-EXECUTION-ABSENCE.json","WORKSPACE-SCOPE.json"]},
"reproduction":{"script":file_pin(Path(__file__)),"original_base_input":file_pin(base_path),"original_base_fetch_manifest":file_pin(OUT/"input/base-tree-fetch-manifest.json"),"archive_pin":file_pin(OUT/"input/ARCHIVE-PIN.json")},
"boundaries":["No Rust, Git command, test runner, native mutation, process signal, or active r19/r20 log was used.","Independent readback is not a newly executed test gate.","Prior r17 PASS is not an r18 workspace result or source47 qualification.","All180 sources were read from the r18 archive, not substituted from r17/r19.","Default test configuration does not imply all features/platforms/external services/doctests/benchmarks/Bazel/Python coverage."]}
write_json("INDEPENDENT-READBACK.json",report)
print(json.dumps({"report":file_pin(OUT/"INDEPENDENT-READBACK.json"),"tree":computed_tree,"members":len(members),"source_files":len(computed_sources),"workspace_members":193,"exit_code":101,"test_execution_started":False,"test_terminal_counts":None,"primary_error_range":[start,end],"full_error_range":[start,start+len(full)]},indent=2))
