import pathlib,json,hashlib,gzip,base64,re,sys
root=pathlib.Path("/tmp/hepta-c0f-source-gates-preservation-36fa")
metadata_path=pathlib.Path("/tmp/hepta-36fa-final-formatted-source/expected-physical-inventory.json")
metadata=metadata_path.read_bytes()
assert len(metadata)==3440077 and hashlib.sha256(metadata).hexdigest()=="c7f8f0a34ef5e5c7ed7bac0ea3cc2b70a06af9e4bc974204a841db1a03eaa49f"
rows=json.loads(metadata);assert len(rows)==14851
identity=json.loads((root/"source-closure/source-before.json").read_text())
assert identity==json.loads((root/"source-closure/source-after.json").read_text())
manifest=json.loads((root/"source-closure/retained-manifest.json").read_text())
descriptors=[x for x in manifest["files"] if x["original_path"] in ("source-before.inventory.json","source-after.inventory.json")]
assert len(descriptors)==2
assert [(x["original_bytes"],x["original_sha256"]) for x in descriptors]==[(5474911,"cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57")]*2
files=[]
for row in sorted(rows,key=lambda x:x["path"]):
 mode=row["mode"];assert mode in ("100644","100755","120000")
 files.append({"path":row["path"],"index_mode":mode,"index_blob":row["blob"],"permissions":{"100644":256,"100755":320,"120000":511}[mode],"kind":"symlink" if mode=="120000" else "file","bytes":row["bytes"],"sha256":row["sha256"],"working_blob":row["blob"],"stable":True,"matches_index":True})
value={"schema":"hepta.utility.desktop-source-gates.v1.inventory","source":identity,"tracked_entries":len(rows),"filesystem_entries":len(rows),"files":files}
raw=(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode()
packed=gzip.compress(raw,compresslevel=9,mtime=0)
part_data=[packed[i:i+262144] for i in range(0,len(packed),262144)]
git=lambda b:hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
checks={"raw_bytes_equal":len(raw)==descriptors[0]["original_bytes"],"raw_sha256_equal":hashlib.sha256(raw).hexdigest()==descriptors[0]["original_sha256"],"part_count_equal":len(part_data)==5,"part_checks":[],"observed_chunk_checks":[]}
for index,part in enumerate(part_data):
 expected=descriptors[0]["parts"][index]
 result={"index":index,"bytes":len(part),"sha256":hashlib.sha256(part).hexdigest(),"git_blob_sha":git(part)}
 result["all_expected_equal"]=all(result[k]==expected[k] for k in ("bytes","sha256","git_blob_sha"))
 checks["part_checks"].append(result)
for p in sorted((root/"observed-chunks").glob("*.json")):
 original=p.read_bytes();d=json.loads(original);b=base64.b64decode(d["data_base64"],validate=True)
 assert hashlib.sha256(b).hexdigest()==d["chunk_sha256"]
 index=int(re.search(r"part(\d+)",p.name).group(1));offset=d["offset"]
 checks["observed_chunk_checks"].append({"path":str(p),"original_native_response_sha256":hashlib.sha256(original).hexdigest(),"part":index,"offset":offset,"bytes":len(b),"chunk_sha256":d["chunk_sha256"],"version":d["version"],"matches_recovered_part":b==part_data[index][offset:offset+len(b)]})
same=checks["raw_bytes_equal"] and checks["raw_sha256_equal"] and checks["part_count_equal"] and all(x["all_expected_equal"] for x in checks["part_checks"]) and all(x["matches_recovered_part"] for x in checks["observed_chunk_checks"])
report={"schema":"hepta.utility.exact-original-inventory-byte-recovery.v1","status":"verified_exact_same_original_bytes" if same else "unverified_candidate_do_not_use","method":"Deterministic reconstruction using the independently hash-verified c0f complete native five-field map, the immutable original driver inventory canonical encoding, original source identities, and observed read-only modes. This is recovery of original bytes, not a new full filesystem observation or a new gate.","original_inventory_sha256":descriptors[0]["original_sha256"],"metadata_input":{"path":str(metadata_path),"bytes":len(metadata),"sha256":hashlib.sha256(metadata).hexdigest(),"git_blob_sha":git(metadata)},"original_driver":{"git_blob_sha":git((root/"original-driver-v2.py").read_bytes()),"sha256":hashlib.sha256((root/"original-driver-v2.py").read_bytes()).hexdigest()},"original_manifest":{"git_blob_sha":git((root/"source-closure/retained-manifest.json").read_bytes())},"checks":checks,"gates_reexecuted":False,"runner_results_modified":False}
if same:
 dest=root/"recovered-original-inventory";dest.mkdir(exist_ok=True)
 (dest/"inventory.json").write_bytes(raw)
 for i,b in enumerate(part_data):
  (dest/f"inventory.json.part{i:04d}").write_bytes(b)
  (dest/f"inventory.json.part{i:04d}.base64.txt").write_bytes(base64.b64encode(b)+b"\n")
 projection=[{"path":x["path"],"mode":x["index_mode"],"blob":x["index_blob"],"bytes":x["bytes"],"sha256":x["sha256"]} for x in files]
 projected=(json.dumps(projection,sort_keys=True,separators=(",",":"))+"\n").encode()
 report["roundtrip_native_map_bytes_equal"]=projected==metadata
 assert report["roundtrip_native_map_bytes_equal"]
 report["recovered_inventory_git_blob_sha"]=git(raw)
 report["reconstructed_gzip_bytes"]=len(packed)
 report["reconstructed_gzip_sha256"]=hashlib.sha256(packed).hexdigest()
 report["recovered_files"]=[{"path":str(p),"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"git_blob_sha":git(p.read_bytes())} for p in sorted(dest.iterdir())]
(root/"INVENTORY_EXACT_RECOVERY.json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
sys.exit(0 if same else 1)
