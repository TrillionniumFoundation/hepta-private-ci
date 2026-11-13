import base64,gzip,hashlib,json,pathlib
SRC=pathlib.Path("/tmp/hepta-36fa-new-source-materializer-hold-v1")
RUNTIME=pathlib.Path("/tmp/hepta-36fa-provider-0c59-materialization-runtime-v1")
OUT=pathlib.Path("/tmp/hepta-36fa-provider-0c59-inventory-pin-reconstruction-v1")
OUT.mkdir(mode=0o700,exist_ok=False)
def ident(b):return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
r=json.loads((RUNTIME/"RESULT.json").read_bytes());a=json.loads((RUNTIME/"ARTIFACTS.json").read_bytes());groups=[];payloads=[]
for label,source,stem in [("complete","EXPECTED_CANDIDATE.complete.inventory.json","complete.inventory.json"),("native-five-field","EXPECTED_CANDIDATE.native-five-field.inventory.json","native-five-field.inventory.json")]:
 raw=(SRC/source).read_bytes();gz=gzip.compress(raw,mtime=0);ar=[next(x for x in a if x["name"]==phase+"."+stem+".gz") for phase in ["initial","final"]]
 for entry in ar:
  assert ident(raw)=={"bytes":entry["raw_bytes"],"sha256":entry["raw_sha256"],"git_blob":entry["raw_git_blob"]}
  assert ident(gz)=={k:entry[k] for k in ["bytes","sha256","git_blob"]}
  assert len(entry["parts"])==5
 with (OUT/(label+".inventory.matching-existing-bytes.json")).open("xb") as f:f.write(raw)
 with (OUT/(label+".inventory.matching-existing-bytes.json.gz")).open("xb") as f:f.write(gz)
 rows=[]
 for num,part in enumerate(ar[0]["parts"],1):
  block=gz[part["decoded_offset"]:part["decoded_offset"]+part["decoded_bytes"]]
  b=base64.b64encode(block)+b"\n"
  assert len(block)==part["decoded_bytes"] and ident(block)["sha256"]==part["decoded_sha256"]
  assert ident(b)=={k:part[k] for k in ["bytes","sha256","git_blob"]}
  finalpart=ar[1]["parts"][num-1];assert ident(b)=={k:finalpart[k] for k in ["bytes","sha256","git_blob"]}
  name=label+f".inventory.json.gz.part-{num:03d}.b64"
  with (OUT/name).open("xb") as f:f.write(b)
  row={"name":name,**ident(b),"native_artifact_paths":[part["name"],finalpart["name"]],"decoded_offset":part["decoded_offset"],"decoded_bytes":len(block),"decoded_sha256":ident(block)["sha256"]}
  rows.append(row);payloads.append(row)
 groups.append({"label":label,"preexisting_source_path":str(SRC/source),"preexisting_raw":ident(raw),"matched_actual_gzip":ident(gz),"actual_producer_artifact_rows":ar,"parts":rows,"standalone_raw_or_gzip_Git_upload":False})
review={"format":"hepta-preexisting-inventory-bytes-actual-producer-pin-equality-v1","scope":"Preexisting expected bytes equal the actual producer RESULT and ARTIFACTS raw/gzip/all-part pins. No independent complete H inventory download and no new execution are claimed.","job_id":"1a1d3cdda18-392-1e2","actual_result":ident((RUNTIME/"RESULT.json").read_bytes()),"actual_artifacts":ident((RUNTIME/"ARTIFACTS.json").read_bytes()),"normal_supervisor":ident((RUNTIME/"STATUS_04.original.json").read_bytes()),"groups":groups,"new_H_calls":0,"qualification":False}
b=(json.dumps(review,indent=2,sort_keys=True)+"\n").encode()
with (OUT/"PIN_EQUALITY_REVIEW.json").open("xb") as f:f.write(b)
payloads.append({"name":"PIN_EQUALITY_REVIEW.json",**ident(b)})
manifest={"format":"hepta-bounded-inventory-pin-equality-materials-v1","payloads":payloads,"max_leaf_bytes":max(x["bytes"] for x in payloads),"all_source_bodies_preexisted_execution":True,"actual_producer_pins_matched":True}
b=(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode()
with (OUT/"MANIFEST.json").open("xb") as f:f.write(b)
print(json.dumps({"directory":str(OUT),"files":payloads+[{"name":"MANIFEST.json",**ident(b)}],"result":"Both complete inventories match actual initial/final raw/gzip/all10 unique parts exactly; no new H reads."}))
