"""Narrow independent closure over saved JSON and source-only synthetic native fixtures."""
import hashlib,json,pathlib,sys
SOURCE=pathlib.Path(sys.argv[1]).resolve();OUT=pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0,str(SOURCE))
import input_contract as contract
import native_analysis_envelope as gate
from test_native155 import fixture,saved
OUT.mkdir(exist_ok=False)
ORIGINAL=pathlib.Path("/workspace/scratch/c385a7439f8e/renderer-native155-independent-review-v1/cases")
def raw(obj):return (json.dumps(obj,indent=2,sort_keys=True)+"\n").encode()
def identity(data):return {"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
def observed(call):
    try:return True,call(),None
    except ValueError as exc:return False,None,str(exc)
rows=[]
for name,expected,message in [
    ("positive_control",True,None),
    ("finalization_beyond_native_whole",False,"native whole cannot cover"),
    ("worker_CPU_beyond_complete_parent_CPU",False,"core disjoint CPU")]:
    original=ORIGINAL/(name+"-INPUT.json");data=original.read_bytes();value=json.loads(data)
    (OUT/(name+"-ORIGINAL-INPUT.json")).write_bytes(data)
    def call():
        contract.envelopes(value["outer"],value["core"],value["result"],value["auth"],value["ids"],value["members"])
        return gate.accounting(value["outer"],value["core"],value["gnu"])
    accepted,result,error=observed(call)
    assert accepted is expected and (message is None or message in error)
    rows.append({"case":name,"scope":"Exact original JSON bytes; same actual envelopes/accounting calls.",
        "original_input":{"path":str(original),**identity(data)},"accepted":accepted,"error":error,"result":result})
for name,bad in (("raw_native_positive_control",False),("raw_native_unrelated_actual_argv",True)):
    directory=OUT/name;directory.mkdir()
    envelope,auth,outer,core,result=fixture(directory)
    if bad:outer["argv"]=["/synthetic/unrelated.py"]
    auth["inputs"]["os_receipt"]=saved(pathlib.Path(auth["inputs"]["os_receipt"]["path"]),outer)
    ids={key:spec["identity"] for key,spec in auth["inputs"].items()}
    accepted,summary,error=observed(lambda:gate.verify_native(raw(envelope),auth,{},outer,core,result,ids))
    assert accepted is (not bad)
    if bad:assert "actual complete OS child command differs" in error
    (directory/"NATIVE-ARGS.json").write_bytes(raw({"envelope":envelope,"auth":auth,"outer":outer,"core":core,"result":result,"ids":ids}))
    rows.append({"case":name,"scope":"Actual raw-native consumer only, using an explicitly attributed owner fixture builder; no unittest methods, full renderer load or plotting run.",
        "accepted":accepted,"error":error,"result":summary,"original_wrong_argv_value_preserved":bad})
assert "matplotlib" not in sys.modules
report={"schema":"renderer-native155-independent-narrow-closure-v1","status":"passed_prospective_contract_closure",
    "exact_original_JSON_cases":3,"raw_native_consumer_cases":2,"cases":rows,
    "original_two_cost_faults_rejected":True,"actual_argv_mismatch_rejected":True,
    "owner_fixture_only_dependency":{"path":str(SOURCE/"test_native155.py"),**identity((SOURCE/"test_native155.py").read_bytes())},
    "scope":"5 fixed metadata function calls in one bounded process; no original owner test suite, production renderer, Matplotlib, model, native job, actual C2 or E access.",
    "actual_analysis_executed":False,"scientific_admission":"HOLD"}
(OUT/"CLOSURE.json").write_bytes(raw(report))
print(json.dumps({"cases":5,"exact_saved_JSON_replays":3,"actual_native_metadata_gate_calls":2,"all_expected_outcomes":True,"Matplotlib_imported":False}))

