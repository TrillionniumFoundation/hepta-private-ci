#!/usr/bin/env python3
"""Build inert source52 registration inputs from four actual source51 Git trees."""
from __future__ import annotations
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT=Path("/workspace/scratch/08f5efd48967")
DEST=ROOT/"source52-preparation"
CANDIDATE=ROOT/"network-runtime-wildcard-r26-repair"
BASE_COMMIT="e28b0f385ee882f842911044958b2810f62f6379"
BASE_TREE="763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
RUNTIME="codex-rs/network-proxy/src/runtime.rs"
KEYS=[("root",""),("codex","codex-rs"),("network","codex-rs/network-proxy"),("network_src","codex-rs/network-proxy/src")]

def need(ok,why):
    if not ok:raise ValueError(why)

def pin(raw):
    return {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}

def jb(obj):
    return (json.dumps(obj,ensure_ascii=False,indent=2)+"\n").encode()

def put(rel,raw):
    p=DEST/rel;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():need(p.read_bytes()==raw,"existing frozen path differs: "+rel)
    else:
        with p.open("xb") as f:f.write(raw)
    return pin(raw)

def tree_sha(entries):
    data=b"".join(e["mode"].lstrip("0").encode()+b" "+e["path"].encode()+b"\0"+bytes.fromhex(e["sha"])
        for e in sorted(entries,key=lambda e:(e["path"]+("/" if e["type"]=="tree" else "")).encode()))
    return hashlib.sha1(b"tree "+str(len(data)).encode()+b"\0"+data).hexdigest(),len(data)

def raw_rows(raw):
    text=raw.decode()
    found=re.search(r'"changed_files":\s*\[',text)
    need(found is not None,"changed_files array missing")
    pos=found.end(); decoder=json.JSONDecoder(); rows={}
    while True:
        while text[pos].isspace():pos+=1
        if text[pos]=="]":return rows
        obj,end=decoder.raw_decode(text,pos)
        need(obj["path"] not in rows,"duplicate source row")
        rows[obj["path"]]=text[pos:end].encode()
        pos=end
        while text[pos].isspace():pos+=1
        if text[pos]==",":pos+=1
        else:need(text[pos]=="]","unexpected source array delimiter")

def apply_patch(before,patch,reverse=False):
    lines=patch.decode().splitlines(keepends=True)
    need(lines[:2]==["--- a/"+RUNTIME+"\n","+++ b/"+RUNTIME+"\n"],"patch only path differs")
    source=before.decode().splitlines(keepends=True);out=[];at=0;i=2
    while i<len(lines):
        m=re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",lines[i]);need(m is not None,"bad hunk")
        old_start,new_start=int(m[1]),int(m[3]);old_count,new_count=int(m[2] or "1"),int(m[4] or "1")
        i+=1;old=[];new=[]
        while i<len(lines) and not lines[i].startswith("@@ "):
            line=lines[i];need(line[0] in " +-","unsupported hunk line")
            if line[0] in " -":old.append(line[1:])
            if line[0] in " +":new.append(line[1:])
            i+=1
        need(len(old)==old_count and len(new)==new_count,"hunk count differs")
        start,match,replacement=(new_start,new,old) if reverse else (old_start,old,new)
        start=max(0,start-1)
        need(start>=at and source[start:start+len(match)]==match,"patch context differs")
        out.extend(source[at:start]);out.extend(replacement);at=start+len(match)
    out.extend(source[at:])
    return "".join(out).encode()

def main():
    source51_raw=(ROOT/"source51-preparation/native-candidate-r26-source.json").read_bytes()
    need(pin(source51_raw)["sha256"]=="74b7a35a77019ec90e42ec33dc0e81bbdbaca585541a028d57fffbe77c69a41a","source51 manifest differs")
    source51=json.loads(source51_raw)
    need(source51["source_commit"]==BASE_COMMIT and source51["source_tree"]==BASE_TREE,"base identity differs")
    old_rows=source51["changed_files"]
    need(len(old_rows)==194 and len({r["path"] for r in old_rows})==194,"base count differs")
    need(RUNTIME not in {r["path"] for r in old_rows},"runtime already in base delta")
    need(sum(r["path"].endswith(".rs") for r in old_rows)==180,"base Rust count differs")
    put("input/source51-actual-manifest.json",source51_raw)
    before=(CANDIDATE/"original"/RUNTIME).read_bytes()
    after=(CANDIDATE/"source"/RUNTIME).read_bytes()
    patch=(CANDIDATE/"repair.patch").read_bytes()
    need(pin(before)=={"bytes":75473,"sha256":"3214446d85796e5d1c4a308ba53aab3bf7098fc18cd38cfc6f97a1cbb14d2e4f","git_blob":"1a449a44381fafa4a5d6a5d0e08753f425f339fc"},"before leaf differs")
    need(pin(after)=={"bytes":76209,"sha256":"1d8523c4eda08408eb952a86d692f1e2cfb2975de934de6f1f325597fe9681c8","git_blob":"2c0b88642d1c079ee3991e9e1e418bbb01203694"},"frozen candidate differs")
    need(pin(patch)["sha256"]=="9d28130f28b2e1dd9d28f47a4ab8e5141095ea2f718d5454a0c3fadda895a16e","candidate patch differs")
    need(apply_patch(before,patch)==after and apply_patch(after,patch,True)==before,"independent hunk roundtrip differs")
    put("original/"+RUNTIME,before);put("source/"+RUNTIME,after);put("candidate.patch",patch)

    trees={};queries=[]
    for key,directory in KEYS:
        filename="input/original-trees/"+key+".json"
        raw=(DEST/filename).read_bytes();obj=json.loads(raw)
        need(obj["truncated"] is False,"truncated tree")
        actual,size=tree_sha(obj["tree"]);need(actual==obj["sha"],"original Git tree rehash differs")
        need(len(obj["tree"])==len({e["path"] for e in obj["tree"]}),"duplicate tree child")
        trees[directory]={"key":key,"object":obj}
        queries.append({"directory":directory,"key":key,"file":filename,**pin(raw),
                        "request_url":"https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/trees/"+actual,
                        "recursive":False,"git_tree":actual,"computed_git_tree":actual,"entries":len(obj["tree"]),"tree_object_body_bytes":size})
    need(trees[""]["object"]["sha"]==BASE_TREE,"original root differs")
    links=0
    for directory,item in trees.items():
        if not directory:continue
        parent=directory.rsplit("/",1)[0] if "/" in directory else ""
        name=directory.rsplit("/",1)[-1]
        entry=next(e for e in trees[parent]["object"]["tree"] if e["path"]==name)
        need(entry["type"]=="tree" and entry["sha"]==item["object"]["sha"],"source51 parent-child link differs")
        links+=1
    leaf=next(e for e in trees["codex-rs/network-proxy/src"]["object"]["tree"] if e["path"]=="runtime.rs")
    need(leaf["mode"]=="100644" and leaf["type"]=="blob" and leaf["sha"]==pin(before)["git_blob"] and leaf["size"]==len(before),"actual before leaf differs")

    derived={};details=[]
    for directory in sorted(trees,key=lambda s:(s.count("/"),len(s)),reverse=True):
        item=trees[directory];entries=[];changes=[]
        for old in item["object"]["tree"]:
            entry={k:old[k] for k in ["path","mode","type","sha"]}
            full="/".join(s for s in [directory,entry["path"]] if s)
            if full in derived:entry["sha"]=derived[full]
            elif full==RUNTIME:entry["sha"]=pin(after)["git_blob"]
            if entry["sha"]!=old["sha"]:changes.append({"path":old["path"],"before":old["sha"],"after":entry["sha"]})
            entries.append(entry)
        need(len(changes)==1,"expected exactly one changed direct child per ancestor")
        computed,size=tree_sha(entries);derived[directory]=computed
        body={"schema":"hepta.source52-offline-derived-direct-tree.v1","directory":directory,
              "original_git_tree":item["object"]["sha"],"expected_git_tree":computed,
              "entries":entries,"changes":changes,"all_other_canonical_entries_byte_identical":True,
              "tree_object_body_bytes":size,"git_object_created":False}
        put("derived-trees/"+item["key"]+".json",jb(body))
        details.append({"directory":directory,"before":item["object"]["sha"],"expected_after":computed,"changed_direct_children":changes})
    predicted=derived[""]
    put("input/GIT-TREE-QUERIES.json",jb({"schema":"hepta.source52-original-git-tree-inputs.v1","base_commit":BASE_COMMIT,"base_tree":BASE_TREE,"queries":queries,
        "payload_note":"Exact UTF-8 content string returned by the GitHub connector for fixed nonrecursive GitData URLs; not raw HTTP framing.",
        "read_only_git_requests":True,"git_writes_performed":False}))

    candidate_handoff=(CANDIDATE/"HANDOFF-MANIFEST.json").read_bytes()
    handoff_obj=json.loads(candidate_handoff)
    for row in handoff_obj["files"]:
        data=(CANDIDATE/row["path"]).read_bytes();actual=pin(data)
        need(all(actual[k]==row[k] for k in ["bytes","sha256","git_blob"]),"candidate handoff differs")
    for name in ["HANDOFF-MANIFEST.json","repair-audit.json","FIXTURE-ORACLES.json","source-input-pins.json"]:
        put("input/candidate-"+name,(CANDIDATE/name).read_bytes())
    independent=(ROOT/"network-runtime-wildcard-r26-independent-review/INDEPENDENT-REVIEW.json").read_bytes()
    need(pin(independent)["sha256"]=="3a7a6c600d1c90d52526cbf69a6c314a5ab5e8aec74f9a9b5331c73cd488e8cb","independent review differs")
    put("input/candidate-independent-review.json",independent)
    scope_raw=(ROOT/"source51-final-scope-readonly/EXPECTED-SELECTION.json").read_bytes()
    scope=json.loads(scope_raw)
    need(scope["source_commit"]==BASE_COMMIT and scope["source_tree"]==BASE_TREE,"scope identity differs")
    owners=scope["owners"]
    matches=[o for o in owners if RUNTIME.startswith(o["root"]+"/")]
    longest=max(matches,key=lambda o:len(o["root"]))
    need(longest["name"]=="codex-network-proxy" and len(owners)==26 and scope["ci_selector_count"]==27,"owner/CI scope differs")
    put("input/source51-scope-selection.json",scope_raw)

    new_rows=sorted(old_rows+[{"path":RUNTIME,"mode":"100644",**pin(after)}],key=lambda r:r["path"])
    provisional={
        "schema":"hepta.offline-source52-provisional-manifest.v1",
        "stage":52,"status":"PROVISIONAL_NOT_REGISTERED_NOT_APPLIED_NOT_QUALIFIED",
        "source_commit":None,"source_tree":predicted,"source_parent_commit":BASE_COMMIT,"source_before_tree":BASE_TREE,
        "source_tree_is_offline_expected_identity":True,"native_checkout_or_execution_not_claimed":True,
        "cargo_lock_sha256":source51["cargo_lock_sha256"],"bazel_lock_sha256":source51["bazel_lock_sha256"],
        "changed_files":new_rows,
        "base_source_manifest":{"path":"input/source51-actual-manifest.json",**pin(source51_raw)},
        "source_changes_from_parent":[{"path":RUNTIME,"mode":"100644","before":pin(before),"after":pin(after)}],
        "source51_original_manifest_rows_retained":194,"original_row_json_bytes_retained":True,
        "changed_file_count":195,"rust_file_count":181,"other_file_count":14,
        "owner_count_unchanged":26,"ci_selector_count_unchanged":27,
        "dependency_inputs_changed":[],"lock_changes":[],
        "rust_qualification":"PENDING","native_applied":False,"final_fix_fmt_executed":False,
        "science":"HOLD","authority":"DENY_ALL"}
    provisional_raw=jb(provisional)
    old_raw_rows=raw_rows(source51_raw);new_raw_rows=raw_rows(provisional_raw)
    need(set(new_raw_rows)==set(old_raw_rows)|{RUNTIME},"provisional path set differs")
    need(all(old_raw_rows[p]==new_raw_rows[p] for p in old_raw_rows),"existing row JSON raw bytes changed")
    need(len(new_rows)==195 and sum(r["path"].endswith(".rs") for r in new_rows)==181,"new total/Rust counts differ")
    put("candidate-source-manifest.json",provisional_raw)
    rowproof={"schema":"hepta.source52-original-row-preservation.v1","parent_manifest":pin(source51_raw),"provisional_manifest":pin(provisional_raw),
              "old_rows":194,"new_rows":195,"all_original_values_identical":True,"all_original_object_json_slices_byte_identical":True,
              "slice_definition":"From each changed_files entry's opening { through its matching }; original indentation/newlines inside each object retained.",
              "only_added_row":{"path":RUNTIME,"mode":"100644",**pin(after)},
              "original_row_slice_pins":[{"path":p,**pin(old_raw_rows[p])} for p in old_raw_rows]}
    put("ROW-PRESERVATION.json",jb(rowproof))
    delta={"schema":"hepta.source52-apply-delta.v1","source_before_tree":BASE_TREE,"source_before_commit":BASE_COMMIT,
           "source_tree":predicted,"source_commit":None,
           "patch":{"path":"candidate.patch",**pin(patch)},
           "files":[{"path":RUNTIME,"before":{"mode":"100644",**pin(before)},"after":{"mode":"100644",**pin(after)}}],
           "identity_status":"OFFLINE_EXPECTED_TREE_COMMIT_UNCREATED"}
    put("source52-delta-manifest.json",jb(delta))
    readback={"schema":"hepta.source52-offline-tree-patch-readback.v1","status":"PASS_OFFLINE_PREPARATION_ONLY",
              "base_commit":BASE_COMMIT,"base_tree":BASE_TREE,"expected_tree":predicted,
              "original_direct_trees_rehashed":4,"parent_child_links_verified":links,
              "new_direct_trees_rebuilt":4,"only_changed_leaf":RUNTIME,
              "leaf_mode":"100644","before":pin(before),"after":pin(after),"patch":pin(patch),
              "forward_patch_exact":True,"inverse_patch_exact":True,
              "original194_row_values_and_object_json_bytes_preserved":True,
              "new_changed_path_count":195,"new_rust_count":181,"new_other_count":14,
              "longest_parent_owner":longest["name"],"owner_count":26,"ci_selector_count":27,
              "fresh_source52_metadata_run":False,"future_metadata_binding_required":True,
              "lock_bytes_not_changed_by_candidate":True,"source_commit_created":False,
              "git_writes":False,"native_apply_executed":False,"rust_tests_run":False,
              "derived_direct_trees":details}
    put("TREE-AND-PATCH-READBACK.json",jb(readback))
    plan={"schema":"hepta.source52-single-leaf-preparation-plan.v1",
          "state":"FROZEN_OFFLINE_PLAN_PENDING_ROOT_REGISTRATION_AND_ACTUAL_APPLY",
          "base_commit":BASE_COMMIT,"base_tree":BASE_TREE,
          "expected_tree":predicted,"source_commit":None,"source_commit_created":False,
          "changed_from_source51_paths":[RUNTIME],
          "full_source_count":195,"rust_paths":181,"other_paths":14,
          "source51_original194_entries_unchanged":True,
          "owners":scope["owners"] and [o["name"] for o in scope["owners"]],
          "ci_selectors":scope["ci_selectors"],
          "dependency_inputs_changed":[],"new_lock_command_claimed":False,
          "provisional_source_manifest":{"path":"candidate-source-manifest.json",**pin(provisional_raw)},
          "delta_manifest":{"path":"source52-delta-manifest.json",**pin(jb(delta))},
          "patch":{"path":"candidate.patch",**pin(patch)},
          "future_actual_apply_archive_member_contract":["before/"+RUNTIME,"after/"+RUNTIME,"candidate.patch","delta-manifest.json","source52-manifest.json"],
          "actual_input_archive_created":False,
          "future_binding_requirement":"Root must create the actual GitData commit/tree and bind source_commit in both actual manifest and delta before creating the five-member native apply input. This plan never applies patches.",
          "r26_original_result":"FAIL100 retained; the candidate is not test qualification",
          "r27_executed":False,"final_fix_fmt_executed":False,
          "science":"HOLD","authority":"DENY_ALL"}
    put("PLAN.json",jb(plan))
    put("README.md",("""# Source52 单叶离线登记准备

基线是实际 source51 commit """+BASE_COMMIT+""" / tree """+BASE_TREE+"""。本目录只从四层固定 GitData 非递归树原件离线重算，未创建 Git 对象、commit、分支，也未改动 native 或运行 Rust。

唯一变化为 runtime.rs 的四个域名策略 fixture 初始配置；原断言与生产代码保持。完整 candidate、原文、2255B patch 及独立审查固定在本组。预计新 root tree 为 """+predicted+"""，该值仍是离线预测，source_commit=null。

runtime.rs 已是 source51 仓库的真实叶节点，但不在相对 framework 的194条变更清单内。因此新清单为195条＝181 Rust＋14其他。原194条对象的字段和值，以及每条对象内部 JSON 原字节均验证保持；owner仍26、CI选择项仍27，没有依赖或双锁修改。未来仍需 actual metadata 与原门验证。

主要文件：
- PLAN.json：未执行的登记／后续五成员 apply 输入契约。
- candidate-source-manifest.json：195条 provisional 清单；commit未创建。
- source52-delta-manifest.json、candidate.patch：唯一叶的变更与原补丁。
- input/original-trees/：四份实际 source51 GitData 内容字符串原件。
- derived-trees/：只替换一个叶及其祖先引用的四棵预测树。
- ROW-PRESERVATION.json：原194条 JSON 对象原字节逐项 pins。
- TREE-AND-PATCH-READBACK.json：四树原hash、三层父子链接、单叶以及补丁正逆复算。
- input/candidate-independent-review.json：冻结候选的独立静态审查，未执行Rust。

root须在实际创建source52 commit后重绑actual manifest与delta，并生成最终五成员输入包；本组没有创建可运行native输入归档。原r26 FAIL保持，科学HOLD、DENY_ALL不变。
""").encode())
    files=[]
    for p in sorted(DEST.rglob("*")):
        if p.is_file() and p.name!="HANDOFF-MANIFEST.json":
            files.append({"path":str(p.relative_to(DEST)),**pin(p.read_bytes())})
    handoff={"schema":"hepta.source52-offline-preparation-handoff.v1","status":"FROZEN_PREPARATION_NOT_NATIVE_EXECUTION",
             "base_commit":BASE_COMMIT,"base_tree":BASE_TREE,"expected_tree":predicted,"source_commit":None,
             "file_count":len(files),"total_bytes":sum(x["bytes"] for x in files),"files":files}
    put("HANDOFF-MANIFEST.json",jb(handoff))
    print(json.dumps({"expected_tree":predicted,"source_commit":None,"paths":195,"rust":181,"other":14,
                      "plan":pin(jb(plan)),"manifest":pin(provisional_raw),"delta":pin(jb(delta)),
                      "handoff":pin(jb(handoff)),"files":len(files)},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
