"""Reconstruct the missing CI config without running a model, runtime or SSH."""
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
from types import SimpleNamespace
import zipfile

ARCHIVE_SHA = "c549a22e56c12cdb09f9ea9708557c3f5164c803020c25aa72e47912c3d9cd7a"
CONFIG_SHA = "3cd6f5979ca0fbf9b94803da50918a18b2175553c9e9024bf537f77a2029ef30"
LABEL = "RECONSTRUCTED_FROM_FROZEN_GENERATOR_AND_RETAINED_INPUTS"
sha = lambda raw: hashlib.sha256(raw).hexdigest()
blob = lambda raw: hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
archive_path, output = map(Path, sys.argv[1:3])
assert sha(archive_path.read_bytes()) == ARCHIVE_SHA
output.mkdir(mode=0o700, parents=True, exist_ok=True)
config_path, proof_path = output/"RECONSTRUCTED_RUNTIME_CONFIG.json", output/"CONFIG_RECONSTRUCTION_PROOF.json"
assert not config_path.exists() and not proof_path.exists()
source_names = ["qualify_runtime_process_bridge.py", "runtime_stdio.py", "runtime_process_bridge.py", "qualify_runtime_campaign.py"]
names = ["local-joint/candidate.json", "runtime-joint/candidate.json", "runtime-joint/profile.json", "runtime-joint/ssh-setup.json", "runtime-joint/result.json", "runtime-joint/campaign-runtime.json", "runtime-joint/campaign-readonly-review.json", "runtime-joint/campaign-worker/campaign/RESULT.json"]
names += ["runtime-joint/campaign-worker/campaign/"+cell+"/COLD_PROCESS.json" for cell in ("memory", "predictor")]
names += ["local-joint/executed-source/cells/scripts/"+name for name in source_names]
with zipfile.ZipFile(archive_path) as archive:
    assert not any(PurePosixPath(name).name == "runtime-config.json" for name in archive.namelist())
    raw = {name: archive.read(name) for name in names}
data = {name: json.loads(value) for name,value in raw.items() if name.endswith(".json")}
origin, candidate, profile = (data[name] for name in ["local-joint/candidate.json","runtime-joint/candidate.json","runtime-joint/profile.json"])
outer, campaign, setup = (data[name] for name in ["runtime-joint/result.json","runtime-joint/campaign-runtime.json","runtime-joint/ssh-setup.json"])
assert candidate["runtime_identity"]["config_sha256"] == profile["runtime"]["config_sha256"] == CONFIG_SHA
assert candidate["origin_candidate_sha256"] == sha(raw["local-joint/candidate.json"])
assert profile["candidate_sha256"] == sha(raw["runtime-joint/candidate.json"])
assert outer["status"] == campaign["status"] == "PASS"
assert all(s["runtime"]["runtime_config_sha256"] == CONFIG_SHA for lane in (outer,campaign) for s in lane["sessions"])
source, source_proof = {}, {}
for name in source_names:
    archive_name = "local-joint/executed-source/cells/scripts/"+name
    value = raw[archive_name]
    records = [row for row in candidate["files"] if row["root"]=="cells" and row["path"]=="scripts/"+name]
    assert len(records)==1 and records[0]["sha256"]==sha(value)
    source[name] = value.decode()
    source_proof[name] = {"archive_path":archive_name,"sha256":sha(value),"git_blob_sha":blob(value)}
assert source_proof["qualify_runtime_process_bridge.py"]["git_blob_sha"] == "bf8588998f9ebc827822430c46ed4d2cf2a3a06a"
assert source_proof["runtime_stdio.py"]["git_blob_sha"] == "30cc1a412353420a65745914c64783ff7f0a10b9"
trees = {name:ast.parse(text) for name,text in source.items()}
for name, module in [("qualify_runtime_process_bridge.py","runtime_process_bridge"),("runtime_process_bridge.py","runtime_stdio")]:
    assert any(isinstance(n,ast.ImportFrom) and n.module==module and any(a.name=="canonical" and a.asname is None for a in n.names) for n in trees[name].body)
main = next(n for n in trees["qualify_runtime_process_bridge.py"].body if isinstance(n,ast.FunctionDef) and n.name=="main")
assignments = [n for n in ast.walk(main) if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=="config"]
assert len(assignments)==1 and isinstance(assignments[0].value,ast.Dict)
assignment = assignments[0]
writer = next(n for n in trees["qualify_runtime_process_bridge.py"].body if isinstance(n,ast.FunctionDef) and n.name=="write")
serializer = next(n for n in trees["runtime_stdio.py"].body if isinstance(n,ast.FunctionDef) and n.name=="canonical")
argv, campaign_argv = profile["process"]["args"], campaign["profile"]["process"]["args"]
assert argv.count("--candidate")==campaign_argv.count("--output")==1
candidate_parent = PurePosixPath(argv[argv.index("--candidate")+1]).parent
campaign_output = PurePosixPath(campaign_argv[campaign_argv.index("--output")+1])
assert campaign_output.name=="campaign-worker"
assert 'str(output / "campaign-worker")' in source["qualify_runtime_campaign.py"]
assert "candidate.parent / (" in source["qualify_runtime_process_bridge.py"]
private = PurePosixPath(profile["runtime"]["config"]).parent
assert PurePosixPath(profile["runtime"]["config"]).name=="runtime-config.json"
assert PurePosixPath(argv[argv.index("--database")+1]).parent==private
targets = {arg for row in setup if row["returncode"]==0 and row["argv"][0]=="ssh" for arg in row["argv"] if arg.startswith("ssh://")}
assert len(targets)==1
target = next(iter(targets))
keys = [PurePosixPath(row["argv"][row["argv"].index("-f")+1]) for row in setup if row["argv"][0]=="ssh-keygen"]
assert len(keys)==2 and all(path.parent==private for path in keys)
assert PurePosixPath(profile["process"]["executable"]).is_absolute()
bindings = {"private":str(private),"args.output":str(campaign_output.parent),"cell_root":profile["process"]["cwd"],"runtime_root":profile["runtime"]["source_root"],"candidate_record.hia_root":origin["hia_root"],"candidate.parent":str(candidate_parent),"sys.executable":profile["process"]["executable"],"ssh.target":target}
ns = {"json":json,"os":os,"Path":PurePosixPath,"private":private,"args":SimpleNamespace(output=campaign_output.parent),"cell_root":PurePosixPath(bindings["cell_root"]),"runtime_root":PurePosixPath(bindings["runtime_root"]),"candidate_record":origin,"candidate":SimpleNamespace(parent=candidate_parent),"sys":SimpleNamespace(executable=bindings["sys.executable"]),"ssh":SimpleNamespace(target=target)}
# Only the frozen config expression and canonical/write functions are evaluated.
# The frozen modules, main function, runtime constructors and process calls are not run.
module = ast.Module(body=[serializer,writer,assignment],type_ignores=[])
exec(compile(ast.fix_missing_locations(module),"<frozen-config-and-writer-only>","exec"),ns)
ns["write"](config_path,ns["config"])
config_path.chmod(0o600)
config_bytes = config_path.read_bytes()
matched = sha(config_bytes)==CONFIG_SHA
result = data["runtime-joint/campaign-worker/campaign/RESULT.json"]
review = data["runtime-joint/campaign-readonly-review.json"]["review"]
costs = {}
for cell in ("memory","predictor"):
    cold_name = "runtime-joint/campaign-worker/campaign/"+cell+"/COLD_PROCESS.json"
    cold, measured, training = data[cold_name],review["cells"][cell],result["cells"][cell]["training"]
    assert measured["cold_whole_wall_ns"]==cold["wall_ns"]
    assert measured["training_wall_seconds"]==training["wall_seconds"]
    costs[cell] = {"component_call_p95_ms":measured["component_call_p95_ms"],"component_call_p99_ms":measured["component_call_p99_ms"],"component_latency_scope":measured["latency_scope"],"cold_model_child_wall_ns":cold["wall_ns"],"cold_model_child_wall_seconds":cold["wall_ns"]/1e9,"cold_model_child_cpu_seconds":cold["whole_child_cpu_seconds"],"training_wall_seconds":training["wall_seconds"],"training_parent_process_cpu_seconds":training["process_cpu_seconds"],"training_measurement_scope":training["measurement_scope"],"sources":{"component_latencies":"runtime-joint/campaign-readonly-review.json#/review/cells/"+cell,"cold_model_child":cold_name,"training":"runtime-joint/campaign-worker/campaign/RESULT.json#/cells/"+cell+"/training"}}
proof = {
    "schema":"hepta.cell.runtime-config-reconstruction.v1",
    "classification":LABEL,
    "status":"EXACT_DIGEST_MATCH" if matched else "DIGEST_MISMATCH",
    "head_sha":"f8e54c63700c8ffc40c9ddaec4e3fd44817da0fb",
    "run_id":43802821002,"archive_sha256":ARCHIVE_SHA,
    "candidate_sha256":sha(raw["runtime-joint/candidate.json"]),
    "origin_candidate_sha256":sha(raw["local-joint/candidate.json"]),
    "expected_config_sha256":CONFIG_SHA,"reconstructed_config_sha256":sha(config_bytes),
    "reconstructed_config_git_blob_sha":blob(config_bytes),"reconstructed_bytes":len(config_bytes),
    "original_config_archived":False,"original_absence_limitation_preserved":True,
    "attempts":1,"guessing_or_brute_force":False,
    "serialization":"Original frozen write(path,value) calls original canonical(value), appends one LF, then fsyncs; one deterministic serialization.",
    "sources":source_proof,
    "input_records":{name:{"sha256":sha(value),"bytes":len(value)} for name,value in raw.items()},
    "bindings":bindings,
    "binding_derivation":{
        "private":"profile.runtime.config parent; cross-checked with database and both ssh-keygen output paths",
        "args.output":"parent of retained campaign --output; frozen campaign generator appends campaign-worker",
        "cell_root":"retained profile.process.cwd",
        "runtime_root":"retained profile.runtime.source_root",
        "candidate_record.hia_root":"original candidate.hia_root",
        "candidate.parent":"parent of retained profile --candidate; frozen qualifier creates runtime_candidate in original candidate.parent",
        "sys.executable":"retained profile.process.executable, recorded by frozen generator from Path(sys.executable).absolute()",
        "ssh.target":"unique ssh:// target in successful retained ssh-setup argv"
    },
    "frozen_fragments":{
        "config_assignment":ast.get_source_segment(source["qualify_runtime_process_bridge.py"],assignment),
        "write_function":ast.get_source_segment(source["qualify_runtime_process_bridge.py"],writer),
        "canonical_function":ast.get_source_segment(source["runtime_stdio.py"],serializer)
    },
    "costs":{"cells":costs,"campaign_wall_seconds":result["wall_seconds"],"campaign_parent_cpu_seconds":result["parent_cpu_seconds"],"campaign_cost_scope":result["cost_scope"],"runtime_qualifier_wall_seconds":outer["elapsed_seconds"],"campaign_runtime_wall_seconds":campaign["elapsed_seconds"],"energy_joules":result["energy_joules"],"peak_rss_bytes":result["peak_rss_bytes"]},
    "runtime_model_native_or_sshd_execution":False,
    "original_evidence_changed":False,"source_or_ref_changed":False,
    "claim":"Digest-identical reconstruction from retained inputs and frozen generator; not proof that original config bytes were archived."
}
proof_path.open("x").write(json.dumps(proof,sort_keys=True,indent=2,allow_nan=False)+"\n")
assert sha(archive_path.read_bytes())==ARCHIVE_SHA
print(json.dumps({key:proof[key] for key in ["classification","status","expected_config_sha256","reconstructed_config_sha256","reconstructed_config_git_blob_sha","reconstructed_bytes","attempts"]},sort_keys=True))
if not matched:
    raise SystemExit(1)
