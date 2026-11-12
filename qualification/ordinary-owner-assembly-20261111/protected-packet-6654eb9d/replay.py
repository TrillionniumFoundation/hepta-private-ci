import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import tomllib
import traceback

PACKET = Path("/workspace/scratch/af52a6167a5b/protected-v16-current-input.json")
EXPECTED_PACKET = "6654eb9d7116e1e47b1373c7a4d7671327a82a78fbeb70fa7b7bafe007ed57ed"
WORK = Path("/workspace/scratch/af52a6167a5b/protected-v16-chain-nextuse-20261112-v1")
TOOLS = Path("/workspace/scratch/af52a6167a5b/protected-715a572/scripts")
PINS = {"verify_hepta_callers.py":"7a6709691c372504ca11b5d2a74e14ba819fca8f",
        "hepta_typed_callers.py":"e23bb8aa42241b429ef5dbce5a4660853b66eb2f"}
def sha(data):
    return hashlib.sha256(data).hexdigest()
def blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def info(data):
    return {"bytes":len(data),"sha256":sha(data),"git_blob":blob(data)}
with PACKET.open("rb") as stream:
    before=os.fstat(stream.fileno())
    packet_bytes=stream.read()
    after=os.fstat(stream.fileno())
assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
assert sha(packet_bytes)==EXPECTED_PACKET, "packet changed before this replay"
packet=json.loads(packet_bytes)
assert len(packet["files"])==136
checker_before={}
for name,pin in PINS.items():
    data=(TOOLS/name).read_bytes()
    assert blob(data)==pin,(name,blob(data),pin)
    checker_before[name]=info(data)
sys.path.insert(0,str(TOOLS))
proof=importlib.import_module("verify_hepta_callers")
assert Path(proof.__file__).resolve()==(TOOLS/"verify_hepta_callers.py").resolve()
manifest=tomllib.loads(packet["callers"])
rows=manifest["protected_file"]
WORK.mkdir()
source=WORK/"source"
source.mkdir()
inventory={}
for relative,text in packet["files"].items():
    path=Path(relative)
    assert isinstance(text,str) and not path.is_absolute() and ".." not in path.parts
    data=text.encode("utf-8")
    output=source/path
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(data)
    assert output.read_bytes()==data
    inventory[relative]=info(data)
callers=packet["callers"].encode("utf-8")
(source/"CALLERS.toml").write_bytes(callers)
assert (source/"CALLERS.toml").read_bytes()==callers
(WORK/"INPUT_BINDING.json").write_text(json.dumps({
    "packet_path":str(PACKET),"packet":info(packet_bytes),"base_reference":packet["base"],
    "classification":packet["classification"],"CALLERS":info(callers),
    "checker_before":checker_before,"materialized_packet_files":inventory
},indent=2)+"\n")
started=time.monotonic()
covered=[]
uncovered=[]
failures=[]
with (WORK/"rows.jsonl").open("x") as journal:
    for index,row in enumerate(rows):
        relative=row["path"]
        if relative not in packet["files"]:
            uncovered.append({"index_zero_based":index,"index_one_based":index+1,"path":relative})
            continue
        item={"index_zero_based":index,"index_one_based":index+1,"path":relative,
              "source":inventory[relative],"row_sha256":sha(json.dumps(row,sort_keys=True,separators=(",",":")).encode())}
        began=time.monotonic()
        try:
            checked=proof._verify_protected_files(source,{"protected_file":[row]})
            assert checked==[relative]
            item["status"]="satisfied_on_packet"
        except proof.VerificationFailure as error:
            item.update(status="failed_on_packet",error_type=type(error).__name__,condition=str(error),original_row=row)
            failures.append(item)
        except BaseException as error:
            item.update(status="unexpected_diagnostic_error",error_type=type(error).__name__,condition=str(error),traceback=traceback.format_exc(),original_row=row)
            failures.append(item)
        item["elapsed_seconds"]=time.monotonic()-began
        covered.append(item)
        journal.write(json.dumps(item,sort_keys=True)+"\n")
        journal.flush()
        if item["status"]!="satisfied_on_packet" or len(covered)%25==0:
            print(json.dumps({"covered":len(covered),"failures":len(failures),"index_zero_based":index,"path":relative,"status":item["status"],"condition":item.get("condition")}),flush=True)
    os.fsync(journal.fileno())
for relative,pin in inventory.items():
    assert info((source/relative).read_bytes())==pin, "materialized source changed"
assert (source/"CALLERS.toml").read_bytes()==callers
assert PACKET.read_bytes()==packet_bytes, "shared input packet changed during replay"
checker_after={name:info((TOOLS/name).read_bytes()) for name in PINS}
assert checker_after==checker_before
result={
    "schema":"hepta.partial-protected-row-replay.v1",
    "classification":"PARTIAL_CURRENT_V16_PACKET_ONLY_NOT_FULL_SOURCE_OR_QUALIFICATION",
    "base_reference":packet["base"],
    "source_commit_not_claimed":True,
    "input":{"path":str(PACKET),**info(packet_bytes)},
    "callers":info(callers),
    "original_checkers":checker_before,
    "work_directory":str(WORK),
    "materialized_packet_files":len(inventory),
    "protected_total":len(rows),
    "covered_rows":len(covered),
    "covered_unique_paths":len({item["path"] for item in covered}),
    "satisfied_rows":sum(item["status"]=="satisfied_on_packet" for item in covered),
    "failed_rows":len(failures),
    "uncovered_rows":len(uncovered),
    "elapsed_seconds":time.monotonic()-started,
    "covered":covered,
    "uncovered":uncovered,
    "failures":failures,
    "shared_packet_and_materialized_source_unchanged":True,
    "original_checkers_unchanged":True,
    "full_source_index":False,
    "full_boundary_verification":False,
    "native_executed":False,
    "qualification_pass":False,
    "ref_updated":False,
    "ordinary_complete_chains":0,"positive_adoption_chains":0,"ordinary_no_update_rollback_chains":0
}
(WORK/"RESULT.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps({key:result[key] for key in (
    "classification","work_directory","protected_total","covered_rows","covered_unique_paths",
    "satisfied_rows","failed_rows","uncovered_rows","elapsed_seconds","failures"
)},indent=2),flush=True)
raise SystemExit(1 if failures else 0)

