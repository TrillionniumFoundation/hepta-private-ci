import base64, hashlib, json, pathlib, zlib
P=pathlib.Path("/tmp/hepta-36fa-new-source-materializer-staging-v1")
def ident(b): return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def load(p): return json.loads(p.read_bytes())
def payload(p):
 r=load(p); assert not r.get("isError") and "tool_call_exception" not in r
 return r.get("structuredContent") or json.loads(r["content"][0]["text"])
rows=[]; binaries=[]
for i in range(1,6):
 prefix=f"STAGE_{i:02d}"; report=P/(prefix+".FULL_READBACK_REVIEW.json"); r=load(report)
 assert r["all_bytes_equal"] and r["single_read_version"]
 b=b"".join(base64.b64decode(payload(P/x["sdk"])["data_base64"],validate=True) for x in r["chunks"])
 assert ident(b)==r["actual"]; binaries.append(b)
 rows.append({"sequence":i,"request_name":r["request_name"],"request":r["request"],"path":r["path"],"version":r["version"],"actual":r["actual"],"metadata":r["metadata"],"write_sdk":r["write_sdk"],"file_info_sdk":r["file_info_sdk"],"full_readback_review":ident(report.read_bytes()),"read_chunk_count":len(r["chunks"]),"complete_readback_equal":True})
expected=[
 ("base",b"".join(binaries[:2]),707857,"4d76a6bd6afc7cfbd0b11f7d2283c3db520ad215c9b21a23f7e7df1ce460c7ae",3095381,"465d36f5dc99c651e59870806e8613cf2b3b5a1cecfabdce2363716c339711da","26a1d658112e58531b710ab9fb50ed93f50d1afe"),
 ("candidate",b"".join(binaries[2:]),1071796,"3b51189d4087167198a13b493991def8a925ec26d57b8981542c8426037ff3f2",5026346,"3f0e398c4a10d4cf5f0e2157c04e924449c674f338c8b5a4f4f51b203a2eb475","432b4670a3c239627338df93c1f5f351260da498")]
joined=[]
for label,gz,gs,gh,rs,rh,rg in expected:
 assert len(gz)==gs and ident(gz)["sha256"]==gh
 d=zlib.decompressobj(31); raw=d.decompress(gz,rs+1)
 assert d.eof and not d.unconsumed_tail and not d.unused_data and len(raw)==rs
 assert ident(raw)=={"bytes":rs,"sha256":rh,"git_blob":rg}
 json.loads(raw)
 joined.append({"label":label,"actual_gzip":ident(gz),"actual_decoded":ident(raw),"exact_expected":True,"scope":"Reassembled from all actual fixed-version binary_read payloads on the cloud; no additional H execution."})
result={"format":"hepta-actual-five-part-staging-result-v1","status":"ALL_FIVE_CREATED_AND_FULLY_READ_BACK","scope":"Approved material preparation only; no bootstrap, main, source, index, ref, formatter or native gate execution.","approval_git_blob":"3c3070ec03da8b658906cd57fa2822412d9fa640","staging_manifest_git_blob":"49e17fcf6f430c90f3048477e3521683903871a3","writes_observed":5,"read_chunks_observed":sum(r["read_chunk_count"] for r in rows),"unknown_write_outcomes":0,"parts":rows,"joined_payloads":joined,"main_process_started":False,"qualification":False}
raw=(json.dumps(result,indent=2,sort_keys=True)+"\n").encode()
with (P/"STAGING_RESULT.json").open("xb") as f:f.write(raw)
print(json.dumps({"result":result,"result_pin":ident(raw),"result_raw":raw.decode(),"part_review_raws":{f"STAGE_{i:02d}.FULL_READBACK_REVIEW.json":(P/f"STAGE_{i:02d}.FULL_READBACK_REVIEW.json").read_text() for i in range(1,6)}}))
