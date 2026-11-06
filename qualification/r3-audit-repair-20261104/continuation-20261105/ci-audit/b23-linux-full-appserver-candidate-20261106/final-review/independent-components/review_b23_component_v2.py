from pathlib import Path
import json,hashlib,shutil,subprocess
BASE=Path("/tmp/hepta-runtime-recovery-20261106/b23-recovery")
OWN=Path("/tmp/hepta-runtime-recovery-20261106/format-review-recovery/b23-component-review-v2")
OWN.mkdir()
def ident(b):return {"bytes":len(b),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest(),"sha256":hashlib.sha256(b).hexdigest()}
records={}
for version in ("v1","v2"):
 root=BASE/("component-review-"+version);m=json.loads((root/"manifest.json").read_text())
 rows=[]
 for x in m["files"]:
  data=(root/x["path"]).read_bytes();i=ident(data)
  assert all(x[k]==i[k] for k in i),(version,x["path"],i)
  rows.append({"path":x["path"],**i})
 records[version]={"members":len(rows),"bytes":sum(x["bytes"] for x in rows),"files":rows}
a=BASE/"component-review-v1";b=BASE/"component-review-v2"
code=[]
for rel in ("source_identity.py","draft/.github/workflows/hepta-b23-linux-app-server-original-gate.yml.template"):
 old=(a/rel).read_bytes();new=(b/rel).read_bytes()
 needle=b'pr["base"]["ref"] == "main"';repl=b'pr["base"]["ref"] == "fix/r3-original-product-contracts-20261104"'
 assert old.count(needle)==1 and new.count(repl)==1 and old.replace(needle,repl)==new
 code.append({"path":rel,"single_substitution":True,"inverse_equal":new.replace(repl,needle)==old,"before":ident(old),"after":ident(new)})
api=json.loads((b/"source-api/base-ref-pr4902.original-tool-return.json").read_text())
actual=json.loads(api["structuredContent"]["content"])
assert actual["number"]==4902 and actual["base"]["ref"]=="fix/r3-original-product-contracts-20261104" and actual["base"]["sha"]=="67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
clone=OWN/"restored";shutil.copytree(b,clone)
p=subprocess.run(["python3",str(clone/"verify_workflow.py")],cwd="/",capture_output=True,timeout=45)
(OWN/"verifier.stdout.json").write_bytes(p.stdout);(OWN/"verifier.stderr.txt").write_bytes(p.stderr)
assert p.returncode==0,(p.returncode,p.stderr)
expected=(b/"verification-draft/static-verification.json").read_bytes()
assert p.stdout==expected and (clone/"verification-draft/static-verification.json").read_bytes()==expected
proof={"schema":"b23-component-v2-independent-review","scope":"NON_COLLECTOR_COMPONENT_ONLY_NOT_FINAL_WORKFLOW_ACCEPTANCE","identities":records,"code_delta":code,"actual_base_ref":{"source_blob":"5c213344391c4d17203af88e94f25a28c7b6e0d3","number":actual["number"],"ref":actual["base"]["ref"],"sha":actual["base"]["sha"]},"isolated_static_replay":{"exit":p.returncode,"stdout_bytes_equal_frozen":True,"stderr_bytes":len(p.stderr),"output_identity":ident(p.stdout)},"real_source_guard":"NOT_RUN","Bazel_or_product_native":"NOT_RUN","collector":"PENDING_FINAL_EXACT_ACCEPTED_BYTES","review_blockers":[],"packaging_note":"Author verifier currently reads source via original receipt absolute path; all source bodies independently manifest-checked here. Requested relative ROOT/source lookup before portable publication."}
with (OWN/"REVIEW.json").open("x") as f:f.write(json.dumps(proof,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({"members_v1":records["v1"]["members"],"members_v2":records["v2"]["members"],"v2_bytes":records["v2"]["bytes"],"base_ref":proof["actual_base_ref"],"replay":proof["isolated_static_replay"],"review":ident((OWN/"REVIEW.json").read_bytes()),"scope":proof["scope"]},ensure_ascii=False,indent=2))

