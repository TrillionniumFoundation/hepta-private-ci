import base64, hashlib, json, pathlib, sys
ROOT = pathlib.Path("/tmp/hepta-36fa-new-source-materializer-staging-v1")
CONTROL = pathlib.Path("/tmp/hepta-36fa-new-source-materializer-hold-v1")
def sha(b): return hashlib.sha256(b).hexdigest()
def identity(b): return {"bytes":len(b),"sha256":sha(b),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def payload(p):
    raw=p.read_bytes(); sdk=json.loads(raw)
    assert not sdk.get("isError") and "tool_call_exception" not in sdk
    obj=sdk.get("structuredContent")
    if obj is None:
        text=[v["text"] for v in sdk["content"] if v.get("type")=="text"]
        assert len(text)==1
        obj=json.loads(text[0])
    return obj, identity(raw)
idx=int(sys.argv[1]); assert 1<=idx<=5
ap=json.loads((ROOT/"ROOT_APPROVAL.original.json").read_bytes())
entry=ap["requests"][idx-1]; reqraw=(CONTROL/entry["name"]).read_bytes()
assert identity(reqraw)==entry["request"]
req=json.loads(reqraw); expected=base64.b64decode(req["data_base64"],validate=True)
assert identity(expected)==entry["decoded"]
prefix=f"STAGE_{idx:02d}"
w,wpin=payload(ROOT/(prefix+".WRITE.original.json"))
assert (w["size"],w["written"],w["sha256"],w["mode"])==(len(expected),len(expected),sha(expected),384)
fi,fpin=payload(ROOT/(prefix+".FILE_INFO.original.json"))
assert (fi["path"],fi["size"],fi["sha256"],fi["mode"],fi["metadata"]["uid"],fi["metadata"]["gid"],fi["metadata"]["link_count"])==(entry["path"],len(expected),sha(expected),384,1000,1000,1)
version=w["version"]; assert fi["version"]==version
chunks=[]; rows=[]; offset=0
while offset<len(expected):
    path=ROOT/(prefix+f".READ_{offset:06d}.original.json")
    part,ppin=payload(path)
    assert (part["path"],part["version"],part["size"],part["offset"])==(entry["path"],version,len(expected),offset)
    b=base64.b64decode(part["data_base64"],validate=True)
    assert len(b)==min(65536,len(expected)-offset)
    assert part["next_offset"]==offset+len(b) and sha(b)==part["chunk_sha256"]
    assert part["eof"]==(offset+len(b)==len(expected))
    rows.append({"sdk":path.name,"sdk_identity":ppin,"offset":offset,"next_offset":part["next_offset"],"chunk_sha256":sha(b),"eof":part["eof"]})
    chunks.append(b); offset+=len(b)
actual=b"".join(chunks); assert actual==expected
report={"format":"hepta-actual-fixed-part-full-readback-v1","sequence":idx,"request_name":entry["name"],"request":entry["request"],"path":entry["path"],"version":version,"actual":identity(actual),"write_sdk":wpin,"file_info_sdk":fpin,"metadata":fi["metadata"],"chunks":rows,"all_bytes_equal":True,"single_read_version":True,"scope":"Actual complete byte readback of the approved staged part only; no driver execution."}
raw=(json.dumps(report,indent=2,sort_keys=True)+"\n").encode()
out=ROOT/(prefix+".FULL_READBACK_REVIEW.json")
with out.open("xb") as f: f.write(raw)
print(json.dumps({"report":str(out),"report_identity":identity(raw),"actual":identity(actual),"version":version,"all_bytes_equal":True}))
