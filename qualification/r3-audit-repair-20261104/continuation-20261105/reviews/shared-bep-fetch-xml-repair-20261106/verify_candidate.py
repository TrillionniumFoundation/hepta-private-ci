#!/usr/bin/env python3
"""Static, complete-tree and bounded offline verification; never run Bazel/cargo/native."""
import ast
import copy
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import yaml
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent

def identity(data):
    return {"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()}

def git_object(kind, data):
    return hashlib.sha1(kind.encode()+b" "+str(len(data)).encode()+b"\0"+data).hexdigest()

def full_tree(leaves):
    nodes={"":{}}
    for path,entry in leaves.items():
        parent,_,name=path.rpartition("/")
        nodes.setdefault(parent,{})[name]=entry
        while parent:
            parent,_,_=parent.rpartition("/")
            nodes.setdefault(parent,{})
    hashes={}
    for path in sorted(nodes,key=lambda x:(-x.count("/"),x=="",x)):
        children=dict(nodes[path])
        for child,sha in hashes.items():
            parent,_,name=child.rpartition("/")
            if parent==path:
                children[name]={"mode":"40000","type":"tree","sha":sha}
        body=b""
        for name,e in sorted(children.items(),key=lambda item:item[0].encode()+
                             (b"/" if item[1]["type"]=="tree" else b"")):
            mode="40000" if e["type"]=="tree" else e["mode"]
            body+=mode.encode()+b" "+name.encode()+b"\0"+bytes.fromhex(e["sha"])
        hashes[path]=git_object("tree",body)
    return hashes[""],hashes

def fetch_content(result):
    assert not result.get("isError")
    data=result.get("structuredContent")
    if data is None:
        data=json.loads(next(x["text"] for x in result["content"] if x["type"]=="text"))
    assert isinstance(data["content"],str)
    return data["content"],data.get("url") or data.get("display_url")

identities=json.loads((ROOT/"candidate-identities.json").read_bytes())
old=(ROOT/"preimage/collect_attempts.py").read_bytes()
new=(ROOT/"collect_attempts.py").read_bytes()
assert identity(old)==identities["preimage_collector"]
assert identity(new)==identities["postimage_collector"]
assert identity(old)["git_blob"]=="00dc37697adde6154a347963ab19e8a6edebac07"
old_ast,new_ast=ast.parse(old),ast.parse(new)
def preserved(tree):
    return [ast.dump(node,include_attributes=False) for node in tree.body
            if not(isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {"collect","reconcile"})
            and not(isinstance(node,ast.Assign) and any(isinstance(x,ast.Name) and x.id=="SCHEMA" for x in node.targets))]
assert preserved(old_ast)==preserved(new_ast)
old_defs={n.name:ast.get_source_segment(old.decode(),n) for n in old_ast.body if isinstance(n,(ast.ClassDef,ast.FunctionDef))}
new_defs={n.name:ast.get_source_segment(new.decode(),n) for n in new_ast.body if isinstance(n,(ast.ClassDef,ast.FunctionDef))}
assert old_defs.keys()==new_defs.keys()
unchanged=[name for name in old_defs if name not in {"reconcile","collect"}]
assert all(old_defs[name]==new_defs[name] for name in unchanged)
assert (ROOT/"collector.patch").read_text()=="".join(difflib.unified_diff(
    old.decode().splitlines(True),new.decode().splitlines(True),
    fromfile="a/collect_attempts.py",tofile="b/collect_attempts.py"))

with tempfile.TemporaryDirectory(prefix="fetch-xml-static-rebuild-") as temp:
    temp=Path(temp);shutil.copytree(ROOT/"preimage",temp/"preimage")
    shutil.copyfile(ROOT/"build_candidate.py",temp/"build_candidate.py")
    built=subprocess.run([sys.executable,str(temp/"build_candidate.py")],capture_output=True,check=True)
    assert not built.stderr
    for relative in ["collect_attempts.py","collector.patch","candidate-identities.json","b21.patch","b23.patch"]:
        assert (temp/relative).read_bytes()==(ROOT/relative).read_bytes(),relative
    for label,record in identities["workflows"].items():
        relative=Path("candidate")/label/record["repository_path"]
        assert (temp/relative).read_bytes()==(ROOT/relative).read_bytes()

authority=json.loads((ROOT/"authority/main67-full-tree.json").read_bytes())
assert authority["truncated"] is False and authority["sha"]=="3982ba56dc5a3f1da0c1de7ea57992f88125c359"
entries={x["path"]:x for x in authority["tree"] if x["type"]!="tree"}
assert len(entries)==10582 and len(entries)==len([x for x in authority["tree"] if x["type"]!="tree"])
base_root,base_nodes=full_tree(entries)
assert base_root==authority["sha"]
for entry in authority["tree"]:
    if entry["type"]=="tree":
        assert base_nodes[entry["path"]]==entry["sha"]

workflow_results={}
for label,record in identities["workflows"].items():
    path=record["repository_path"]
    pre=(ROOT/"preimage"/(label+"-workflow.yml")).read_bytes()
    post=(ROOT/"candidate"/label/path).read_bytes()
    assert identity(pre)==record["preimage"] and identity(post)==record["postimage"]
    assert path not in entries
    pre_leaves=copy.deepcopy(entries);pre_leaves[path]={"path":path,"mode":"100644","type":"blob","sha":identity(pre)["git_blob"]}
    post_leaves=copy.deepcopy(entries);post_leaves[path]={"path":path,"mode":"100644","type":"blob","sha":identity(post)["git_blob"]}
    parent_root,_=full_tree(pre_leaves)
    candidate_root,candidate_nodes=full_tree(post_leaves)
    assert parent_root==record["parent_tree"]
    actual_parent=json.loads((ROOT/"authority"/(label+"-parent-commit.actual.json")).read_bytes())
    raw_parent,_=fetch_content(json.loads((ROOT/"authority"/(label+"-parent-commit.full-GET.original.json")).read_bytes()))
    assert actual_parent==json.loads(raw_parent)
    assert actual_parent["sha"]==record["parent_commit"] and actual_parent["tree"]["sha"]==parent_root
    actual_merge=json.loads((ROOT/"authority"/(label+"-merge-commit.actual.json")).read_bytes())
    raw_merge,_=fetch_content(json.loads((ROOT/"authority"/(label+"-merge-commit.full-GET.original.json")).read_bytes()))
    assert actual_merge==json.loads(raw_merge)
    assert actual_merge["tree"]["sha"]==parent_root
    assert [x["sha"] for x in actual_merge["parents"]]==["67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed",record["parent_commit"]]
    assert [p for p in pre_leaves if pre_leaves[p]!=post_leaves[p]]==[path]
    assert all(post_leaves[p]==entry for p,entry in entries.items())
    before,after=yaml.safe_load(pre),yaml.safe_load(post)
    before_steps,after_steps=before["jobs"]["test"]["steps"],after["jobs"]["test"]["steps"]
    assert len(before_steps)==len(after_steps)
    command_changes=0; collector_changes=0;guard_changes=0
    syntax_count=0
    for i,(left,right) in enumerate(zip(before_steps,after_steps)):
        if left==right:
            pass
        elif left.get("name")=="bazel test //..." or "--nocache_test_results" in left.get("run",""):
            assert set(left)==set(right) and all(left[k]==right[k] for k in left if k!="run")
            flag="  '--remote_download_regex="+identities["remote_download_regex"]+"'\n"
            assert right["run"].count(flag)==1
            assert right["run"].replace(flag,"")==left["run"]
            command_changes+=1
        elif old.decode() in left.get("run",""):
            assert set(left)==set(right) and all(left[k]==right[k] for k in left if k!="run")
            assert right["run"].count(new.decode())==1 and left["run"].count(old.decode())==1
            assert right["run"].replace(new.decode(),old.decode())==left["run"]
            collector_changes+=1
        elif label=="b21" and i==0:
            a=copy.deepcopy(right);assert a["with"]["fetch-depth"]==4;a["with"]["fetch-depth"]=3
            assert a==left;guard_changes+=1
        elif label=="b21" and left.get("name")=="Bind original source, full archive and actual Intel platform":
            assert set(left)==set(right) and all(left[k]==right[k] for k in left if k!="run")
            assert "ebd31e2b3e38ff72cedaa7b57bee60c1c102da27" in right["run"]
            assert 'test "$(git show -s --format=%P HEAD~2)" = 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed' in right["run"]
            assert 'test "$(git rev-parse \'HEAD~3^{tree}\')" = 3982ba56dc5a3f1da0c1de7ea57992f88125c359' in right["run"]
            guard_changes+=1
        else:
            raise AssertionError(("unexpected workflow change",label,i))
        if "run" in right and right.get("shell")=="bash":
            checked=subprocess.run(["bash","-n"],input=right["run"].encode(),capture_output=True)
            assert checked.returncode==0,(label,i,checked.stderr.decode())
            syntax_count+=1
    assert command_changes==collector_changes==1
    assert guard_changes==(2 if label=="b21" else 0)
    assert before["on"]==after["on"] and before["permissions"]==after["permissions"]
    assert before["concurrency"]==after["concurrency"]
    for key in before["jobs"]["test"]:
        if key!="steps":assert before["jobs"]["test"][key]==after["jobs"]["test"][key]
    assert after["jobs"]["test"]["timeout-minutes"]==120
    assert "workflow_dispatch" not in after["on"]
    workflow_results[label]={
        "workflow":path,"actual_parent_commit":actual_parent["sha"],"actual_parent_tree":parent_root,
        "actual_parent_merge":actual_merge["sha"],"actual_parent_merge_tree":actual_merge["tree"]["sha"],
        "preimage":identity(pre),"postimage":identity(post),"computed_complete_tree":candidate_root,
        "total_leaves":len(post_leaves),"original_main67_leaves_unchanged":len(entries),
        "only_parent_leaf_changed":path,"merkle_nodes":len(candidate_nodes),
        "all_other_workflow_bytes_preserved_except_exact_parent_guard_update":True,
        "only_bazel_argv_addition":"--remote_download_regex="+identities["remote_download_regex"],
        "bash_n_scripts":syntax_count,
    }

primary=[]
for p in sorted((ROOT/"primary").glob("*.java")):
    result_path=p.with_name(p.name+".GET.original.json")
    assert result_path.is_file(),p
    content,url=fetch_content(json.loads(result_path.read_bytes()))
    assert content.encode()==p.read_bytes()
    assert url and "/blob/9.3.0/" in url
    primary.append({"path":str(p.relative_to(ROOT)),"url":url,**identity(p.read_bytes())})
text=lambda name:(ROOT/"primary"/name).read_text()
assert 'name = "remote_download_regex"' in text("CommonRemoteOptions.java")
assert "OptionEffectTag.AFFECTS_OUTPUTS" in text("CommonRemoteOptions.java")
assert "irrespective of --remote_download_outputs" in text("CommonRemoteOptions.java")
assert "patternsToDownloadBuilder.add(patternOption.matcher())" in text("RemoteModule.java")
assert "pattern.test(execPath.toString())" in text("RemoteOutputChecker.java")
assert "|| matchesPattern(execPath)" in text("RemoteOutputChecker.java")
assert "matches the entire input string" in text("RegexPatternOption.java")
assert "BuildEventIdUtil.fetchId(url, downloader)" in text("FetchEvent.java")
assert "setUrl(url).setDownloader(downloader)" in text("BuildEventIdUtil.java")
assert "/* outputs= */ ImmutableSet.of(action.getTestXml())" in text("StandaloneTestStrategy.java")
assert "remoteOutputChecker.shouldDownloadOutput(execPath, treeRootExecPath)" in text("RemoteExecutionService.java")
assert "waitForBulkTransfer(downloads)" in text("RemoteExecutionService.java")
assert "common:ci --remote_download_minimal" in (ROOT/"source/.bazelrc").read_text()
assert "remote_download_regex" not in (ROOT/"source/.bazelrc").read_text()
regression_stdout=(ROOT/"regressions-01.stdout.json").read_bytes()
regression=json.loads(regression_stdout)
assert regression["candidate_collector"]==identity(new)
assert regression["all_checks_passed"] and len(regression["new_controls"])==9
assert all(not x["complete_after"] for x in regression["real_bep"])
assert not (ROOT/"regressions-01.stderr.txt").read_bytes()
if "--replay" in sys.argv:
    replay=subprocess.run([sys.executable,str(ROOT/"verify_regressions.py")],capture_output=True,check=True)
    assert replay.stdout==regression_stdout and not replay.stderr
postimages=json.loads((ROOT/"candidate-postimages.actual.json").read_bytes())["objects"]
assert len(postimages)==3 and len({x["git_blob"] for x in postimages})==3
expected={identity(new)["git_blob"]:new}
for label,record in identities["workflows"].items():
    data=(ROOT/"candidate"/label/record["repository_path"]).read_bytes()
    expected[identity(data)["git_blob"]]=data
for row in postimages:
    assert row["full_GET_byte_equal"] is True
    data,_=fetch_content(json.loads((ROOT/"source-registration"/(row["git_blob"]+".full-GET.original.json")).read_bytes()))
    assert data.encode()==expected[row["git_blob"]]
    assert identity(data.encode())["git_blob"]==row["git_blob"]
result={
    "schema":"shared-fetch-xml-static-proof-v1","status":"STATIC_VERIFIED_NATIVE_PENDING",
    "collector":identity(new),"actual_postimage_full_GET_count":3,"unchanged_function_and_class_bodies":unchanged,
    "only_collector_function_changes":["reconcile","collect"],"schema_name_changed":True,
    "complete_source_regeneration_byte_equal":True,"main67_tree":base_root,"original_leaves":len(entries),
    "workflows":workflow_results,"fixed_bazel_9_3_primary_full_GET":primary,
    "original_36_and_9_new_and_11_original_privacy_checks_passed":True,
    "regression_stdout":identity(regression_stdout),
    "historical_terminal_evidence_remains_incomplete":{"b21_missing_xml":131,"b23_missing_xml":8},
    "no_XML_synthesized_or_missing_reference_waived":True,
    "remote_materialization_is_future_native_requirement":True,
    "limits":[
        "The output-download predicate changes evidence I/O; it does not change test parameters or prove future downloads succeed.",
        "A remote output service or in-memory-output contract can override download behavior; no such new configuration is introduced.",
        "Original native runs and their failures remain historical evidence; offline URI rebasing is not a new native run.",
        "B21 dropped-receiver cause and broader product qualification are not resolved by this evidence-only change."
    ],
}
print(json.dumps(result,indent=2,sort_keys=True))
