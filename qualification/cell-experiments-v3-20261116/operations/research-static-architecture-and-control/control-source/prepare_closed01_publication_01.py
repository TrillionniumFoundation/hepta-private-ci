import hashlib,json,pathlib,zipfile
root=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
source=root/"research-closed01-prepared02-publication-01/publication-closed01-prepared02-input-01.zip"
raw=source.read_bytes();assert hashlib.sha256(raw).hexdigest()=="49df3af358682cf616f749ac1a23d2b2616958671915d0f1e79f74ab1653593f"
with zipfile.ZipFile(source) as archive:
 assert archive.testzip() is None
 def member(path):
  found=[n for n in archive.namelist() if n==path or n.endswith("/"+path)]
  assert len(found)==1,(path,found)
  return archive.read(found[0])
 plan_raw=member("NATIVE_FINAL_PLAN_01.json")
 assert hashlib.sha256(plan_raw).hexdigest()=="498b93ec7ea0c6ced1de2850cb3806ab6a5b9b7fb745f19db7b8d702288219bc"
 plan=json.loads(plan_raw);assert plan["base_commit"]=="36ec275d56bb7e40d671443e2ed6e0b154c0a489"
 for name,ident in plan["files"].items():
  data=member(name);assert len(data)==ident["bytes"] and hashlib.sha256(data).hexdigest()==ident["sha256"]
 prefix="qualification/cell-experiments-v3-20261116/operations/research-run01-and-run02-preparation/"
 review={name:member(prefix+name).decode() for name in ("README.md","NEXT_PACKAGE_PENDING.md","COVERAGE.json")}
dest=root/source.name
with dest.open("xb") as stream:stream.write(raw)
assert hashlib.sha256(dest.read_bytes()).hexdigest()=="49df3af358682cf616f749ac1a23d2b2616958671915d0f1e79f74ab1653593f"
out=root/"publication-closed01-root-check-01";out.mkdir(exist_ok=False)
(out/"REVIEW_TEXT.json").write_text(json.dumps(review,sort_keys=True,indent=2)+"\n")
summary={"archive_sha256":hashlib.sha256(raw).hexdigest(),"plan_sha256":hashlib.sha256(plan_raw).hexdigest(),"verified_payload_files":len(plan["files"]),"all_payload_bytes_verified":True,"copy_created":str(dest),"new_model_or_test_calls":0,"git_mutated":False}
(out/"RESULT.json").write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n")
print(json.dumps(summary));print(json.dumps({k:v for k,v in review.items() if k!="COVERAGE.json"}));print(json.dumps(json.loads(review["COVERAGE.json"])))
