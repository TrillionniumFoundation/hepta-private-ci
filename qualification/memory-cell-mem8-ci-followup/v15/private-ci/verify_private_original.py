from pathlib import Path
import hashlib, json, re, zipfile

ROOT = Path(__file__).resolve().parent
HEAD = "9bd2f589debdba4a93baa363817c3669cb103721"
TREE = "c77785ecb368c44ea699769001a47402c9f50591"
CASE = "circuit_cell::tests::credit_tests::signed_tests::signed_credit_rejects_cross_owner_ledger_episode_before_any_append"
def sha(b):
    return hashlib.sha256(b).hexdigest()
def lines(b):
    s = b.decode("utf-8")
    s = re.sub(r"\x1b\[[0-9;]*m", "", s)
    return [re.sub(r"^\d{4}-\d\d-\d\dT\S+Z ?", "", line) for line in s.splitlines()]
def named(b):
    rows = []
    for line in lines(b):
        m = re.match(r"^\s*(PASS|FAIL)\s+\[\s*[\d.]+s\]\s+(\S+)\s+(\S+)\s*$", line)
        if m:
            rows.append({"status": m[1], "package": m[2], "case": m[3]})
    return rows
def summaries(b):
    rows=[]
    for line in lines(b):
        m=re.search(r"Summary \[\s*[\d.]+s\]\s+(\d+) tests? run:\s+(\d+) passed(?:,\s+(\d+) failed)?(?:,\s+(\d+) skipped)?",line)
        if m:
            rows.append({"executed":int(m[1]),"passed":int(m[2]),"failed":int(m[3] or 0),"reported_skipped":int(m[4] or 0)})
    return rows
raw=(ROOT/"job-130526674042-decoded.log").read_bytes()
assert len(raw)==332370 and sha(raw)=="80dcd87f3950292c75811de11286bf43ba199a422a585b891ac723e23e088191"
main_rows=named(raw)
assert len(main_rows)==34 and len({(r["package"],r["case"]) for r in main_rows})==34
assert all(r["status"]=="PASS" for r in main_rows)
main_summaries=summaries(raw)
assert [r["executed"] for r in main_summaries]==[15,2,3,2,11,1]
assert [r["reported_skipped"] for r in main_summaries]==[5,26,147,148,260,270]
assert sum(r["passed"] for r in main_summaries)==34 and sum(r["failed"] for r in main_summaries)==0
artifact_root=ROOT/"private-artifacts"
expected=json.loads((ROOT/"PRIVATE_ARTIFACTS.json").read_text())["structuredContent"]["artifacts"]
zip_audits=[]
for art in expected:
    zbytes=(artifact_root/f'artifact-{art["id"]}.zip').read_bytes()
    assert len(zbytes)==art["size_in_bytes"] and sha(zbytes)==art["digest"].split(":",1)[1]
    members=[]
    with zipfile.ZipFile(artifact_root/f'artifact-{art["id"]}.zip') as z:
        assert z.testzip() is None
        for info in z.infolist():
            member=Path(info.filename)
            assert not info.is_dir() and not member.is_absolute() and ".." not in member.parts
            b=z.read(info)
            assert b==(artifact_root/str(art["id"])/member).read_bytes()
            members.append({"path":info.filename,"bytes":len(b),"sha256":sha(b)})
    zip_audits.append({"artifact_id":art["id"],"bytes":len(zbytes),"sha256":sha(zbytes),"members":members})
credit_dir=artifact_root/"13856453481"
credit=json.loads((credit_dir/"credit-fixture.json").read_text())
credit_raw=(credit_dir/"credit-fixture.log").read_bytes()
assert credit["source_sha"]==credit["tested_sha"]==HEAD and credit["case"]==CASE
assert credit["before"]==credit["after"] and credit["before"]["commit"]==HEAD
assert credit["before"]["tree"]==TREE and credit["before"]["dirty"] is False
assert credit["command_exit_code"]==credit["exit_code"]==0 and credit["status"]=="passed"
assert credit["command"][-2:]==["--retries","0"] and "--no-tests" in credit["command"]
assert len(credit_raw)==credit["log_bytes"] and sha(credit_raw)==credit["log_sha256"]
assert named(credit_raw)==[{"status":"PASS","package":"codex-hepta-agentd","case":CASE}]
assert summaries(credit_raw)==[{"executed":1,"passed":1,"failed":0,"reported_skipped":270}]
acq_dir=artifact_root/"13856668179"
acq=json.loads((acq_dir/"manifest.json").read_text())
assert acq["source_head"]==HEAD and acq["source_tree"]==TREE
assert acq["qualified"] is True and acq["restored"] is True
prod=json.loads((artifact_root/"EXACT_PRODUCTION_SOURCE.json").read_text())["structuredContent"]
prod_bytes=prod["content"].encode()
assert prod_bytes==(acq_dir/"positive.rs").read_bytes()
assert sha(prod_bytes)==acq["production_sha256"]
assert hashlib.sha1(b"blob "+str(len(prod_bytes)).encode()+b"\0"+prod_bytes).hexdigest()==prod["sha"]
lanes=[]
for lane in acq["lanes"]:
    name=lane["lane"];b=(acq_dir/f"{name}.log").read_bytes();src=(acq_dir/f"{name}.rs").read_bytes()
    assert sha(b)==lane["log_sha256"] and sha(src)==lane["production_sha256"]
    if "patch_sha256" in lane:
        assert sha((acq_dir/f"{name}.patch").read_bytes())==lane["patch_sha256"]
    observed={}
    for row in named(b):
        assert row["package"]=="codex-utils-path"
        assert observed.get(row["case"],row["status"])==row["status"]
        observed[row["case"]]=row["status"]
    assert observed==lane["statuses"] and len(observed)==2
    for observation in lane["observations"].values():
        assert observation in b.decode()
    if name=="positive":
        assert lane["exit_code"]==0 and list(observed.values()).count("PASS")==2
    else:
        assert lane["exit_code"]==1 and list(observed.values()).count("FAIL")==1
    lanes.append({"lane":name,"exit_code":lane["exit_code"],"statuses":observed,"observations":lane["observations"],"log_sha256":sha(b)})
meta=json.loads((ROOT/"OBSERVATION-12-43021840252.json").read_text())
job=json.loads(meta["payload"]["structuredContent"]["content"])["jobs"][0]
assert job["id"]==130526674042 and job["head_sha"]==HEAD and job["conclusion"]=="success"
assert next(s for s in job["steps"] if s["name"]=="Confirm no generated or modified tracked source")["conclusion"]=="success"
result={"schema":"mem9bd2.windows-private-original-offline-audit.v1","status":"passed","source_head":HEAD,"source_tree":TREE,
"run_id":43021840252,"job_id":130526674042,"run_attempt":1,"job_started":job["started_at"],"job_completed":job["completed_at"],
"main_six_selections":{"actual_executions":34,"unique_package_case_ids":34,"passed":34,"failed":0,"summaries":main_summaries,"named_rows":main_rows},
"extra_acquisition_positive_replay":{"actual_executions":2,"passed":2,"case_ids_already_in_main_selection":True},
"acquisition_mutants":{"actual_executions":4,"expected_passes":2,"expected_failures":2,"not_counted_as_source_head_passes":True,"lanes":lanes},
"credit_receipt":credit,"all_artifacts":zip_audits,
"limits":["No JUnit was retained by this original workflow; raw nextest case rows and summaries were checked.",
"Reported skipped counts remain separate; the 34 selected cases are not a whole-package or whole-Windows pass.",
"The enabled core apply-patch hardlink case is in a separate failing Bazel job and is not closed by these private-store cases.",
"Positive replay of two acquisition cases is not counted as two new unique source capabilities."]}
(ROOT/"PRIVATE_ORIGINAL_AUDIT.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps({k:v for k,v in result.items() if k in ["status","source_head","source_tree","run_id","job_id","job_started","job_completed","extra_acquisition_positive_replay","limits"]},indent=2))
print("34 selected original cases PASS; two repeated positive acquisition cases PASS; two mutant lanes each have expected one PASS and one FAIL; 11 ZIP members and all raw identities verified.")

