#!/usr/bin/env python3
"""Root-only pure data review of actual source and four proposed nonRust writes."""
import base64,copy,gzip,hashlib,json,pathlib
R=pathlib.Path("/tmp/hepta-36fa-current-workspace-reconstruction-v3")
F=pathlib.Path("/tmp/hepta-36fa-a489-maintenance-registration-frozen-v1")
S=pathlib.Path("/tmp/hepta-36fa-a489-maintenance-nonrust-apply-packet-v1")
I=pathlib.Path("/tmp/hepta-36fa-a489-maintenance-actual-inventory-recovery-v1")
def oid(kind,b):return hashlib.sha1(kind.encode()+b" "+str(len(b)).encode()+b"\0"+b).hexdigest()
def pin(b):return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":oid("blob",b)}
def subset(x):return {k:x[k] for k in ("bytes","sha256","git_blob")}
def exact(p,sha):
    b=p.read_bytes();assert pin(b)["git_blob"]==sha,(str(p),pin(b))
    return b
def packet(d,spec):
    chunks=[];offset=0
    for p in spec["parts"]:
        b=(d/p["name"]).read_bytes();assert pin(b)==subset(p)
        q=base64.b64decode(b[:-1],validate=True)
        assert b==base64.b64encode(q)+b"\n" and pin(q)==p["decoded"] and p["decoded_offset"]==offset
        chunks.append(q);offset+=len(q)
    z=b"".join(chunks);assert pin(z)==spec["gzip"]
    raw=gzip.decompress(z);assert pin(raw)==spec["raw"]
    return raw,json.loads(raw)
def tree(files):
    root={}
    for row in files:
        terms=row["path"].split("/");node=root
        assert terms and all(x not in ("",".","..") for x in terms)
        for term in terms[:-1]:node=node.setdefault(term,{})
        assert terms[-1] not in node
        node[terms[-1]]=(row["mode"],row["git_blob"])
    alltrees={}
    def visit(node,prefix):
        entries=[]
        for name,value in node.items():
            if isinstance(value,dict):mode,sha="040000",visit(value,prefix+name+"/")
            else:mode,sha=value
            entries.append({"path":name,"mode":mode,"type":"tree" if mode=="040000" else "blob","sha":sha})
        entries.sort(key=lambda e:e["path"].encode()+(b"/" if e["type"]=="tree" else b""))
        b=b"".join(e["mode"].lstrip("0").encode()+b" "+e["path"].encode()+b"\0"+bytes.fromhex(e["sha"]) for e in entries)
        sha=oid("tree",b);alltrees[prefix.rstrip("/") ]={"sha":sha,"entries":entries};return sha
    return visit(root,""),alltrees
ledger=json.loads((R/"ROOT_FINAL_NONRUST_FULL_GET_LEDGER.json").read_bytes())
assert len(ledger["entries"])==55 and all(x["full_GET"] is True for x in ledger["entries"])
for e in ledger["entries"]:assert pin(pathlib.Path(e["local_path"]).read_bytes())==subset(e),e["path"]
fm=json.loads(exact(F/"MANIFEST.json","4bc60fab145563469f1cbb992feeaf216d58dfb5"))
sm=json.loads(exact(S/"MANIFEST.json","aa4e9a0118bee4521b192b14155ce0aab9a78be7"))
proposal_raw,proposal=packet(F,fm["source_packet"]);assert proposal_raw==(F/"SOURCE_PACKET.json").read_bytes()
seven_raw,seven=packet(F,fm["all_seven_fence_images"]);assert seven_raw==(F/"ALL_SEVEN_FENCE_IMAGES.json").read_bytes()
strict_raw,strict=packet(S,sm);assert strict_raw==(S/"NONRUST_PACKET.json").read_bytes()
graph_raw=exact(R/"ACTUAL_MAINTENANCE_C026_GRAPH.json","a8714cfd209763bff062bb61a2819287b355fe47")
graph=json.loads(graph_raw);base={x["path"]:x for x in graph["files"]}
invraw=exact(I/"final.inventory.exact_recovered.json","4a77b645fd76a980ef746997efbd09fcd8f233ba")
inv=json.loads(invraw);invrows={x["path"]:x for x in inv["files"]}
assert len(base)==len(invrows)==len(graph["files"])==inv["filesystem_entries"]==inv["tracked_entries"]==15243
assert pin(invraw)==strict["base_inventory"]==proposal["base_inventory"]
assert strict["source_identity"]==proposal["source_identity"]==inv["source"]
assert strict["source_identity"]["head"]=="d25675445c39f76db69a7bd8e71a1a72e1cd5b9f"
assert strict["source_identity"]["tree"]=="a489b394666b8141840275128a780605b024cde0"
base_tree,base_trees=tree(graph["files"])
assert base_tree==graph["actual_physical_tree"]==strict["base_physical_tree"]==proposal["base_physical_tree"]=="c026a8d7e93c958b39a36c666debecb3dba4be14"
for p,row in base.items():
    v=invrows[p];assert row["bytes"]==v["bytes"] and row["sha256"]==v["sha256"] and row["git_blob"]==v["working_blob"]
    assert row["mode"]==v["index_mode"] and row["kind"]==v["kind"] and v["stable"] is True
paths=[".github/blob-size-allowlist.txt","CALLERS.toml","qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json","qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py"]
assert [x["path"] for x in strict["changes"]]==[x["path"] for x in proposal["changes"]]==paths
assert set(strict)=={"base_inventory","base_physical_tree","changes","expected_after_leaf_count","expected_after_physical_tree","format","source_identity"}
assert strict["format"]=="hepta-reviewed-nonrust-source-apply-v1"
bound={x["path"]:x for x in fm["fence_bindings"]}
assert len(bound)==len(seven["files"])==7 and fm["fence_bindings"]==proposal["all_seven_fence_bindings"]
proposed={x["path"]:x for x in proposal["changes"]}
after=copy.deepcopy(base);expected=copy.deepcopy(inv);expectedrows={x["path"]:x for x in expected["files"]}
images={};changed=[]
for x in seven["files"]:
    p=x["path"];before=base64.b64decode(x["before_raw_base64"],validate=True);new=base64.b64decode(x["after_raw_base64"],validate=True)
    assert pin(before)==x["before"]==bound[p]["before"]==subset(base[p])
    assert pin(new)==x["after"]==bound[p]["after"]
    assert bound[p]["mode"]==base[p]["mode"]=="100644"
    images[p]=(before,new)
    if before!=new:changed.append(p)
    else:assert bound[p]["operation"]=="unchanged"
assert sorted(changed)==paths
for x in strict["changes"]:
    p=x["path"];source=proposed[p];before,new=images[p]
    assert set(x)=={"path","mode","before","after","after_base64"}
    assert x["mode"]=="100644" and invrows[p]["permissions"]==420 and invrows[p]["kind"]=="file"
    assert source["before"]==invrows[p]
    assert x["before"]=={"bytes":source["before"]["bytes"],"sha256":source["before"]["sha256"],"git_blob":source["before"]["working_blob"]}==pin(before)
    assert x["after"]=={"bytes":source["after"]["bytes"],"sha256":source["after"]["sha256"],"git_blob":source["after"]["working_blob"]}==pin(new)
    assert base64.b64decode(source["before_raw_base64"],validate=True)==before
    assert base64.b64decode(source["after_raw_base64"],validate=True)==base64.b64decode(x["after_base64"],validate=True)==new
    assert (F/"after"/p).read_bytes()==new and (F/"before"/p).read_bytes()==before and before!=new
    after[p].update(x["after"])
    expectedrows[p].update(bytes=len(new),sha256=x["after"]["sha256"],working_blob=x["after"]["git_blob"],matches_index=False)
    assert source["after"]==expectedrows[p]
assert sum(after[p]!=base[p] for p in base)==4 and sum(after[p]==base[p] for p in base)==15239
after_tree,after_trees=tree(after.values())
assert after_tree==strict["expected_after_physical_tree"]==proposal["expected_after_physical_tree"]==fm["expected_after_physical_tree"]=="8ebb37e523ad3932a58cf016af0a9f4e0eeb6638"
assert strict["expected_after_leaf_count"]==proposal["expected_after_leaf_count"]==len(after)==15243
expected["source"]["status"]="\n".join(" M "+p for p in sorted(expectedrows) if expectedrows[p]["matches_index"] is not True).strip()
expectedraw=(json.dumps(expected,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
assert expectedraw==(F/"EXPECTED_AFTER_INVENTORY.json").read_bytes()
assert pin(expectedraw)==proposal["expected_after_inventory"] and pin(expectedraw)["git_blob"]=="e3ce3d7bba028e29efca751c6f43fde124b05ea0"
updates=[{"path":p,"mode":"100644","type":"blob","sha":after[p]["git_blob"]} for p in paths]
changedtrees={p:x for p,x in after_trees.items() if base_trees.get(p,{}).get("sha")!=x["sha"]}
assert set(changedtrees)=={"",".github","qa","qa/b4-no-bypass"}
outgraph={"format":"hepta-projected-final-nonrust-source-graph-v1","status":"PROPOSED_NOT_APPLIED","qualification":False,"source_head_unchanged":strict["source_identity"]["head"],"source_index_tree_unchanged":strict["source_identity"]["tree"],"base_actual_physical_tree":base_tree,"projected_after_physical_tree":after_tree,"files":[after[p] for p in sorted(after)]}
def save(name,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode();(R/name).write_bytes(raw);return pin(raw)
gp=save("PROPOSED_NONRUST_8EBB_GRAPH.json",outgraph)
up=save("PROPOSED_NONRUST_4_UPDATES.json",updates)
tp=save("PROPOSED_NONRUST_8EBB_TREE_PLAN.json",{"base_tree":base_tree,"expected_tree":after_tree,"trees":changedtrees,"updates":updates,"native_application_observed":False})
report={"format":"hepta-root-final-nonrust-proposal-complete-source-review-v1","qualification":False,"H_calls":0,"project_or_QA_commands":0,"source_commit_ref_or_index_mutations":0,"actual_base_tree":base_tree,"projected_tree":after_tree,"native_application_observed":False,"full_git_readback_entries":55,"full_git_readback_ledger":pin((R/"ROOT_FINAL_NONRUST_FULL_GET_LEDGER.json").read_bytes()),"actual_base_graph":pin(graph_raw),"actual_final_inventory":pin(invraw),"proposal_packet":pin(proposal_raw),"strict_packet":pin(strict_raw),"all_seven_images":pin(seven_raw),"source_identity_preserved_exact":True,"seven_bound_paths":sorted(bound),"four_exact_writes":[{"path":p,"before":bound[p]["before"],"after":bound[p]["after"],"mode":bound[p]["mode"]} for p in paths],"unchanged_paths":15239,"leaves":15243,"no_rust_mode_deletion_or_addition":True,"projected_full_inventory":pin(expectedraw),"projected_graph":gp,"updates":up,"tree_plan":tp,"required_target_permission_adaptation":{"path":paths[2],"pure_subset_of_old_safe":False,"before":bound[paths[2]]["before"],"after":bound[paths[2]]["after"],"scope":"Only this exact existing contract JSON target is added; all previous QA wildcard write scope is removed. No native execution permission is implied."},"limits":["This proves complete byte projection and provenance, not actual application or final fmt.","Semantic fence review is independently owned by evaluation_audit.","No qualification, real owner, task, evaluation, consumer or process cold recovery inference."]}
rp=save("ROOT_FINAL_NONRUST_PROPOSAL_REVIEW.json",report)
print(json.dumps({"review":rp,"updates":up,"tree_plan":tp,"derived_graph":gp,"expected_tree":after_tree,"status":"PROPOSED_NOT_APPLIED"}))
