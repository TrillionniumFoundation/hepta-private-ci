import hashlib,json,pathlib,zipfile
root=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
source=root/"research-static-publication-02/publication-static-architecture-control-input-02.zip"
raw=source.read_bytes();assert hashlib.sha256(raw).hexdigest()=="e2493a6d787051dae3bc8b7ab52f9e7b73c507879b709064d57659a5edaee965"
with zipfile.ZipFile(source) as archive:
 assert archive.testzip() is None
 def member(path):
  found=[n for n in archive.namelist() if n==path or n.endswith("/"+path)]
  assert len(found)==1,(path,found)
  return archive.read(found[0])
 plan_raw=member("NATIVE_FINAL_PLAN_01.json")
 assert hashlib.sha256(plan_raw).hexdigest()=="e8710053841ddad7c709a593bf1ae09cc74071c26cc8a6384012e66c2ff90f34"
 plan=json.loads(plan_raw);assert plan["base_commit"]=="296eed0d85795d102d1bb27a84b86f8f4ed26e4b"
 for name,ident in plan["files"].items():
  data=member(name);assert len(data)==ident["bytes"] and hashlib.sha256(data).hexdigest()==ident["sha256"]
 prefix="qualification/cell-experiments-v3-20261116/operations/research-static-architecture-and-control/"
 review={name:member(prefix+name).decode() for name in ("README.md","architecture/ARCHITECTURE_PUBLICATION.diff","COVERAGE.json")}
dest=root/source.name
with dest.open("xb") as stream:stream.write(raw)
assert hashlib.sha256(dest.read_bytes()).hexdigest()=="e2493a6d787051dae3bc8b7ab52f9e7b73c507879b709064d57659a5edaee965"
out=root/"publication-static-root-check-02";out.mkdir(exist_ok=False)
(out/"REVIEW_TEXT.json").write_text(json.dumps(review,sort_keys=True,indent=2)+"\n")
summary={"archive_sha256":hashlib.sha256(raw).hexdigest(),"plan_sha256":hashlib.sha256(plan_raw).hexdigest(),"verified_payload_files":len(plan["files"]),"all_payload_bytes_verified":True,"copy_created":str(dest),"new_model_or_test_calls":0,"git_mutated":False}
(out/"RESULT.json").write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n")
print(json.dumps(summary));print(json.dumps({k:v for k,v in review.items() if k!="COVERAGE.json"}));print(json.dumps(json.loads(review["COVERAGE.json"])))
