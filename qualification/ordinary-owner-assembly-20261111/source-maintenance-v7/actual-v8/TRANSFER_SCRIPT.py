import base64,hashlib,json,re,stat,zlib
from pathlib import Path
WORK=Path("/home/qq/af52-learning-local-decision-20261111/ordinary-future-197-maintenance-v8")
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
result_raw=take(ROOT/"RESULT.json","RESULT.json",{"bytes":11742,"git_blob":"35a0088c0d1a168925d627d6fd78bf6537e9e930","sha256":"18b32d2a6bba91728f2c0d6438a2cee65749e08612909e53cdb74ff52c815dc6"})
final_raw=take(ROOT/"final-postimages.json","FINAL_POSTIMAGES.json",{"bytes":62284,"git_blob":"dbc94e43c8b285189ba36cd7757ffe36611a2347","sha256":"1eb240ae2fc8504f166ef3bb16e09b9167837ea866b831266838764e3de61197"})
fmt_raw=take(ROOT/"formatted-postimages.json","FORMATTED_POSTIMAGES.json",{"bytes":60780,"git_blob":"3a5504ddfa5b32081d12d94047330e1f8afba438","sha256":"af214d8bc8763243bdcaffaa6d453bdab1861ee92f6e171b8f69f2af99837158"})
input_raw=take(WORK/"source/qualification/ordinary-owner-assembly-20261111/source-maintenance-v7/FINAL_SOURCE_MANIFEST.json","INPUT_MANIFEST.json",{"bytes":57520,"git_blob":"2568ae7251360b252bebd965b1aa5a7ca5014635","sha256":"d7b4c9a994e1d5d0625208872e6f88b40c408d4f1b49e3dabbb966deac8c27b5"})
result=json.loads(result_raw);final=json.loads(final_raw);formatted=json.loads(fmt_raw);original=json.loads(input_raw)
assert result["input"]["head"]=="230d771303b3775ea88126ff933a1d2e3452c948"
assert result["input"]["tree"]=="880feb6979d16f878adc6091f700ef67ff4e57a0"
assert result["completion_unknown"] is False and result["errors"]==[]
assert result["status"]=="source-maintenance-failed"
assert formatted["changed"]==[] and formatted["complete_source_manifest"]==original
assert len(final["changed"])==3 and len(final["complete_source_manifest"]["files"])==197
old={f["path"]:f for f in original["files"]}
new={f["path"]:f for f in final["complete_source_manifest"]["files"]}
assert set(old)==set(new)
assert {p for p in old if old[p]!=new[p]}=={f["path"] for f in final["changed"]}
for f in final["changed"]:
    assert old[f["path"]]["post"]==f["pre_blob"] and new[f["path"]]["post"]==f["post_blob"]
    p=Path(f["copy_path"])
    assert p.parent==ROOT/"postimages-final" and re.fullmatch(r"[0-9]{3}\.txt",p.name)
    take(p,"postimage/"+f["path"]+".txt",{"bytes":f["bytes"],"sha256":f["sha256"],"git_blob":f["post_blob"]})
patch=take(ROOT/"final.patch","FINAL.patch",final["patch"])
scope_raw=take(ROOT/"final-scope-observation.json","FINAL_SCOPE.json")
scope=json.loads(scope_raw);assert scope["outside_fixed_paths"]==[] and scope["untracked"]==[]
assert set(scope["tracked_dirty"])=={f["path"] for f in final["changed"]}
log_raw=take(ROOT/"fix-eleven-crates.log","fix-eleven-crates.log",{"bytes":57049})
log=log_raw.decode("utf-8")
blocks=[]
for match in re.finditer(r"^error(?:\[[^\]]+\])?:.*$",log,re.M):
    blocks.append("\n".join(log[match.start():].splitlines()[:18]))
excerpt="\n\n".join(blocks)[:6500]
summary={"kind":"actual-v8-evidence-summary","classification":"READ_ONLY_EVIDENCE_TRANSFER_NOT_QUALIFICATION","result":files[0]["pin"],"source_changed":final["changed"],"maintenance_results":result["maintenance_results"],"completion_unknown":result["completion_unknown"],"errors":result["errors"],"compiler_error_excerpt":excerpt,"full_compiler_log_in_payload":True,"files":len(files),"patch":final["patch"]}
summary_text=json.dumps(summary,sort_keys=True)
assert len(summary_text.encode())<14000
print(summary_text,flush=True)
bundle=(json.dumps({"schema_version":1,"files":files},sort_keys=True,ensure_ascii=False)+"\n").encode("utf-8")
encoder=zlib.compressobj(level=9,wbits=-15);compressed=encoder.compress(bundle)+encoder.flush()
assert zlib.decompress(compressed,wbits=-15)==bundle
print(json.dumps({"kind":"actual-v8-original-evidence-bundle","encoding":"raw-deflate-base64","original_bytes":len(bundle),"original_sha256":hashlib.sha256(bundle).hexdigest(),"original_git_blob":blob(bundle),"compressed_bytes":len(compressed),"compressed_sha256":hashlib.sha256(compressed).hexdigest(),"python_roundtrip_exact":True,"data_base64":base64.b64encode(compressed).decode("ascii")},sort_keys=True),flush=True)
