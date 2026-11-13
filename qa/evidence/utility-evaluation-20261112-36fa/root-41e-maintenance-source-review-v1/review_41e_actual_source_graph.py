#!/usr/bin/env python3
"""Independently bind actual maintenance packets to every frozen source leaf."""
import base64,copy,gzip,hashlib,json,pathlib
R=pathlib.Path("/tmp/hepta-36fa-current-workspace-reconstruction-v3")
D=pathlib.Path("/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1")
G=pathlib.Path("/tmp/hepta-36fa-coordinator-final-candidate-graph-v1")
def oid(kind,b):return hashlib.sha1(kind.encode()+b" "+str(len(b)).encode()+b"\0"+b).hexdigest()
def pin(b):return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":oid("blob",b)}
def identity(p):return pin(p.read_bytes())
def subset(p):return {k:p[k] for k in ("bytes","sha256","git_blob")}
def primary(b):
    x=json.loads(b);assert x.get("isError") is False
    return json.loads(x["content"][0]["text"])
def source_tree(files):
    root={}
    for f in files:
        parts=f["path"].split("/");d=root
        for part in parts[:-1]:d=d.setdefault(part,{})
        assert parts[-1] not in d
        d[parts[-1]]=(f["mode"],f["git_blob"])
    trees={}
    def visit(d,prefix):
        entries=[]
        for name,v in d.items():
            mode,sha=("040000",visit(v,prefix+name+"/")) if isinstance(v,dict) else v
            entries.append({"path":name,"mode":mode,"type":"tree" if mode=="040000" else "blob","sha":sha})
        entries.sort(key=lambda e:e["path"].encode()+(b"/" if e["type"]=="tree" else b""))
        raw=b"".join(e["mode"].lstrip("0").encode()+b" "+e["path"].encode()+b"\0"+bytes.fromhex(e["sha"]) for e in entries)
        sha=oid("tree",raw);trees[prefix.rstrip("/") ]={"sha":sha,"entries":entries};return sha
    return visit(root,""),trees
graph_raw=(G/"CANDIDATE_FILE_GRAPH.json").read_bytes()
assert pin(graph_raw)["git_blob"]=="097282896b5881614498faf2231e4c8c0da393c3"
g=json.loads(graph_raw);base={f["path"]:f for f in g["files"]}
invraw=(G/"expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json").read_bytes()
assert pin(invraw)["git_blob"]=="f1e2d72f99093581403a2dcc91b55da22a33f905"
inv=json.loads(invraw);metadata={f["path"]:f for f in inv["files"]}
assert len(base)==len(metadata)==15243
base_tree,base_trees=source_tree(base.values())
assert base_tree=="a489b394666b8141840275128a780605b024cde0"
result=json.loads((D/"RESULT.json").read_bytes());assert identity(D/"RESULT.json")["git_blob"]=="b87aed7647ac34e3db0e381110bf685438aee0ee"
a=json.loads((D/"ARTIFACTS.json").read_bytes());am={x["name"]:x for x in a["files"]};assert len(am)==len(a["files"])==170
readback_raw=(D/"POSTIMAGES_AND_RAW_LOG_READBACK_REVIEW.json").read_bytes();assert pin(readback_raw)["git_blob"]=="9f4fc20c0b8adf15da75382ae916b84b2f9bf8b7"
readback=json.loads(readback_raw);packets={};observed=[]
for spec in readback["packets"]:
    data=bytearray();version=None
    for sr in spec["actual_binary_read_sdks"]:
        original=(D/sr["name"]).read_bytes();assert pin(original)==subset(sr)
        x=primary(original);chunk=base64.b64decode(x["data_base64"],validate=True)
        assert x["offset"]==len(data) and x["next_offset"]==len(data)+len(chunk)
        assert x["path"]=="/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/"+spec["name"]
        assert x["size"]==spec["compressed"]["bytes"] and hashlib.sha256(chunk).hexdigest()==x["chunk_sha256"]
        version=version or x["version"];assert x["version"]==version==spec["version"]
        data.extend(chunk);observed.append({"name":sr["name"],**pin(original)})
    assert x["eof"] and x["next_offset"]==x["size"] and pin(bytes(data))==spec["compressed"]
    record=am[spec["name"]];assert pin(bytes(data))==subset(record)
    raw=gzip.decompress(bytes(data));assert pin(raw)==spec["raw"]
    assert pin(raw)=={"bytes":record["raw_bytes"],"sha256":record["raw_sha256"],"git_blob":record["raw_git_blob"]}
    assert raw==(D/spec["raw_name"]).read_bytes() and bytes(data)==(D/spec["name"]).read_bytes()
    parts=bytearray()
    for part in record["parts"]:
        body=(D/part["name"]).read_bytes();assert pin(body)==subset(part)
        decoded=base64.b64decode(body.strip(),validate=True)
        assert part["decoded_offset"]==len(parts) and len(decoded)==part["decoded_bytes"]
        assert hashlib.sha256(decoded).hexdigest()==part["decoded_sha256"];parts.extend(decoded)
    assert parts==data
    packet=json.loads(raw);assert packet["source_commit_unchanged"]==result["source_commit"]
    assert packet["all_physical_changes_including_untracked_or_ignored_are_recorded"] and packet["qualification"] is False
    packets[packet["stage"]]=packet
assert len(observed)==6 and set(packets)=={"fix.after","fmt.after","final"}
def apply(graph,meta,packet):
    graph=copy.deepcopy(graph);meta=copy.deepcopy(meta);bodies={}
    assert len({c["path"] for c in packet["changes"]})==len(packet["changes"])
    for c in packet["changes"]:
        path=c["path"];assert path in graph and c["before"]==meta[path]
        for field in ("before","after"):
            m=c[field];raw=base64.b64decode(c[field+"_raw_base64"],validate=True)
            assert m["path"]==path and m["kind"]=="file" and m["permissions"]==420 and m["stable"] is True
            assert pin(raw)=={"bytes":m["bytes"],"git_blob":m["working_blob"],"sha256":m["sha256"]}
            assert m["index_mode"]=="100644" and m["index_blob"]==base[path]["git_blob"]
            assert m["matches_index"]==(m["working_blob"]==m["index_blob"])
            if field=="before":
                assert subset(graph[path])==pin(raw)
            else:bodies[path]=raw
        meta[path]=c["after"]
        graph[path]={**graph[path],"bytes":c["after"]["bytes"],"sha256":c["after"]["sha256"],"git_blob":c["after"]["working_blob"]}
    return graph,meta,bodies
fix=packets["fix.after"];fmt=packets["fmt.after"];final=packets["final"]
assert [len(x["changes"]) for x in (fix,fmt,final)]==[12,14,17]
assert fix["base_inventory_sha256"]==final["base_inventory_sha256"]==pin(invraw)["sha256"]
assert fmt["base_inventory_sha256"]==fix["after_inventory_sha256"]==result["stages"][0]["retention"]["inventory"]["sha256"]
assert fmt["after_inventory_sha256"]==final["after_inventory_sha256"]==result["actual_final_source"]["inventory"]["sha256"]
fg,fm,fb=apply(base,metadata,fix);ag,mm,ab=apply(fg,fm,fmt);direct,dm,db=apply(base,metadata,final)
assert ag==direct and mm==dm
for p in db:assert db[p]==(ab[p] if p in ab else fb[p])
fix_tree,_=source_tree(fg.values());actual_tree,trees=source_tree(ag.values())
assert fix_tree==result["stages"][0]["retention"]["postimages"]["all_actual_physical_tree"]=="c29d4e478e7561cadf062e108aa6413623a62ac2"
assert actual_tree==result["actual_final_source"]["postimages"]["all_actual_physical_tree"]=="c026a8d7e93c958b39a36c666debecb3dba4be14"
changed=sorted(p for p in base if base[p]!=ag[p]);assert changed==sorted(db) and len(changed)==17
assert changed==sorted(result["actual_final_source"]["postimages"]["paths"])
assert {p:base[p] for p in base if p not in changed}=={p:ag[p] for p in ag if p not in changed}
assert all(base[p]["mode"]==ag[p]["mode"]=="100644" for p in changed)
assert len(ag)==15243
artifact={"format":"hepta-actual-maintenance-physical-source-graph-v1","source_head_unchanged":result["source_commit"],"source_index_tree_unchanged":base_tree,"actual_physical_tree":actual_tree,"source_is_clean":False,"qualification":False,"files":sorted(ag.values(),key=lambda f:f["path"])}
graph_out=R/"ACTUAL_MAINTENANCE_C026_GRAPH.json";graph_out.write_text(json.dumps(artifact,sort_keys=True,indent=2)+"\n")
updates=[{"path":p,"mode":ag[p]["mode"],"type":"blob","sha":ag[p]["git_blob"],"bytes":ag[p]["bytes"],"sha256":ag[p]["sha256"]} for p in changed]
u=R/"ACTUAL_MAINTENANCE_17_UPDATES.json";u.write_text(json.dumps(updates,sort_keys=True,indent=2)+"\n")
changed_trees={p:v for p,v in trees.items() if base_trees.get(p,{}).get("sha")!=v["sha"]}
t=R/"ACTUAL_MAINTENANCE_C026_TREE_PLAN.json";t.write_text(json.dumps(changed_trees,sort_keys=True,indent=2)+"\n")
report={"format":"hepta-root-actual-41e-source-transition-review-v1","status":"ALL_ACTUAL_PACKET_BYTES_AND_COMPLETE_SOURCE_TREES_MATCH",
"job":"1a1d47cebc8-392-41e","result":identity(D/"RESULT.json"),"packet_readback":pin(readback_raw),"actual_binary_read_sdk_count":6,"original_binary_reads":observed,
"changes":{"fix":12,"fmt":14,"final_union":17},"all_before_after_bodies_verified":True,"consecutive_and_direct_final_transitions_equal":True,
"all_15243_modes_and_source_blobs_composed":True,"unchanged_other_paths":15226,"source_head_and_index_remain_d256_a489":True,
"base_tree":base_tree,"after_fix_physical_tree":fix_tree,"actual_final_physical_tree":actual_tree,
"complete_graph":identity(graph_out),"exact_source_updates":identity(u),"changed_tree_plan":identity(t),"changed_tree_count":len(changed_trees),
"semantic_review":"Separate independent peer examines automatic fix semantics and formatter tokens; this report proves bytes, linkage and complete mode-aware source composition.",
"inventory_scope":"Original actual inventory pins are linked through all three packets. Full inventory serialization recovery is separately owned by ordinary_path; no second Root H source scan is claimed.",
"H_calls":0,"source_writes":0,"test_commands_dispatched":0,"qualification":False,"real_authorized_task_chains":0}
o=R/"ROOT_41E_ACTUAL_SOURCE_GRAPH_REVIEW.json";o.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
print(json.dumps({"report":identity(o),"graph":identity(graph_out),"updates":identity(u),"tree_plan":identity(t),"tree":actual_tree,"changed_trees":len(changed_trees)}))
