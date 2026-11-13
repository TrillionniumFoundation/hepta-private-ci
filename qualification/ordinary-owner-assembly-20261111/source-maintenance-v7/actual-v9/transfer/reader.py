import base64,hashlib,json,re,stat,zlib
from pathlib import Path
WORK=Path("/home/qq/af52-learning-local-decision-20261111/ordinary-future-199-maintenance-v9")
ROOT=WORK/"records"
files=[]
def blob(raw): return hashlib.sha1(b"blob "+str(len(raw)).encode()+bytes([0])+raw).hexdigest()
def take(path,name,expected=None):
    before=path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and not path.is_symlink()
    assert before.st_size<=4*1024*1024
    raw=path.read_bytes();after=path.lstat()
    assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    pin={"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"git_blob":blob(raw)}
    if expected:
        for key,value in expected.items(): assert pin[key]==value,(name,key)
    files.append({"name":name,"path":str(path),"pin":pin,"version":[str(getattr(after,x)) for x in ("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")],"text":raw.decode("utf-8")})
    return raw
result_raw=take(ROOT/"RESULT.json","RESULT.json",{"bytes":11652,"git_blob":"4f1856cd679163e205fad3a11cd554e4722acc38","sha256":"ad32d19a46e22b9a1b31d4214aeb6ce6873d54706dc293557ebd49b263b02052"})
final_raw=take(ROOT/"final-postimages.json","FINAL_POSTIMAGES.json",{"bytes":61933,"git_blob":"2f7d924178f222007d52394ae3d367beb3288eb1","sha256":"85a74ee4ae61b7878ea65721b27aee2319b9d1b29a1105f4aeaa8e255ca1be48"})
fmt_raw=take(ROOT/"formatted-postimages.json","FORMATTED_POSTIMAGES.json",{"bytes":61941,"git_blob":"f9b7741a620042ec3fe4194e76e0b82d73d0d374","sha256":"71cec67e15bebd63682b0e57dd6fec9627b6c365981ccbdcccca037ede5d8386"})
input_raw=take(WORK/"source/qualification/ordinary-owner-assembly-20261111/source-maintenance-v7/FINAL_SOURCE_MANIFEST.json","INPUT_MANIFEST.json",{"bytes":58109,"git_blob":"26aa82d0ac4558c7b669d6ee9ad4f58c98daeb2a","sha256":"efd7d33be47101862e70eba63dec4b77aebaf4ebb24f0194a03bd2947dad1d4b"})
result=json.loads(result_raw);final=json.loads(final_raw);formatted=json.loads(fmt_raw);original=json.loads(input_raw)
assert result["input"]["head"]=="14d377594626fcd8d2664aaf805436a818bec867"
assert result["input"]["tree"]=="62a2a16cb7099eac3ce38fe134d8092bc54add03"
assert result["completion_unknown"] is False and result["errors"]==[]
assert result["status"]=="source-maintenance-failed"
assert len(original["files"])==199
old={f["path"]:f for f in original["files"]}
for label,stage in [("formatted",formatted),("final",final)]:
    assert len(stage["changed"])==1 and len(stage["complete_source_manifest"]["files"])==199
    new={f["path"]:f for f in stage["complete_source_manifest"]["files"]}
    assert set(old)==set(new)
    assert {p for p in old if old[p]!=new[p]}=={f["path"] for f in stage["changed"]}
    for f in stage["changed"]:
        assert old[f["path"]]["post"]==f["pre_blob"] and new[f["path"]]["post"]==f["post_blob"]
        p=Path(f["copy_path"])
        assert p.parent==ROOT/("postimages-"+label) and re.fullmatch(r"[0-9]{3}\.txt",p.name)
        expected={"bytes":f["bytes"],"sha256":f["sha256"],"git_blob":f["post_blob"]}
        take(p,label+"-postimage/"+f["path"]+".txt",expected)
        if label=="final":
            take(WORK/"source"/f["path"],"actual-source/"+f["path"],expected)
    take(ROOT/(label+".patch"),label.upper()+".patch",stage["patch"])
scope_raw=take(ROOT/"final-scope-observation.json","FINAL_SCOPE.json")
scope=json.loads(scope_raw);assert scope["outside_fixed_paths"]==[] and scope["untracked"]==[]
assert set(scope["tracked_dirty"])=={f["path"] for f in final["changed"]}
log_raw=take(ROOT/"fix-eleven-crates.log","fix-eleven-crates.log",{"bytes":97371})
log=log_raw.decode("utf-8")
blocks=[]
for match in re.finditer(r"^error(?:\[[^\]]+\])?:.*$",log,re.M):
    blocks.append("\n".join(log[match.start():].splitlines()[:18]))
excerpt="\n\n".join(blocks)[:6500]
summary={"kind":"actual-v9-evidence-summary","classification":"READ_ONLY_EVIDENCE_TRANSFER_NOT_QUALIFICATION","result":files[0]["pin"],"source_changed":final["changed"],"formatted_changed":formatted["changed"],"maintenance_results":result["maintenance_results"],"completion_unknown":result["completion_unknown"],"errors":result["errors"],"compiler_error_blocks":len(blocks),"compiler_error_excerpt":excerpt,"full_compiler_log_in_payload":True,"files":len(files),"patch":final["patch"]}
summary_text=json.dumps(summary,sort_keys=True)
assert len(summary_text.encode())<14000
print(summary_text,flush=True)
bundle=(json.dumps({"schema_version":1,"files":files},sort_keys=True,ensure_ascii=False)+"\n").encode("utf-8")
encoder=zlib.compressobj(level=9,wbits=-15);compressed=encoder.compress(bundle)+encoder.flush()
assert zlib.decompress(compressed,wbits=-15)==bundle
print(json.dumps({"kind":"actual-v9-original-evidence-bundle","encoding":"raw-deflate-base64","original_bytes":len(bundle),"original_sha256":hashlib.sha256(bundle).hexdigest(),"original_git_blob":blob(bundle),"compressed_bytes":len(compressed),"compressed_sha256":hashlib.sha256(compressed).hexdigest(),"python_roundtrip_exact":True,"data_base64":base64.b64encode(compressed).decode("ascii")},sort_keys=True),flush=True)
