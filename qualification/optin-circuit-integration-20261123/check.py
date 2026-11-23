"""Use original SDK-produced artifacts as A inputs to an isolated engineering router fit."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

from cell_experiments import data, paired_router_source as router, paired_source_gate as gate

repo = Path(__file__).resolve().parents[2]
out = Path(sys.argv[1]).resolve()
os.umask(0o077)
out.mkdir(mode=0o700)
root = out / "materials"
module_path = repo / "qualification/selected-session-mcp-20261123/qualify.py"
spec = importlib.util.spec_from_file_location("sdk_capture", module_path)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
asyncio.run(capture.run(root))
read = lambda path: json.loads(path.read_bytes())
a, b = [read(root/(slot+".json")) for slot in ("failure","correction")]
proposed = read(root/"proposed-scope.json")
assert proposed["scope"] == {"use":"train","failure":data.digest(a),"correction":data.digest(b)}
capture_result = read(root/"READOUT.json")
assert capture_result["native_original_A_grants"] == capture_result["real_people"] == 0
archive = repo / "qualification/paired-consumer-circuit-20261123/CONSUMER_CIRCUIT_ORIGINALS.zip"
assert hashlib.sha256(archive.read_bytes()).hexdigest() == "08640f268030dbb74b97cc63f1631e510848c99b8522231314b1f2a9b5c83099"
with zipfile.ZipFile(archive) as z:
    for name in z.namelist():
        if name.startswith(("original/materials/base/","original/materials/source/","original/materials/reader/")) and not name.endswith("/"):
            rel = Path(name).relative_to("original/materials")
            assert ".." not in rel.parts
            f = root/rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(z.read(name))
    pair = json.loads(z.read(next(n for n in z.namelist() if n.endswith("/paired.json"))))
router.keep(root/"parent.json",pair["candidate"])
router.keep(root/"retention.json",pair["retention"])
plan = dict(schema=router.POLICY, study=proposed["study_sha256"],
            delivery=data.digest(["engineering only",data.digest(a),data.digest(b)]),
            failure=data.digest(a), correction=data.digest(b), parent=data.digest(pair["candidate"]),
            retention=data.digest(pair["retention"]), trainer_source_sha256=router.source_hash(), timeout_seconds=180)
engineering = dict(schema="engineering_fixture",participants=0)
try:
    router._fit(root,plan,engineering)
except ValueError as err:
    assert "owner or fixture scope differs" in str(err)
else:
    raise RuntimeError("engineering principal admitted to the real training path")
try:
    result, operation = router._fit(root,plan,engineering,engineering=True)
except ValueError as err:
    if str(err) not in ("source input outside parent budget","source and retention share token IDs"):
        raise
    result = {"decision":"denied_by_registered_input_gate","reason":str(err)}
else:
    repeat, same = router._fit(root,plan,engineering,engineering=True)
    assert repeat == result and same == operation
    if "freeze_sha256" in result:
        gate_result = gate.gate(root,operation)
        router.verify_originals(operation,router.read(operation/"FROZEN.json"),router.read(operation/"COMPLETED.json"))
        result = dict(result, decision=gate_result["decision"], retention=gate_result)
    else:
        assert not (operation/"FROZEN.json").exists()
    shutil.copytree(operation,out/"operation")
report = dict(scope="engineering_fixture", originating_client="local official MCP SDK",
              study=plan["study"],failure=plan["failure"],correction=plan["correction"],
              selected_parent=plan["parent"],original_calls=capture_result["tool_calls"],result=result,
              native_A_grants=0, enrolled_people=0, new_B_arrivals=0, payments=0)
(out/"RESULT.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
(out/"input-plan.json").write_text(json.dumps(plan,sort_keys=True)+"\n")
print("COMBINED_READOUT", json.dumps(report,sort_keys=True))
