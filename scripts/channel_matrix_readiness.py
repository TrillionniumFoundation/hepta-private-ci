#!/usr/bin/env python3
"""Create one non-mixable channel.matrix readiness manifest."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA1 = re.compile(r"[0-9a-f]{40}"); SHA256 = re.compile(r"[0-9a-f]{64}")
LOCAL = ("source_navigation","compilation","native_tests","strict_lint","formatting")
WORKFLOW = ".github/workflows/channel-matrix-readiness.yml"
MAP = "docs/modules/channel.matrix/IMPLEMENTATION_MAP.json"
PROFILE = "docs/modules/channel.matrix/PRODUCTION_QUALIFICATION_PROFILE.json"
LOCK = "codex-rs/Cargo.lock"

def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file(): raise ValueError(f"non-regular evidence: {path}")
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def read(path: Path) -> dict[str,Any]:
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out: raise ValueError(f"duplicate JSON key: {k}")
            out[k]=v
        return out
    if path.is_symlink() or not path.is_file() or path.stat().st_size>64*1024*1024: raise ValueError(f"invalid evidence: {path}")
    value=json.loads(path.read_text(encoding="utf-8"),object_pairs_hook=unique)
    if not isinstance(value,dict): raise ValueError("evidence object required")
    return value

def s1(value: object,label:str)->str:
    if not isinstance(value,str) or not SHA1.fullmatch(value): raise ValueError(f"invalid {label}")
    return value

def s256(value: object,label:str)->str:
    if not isinstance(value,str) or not SHA256.fullmatch(value): raise ValueError(f"invalid {label}")
    return value

def canonical(value:Path)->Path:
    if value.is_symlink(): raise ValueError("symlinked lane directory")
    result=value.resolve(strict=True)
    if not result.is_dir() or result!=value.absolute(): raise ValueError("lane directory must be canonical")
    return result

def manifest(directory:Path,row:dict)->dict[str,dict]:
    if row.get("schema")!="hepta.channel-matrix-artifact-manifest.v2" or row.get("runnerReportedStatus")!="success" or row.get("claims",{}).get("focusedCommandsPassed") is not True:
        raise ValueError("lane manifest is not successful")
    for name in ("homeserverQualified","independentAcceptance","activation","release","authorityGranted"):
        if row.get("claims",{}).get(name) is not False: raise ValueError(f"lane escalates {name}")
    inv={}
    for item in row.get("files",[]):
        if not isinstance(item,dict) or set(item)!={"path","bytes","sha256"}: raise ValueError("invalid manifest row")
        name=item["path"]; rel=Path(name)
        if not isinstance(name,str) or rel.is_absolute() or ".." in rel.parts or name in inv: raise ValueError("unsafe manifest path")
        actual=directory/rel
        if item["bytes"]!=actual.stat().st_size or item["sha256"]!=digest(actual): raise ValueError(f"manifest mismatch: {name}")
        inv[name]=item
    needed={"candidate.json","source.json","source-after.json","status.json","scenario-ledger.json","focused-tests.junit.xml","api-compile-fail.log","source-provenance-before.json","source-provenance-after.json"}
    for label in ("compile","focused-tests","clippy","format"): needed|={f"{label}.command.json",f"{label}.log"}
    if not needed<=inv.keys(): raise ValueError(f"missing lane evidence: {sorted(needed-inv.keys())}")
    return inv

def provenance(directory:Path,name:str,stage:str,source:dict)->dict:
    p=read(directory/name)
    claims=p.get("claims",{}); scan=p.get("scan",{}); clean1=p.get("cleanTreeBefore",{}); clean2=p.get("cleanTreeAfter",{})
    if p.get("schema")!="hepta.channel-matrix-source-provenance.v1" or p.get("stage")!=stage or p.get("checkoutSha")!=source["testedSha"] or p.get("treeSha")!=source["testedTree"] or claims.get("trackedOnly") is not True or claims.get("sourceClosurePassed") is not True or claims.get("productionQualified") is not False or claims.get("authorityGranted") is not False or scan.get("filesystemWalkUsed") is not False or clean1.get("clean") is not True or clean2.get("clean") is not True:
        raise ValueError(f"invalid source provenance: {name}")
    if p.get("workflow",{}).get("path")!=WORKFLOW: raise ValueError("wrong workflow provenance")
    s1(p["workflow"].get("gitBlob"),"workflow blob"); s256(p["workflow"].get("sha256"),"workflow digest")
    e=p.get("execution",{})
    for key in ("workflowRunId","attemptId","runnerImage","targetTriple"):
        if not isinstance(e.get(key),str) or not e[key]: raise ValueError(f"missing execution {key}")
    rows=p.get("files")
    if not isinstance(rows,list) or not rows: raise ValueError("empty provenance")
    for item in rows:
        if not isinstance(item,dict) or item.get("tracked") is not True or item.get("gitLsFilesErrorUnmatch") is not True or item.get("fromGeneratedDirectory") is not False or item.get("fromCache") is not False or item.get("fromArtifactDownload") is not False:
            raise ValueError("mixed source provenance")
    return p

def load_lane(value:Path, _label:str|None=None)->dict[str,Any]:
    directory=canonical(value); source=read(directory/"source.json"); after=read(directory/"source-after.json")
    candidate=read(directory/"candidate.json"); status=read(directory/"status.json"); ledger=read(directory/"scenario-ledger.json"); m=read(directory/"manifest.json")
    inv=manifest(directory,m)
    if source!=after or source.get("schema")!="hepta.channel-matrix-source-snapshot.v1" or not source.get("files"): raise ValueError("invalid source lane")
    for key in ("sourceSha","baseSha","testedSha","testedTree"): s1(source.get(key),key)
    expected={"commit":source["testedSha"],"tree":source["testedTree"]}
    if candidate.get("schema")!="hepta.channel-matrix-candidate-receipt.v1" or candidate.get("status")!="PASS_CHANNEL_MATRIX_CANDIDATE_BINDING" or candidate.get("candidate")!=expected or candidate.get("authorityGranted") is not False: raise ValueError("candidate mismatch")
    states=status.get("states",{}); status_id={**expected,"lane":source.get("lane")}
    if status.get("schema")!="hepta.channel-matrix-evidence-status.v2" or status.get("candidate")!=status_id or any(states.get(x)!="passed" for x in LOCAL) or states.get("target_qualification")!="not_proved" or states.get("independent_acceptance")!="not_proved" or status.get("activation") is not False or status.get("release") is not False or status.get("authority_granted") is not False: raise ValueError("incomplete lane status")
    if ledger.get("schema")!="hepta.channel-matrix-scenario-ledger.v2" or ledger.get("candidate")!=expected or ledger.get("lane")!=source.get("lane") or ledger.get("native_completion")!="passed" or ledger.get("native_blockers")!=[] or ledger.get("activation") is not False or ledger.get("release") is not False or ledger.get("authority_granted") is not False: raise ValueError("incomplete scenario ledger")
    before=provenance(directory,"source-provenance-before.json","checkout",source); post=provenance(directory,"source-provenance-after.json","post-qualification",source)
    fields=lambda p:[(x["repoRelativePath"],x["gitBlob"],x["sha256"],x["bytes"]) for x in p["files"]]
    if fields(before)!=fields(post) or before["workflow"]!=post["workflow"]: raise ValueError("source provenance changed")
    for key in ("workflowRunId","attemptId","runnerImage","targetTriple"):
        if before["execution"][key]!=post["execution"][key]: raise ValueError("execution identity changed")
    if str(m.get("runId"))!=before["execution"]["workflowRunId"] or str(m.get("runAttempt"))!=before["execution"]["attemptId"]: raise ValueError("manifest/provenance run mismatch")
    names=("candidate","source","status","scenario-ledger","manifest","source-provenance-before","source-provenance-after")
    return {"dir":directory,"source":source,"status":status,"ledger":ledger,"manifest":m,"inventory":inv,"provenance":before,
            "digests":{name.replace("-","_"):digest(directory/f"{name}.json") for name in names}}

def source_index(source:dict)->dict[str,dict]:
    out={}
    for item in source["files"]:
        if not isinstance(item,dict) or set(item)!={"path","gitBlob","sha256","bytes"}: raise ValueError("invalid source row")
        path=item["path"]
        if path in out: raise ValueError("duplicate source path")
        s1(item["gitBlob"],path); s256(item["sha256"],path); out[path]=item
    return out

def grouped(index:dict,predicate,domain:bytes)->str:
    rows=sorted((p,x["sha256"],x["bytes"]) for p,x in index.items() if predicate(p))
    if not rows: raise ValueError("empty source hash group")
    return hashlib.sha256(domain+b"\0"+json.dumps(rows,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()

def snapshot_hashes(source:dict,workflow_sha:str,frozen_source_sha:str)->dict[str,str]:
    idx=source_index(source)
    def one(path:str)->str:
        if path not in idx: raise ValueError(f"source snapshot lacks {path}")
        return s256(idx[path]["sha256"],path)
    return {"Cargo.lock_hash":one(LOCK),
            "migration_hash":grouped(idx,lambda p:p.startswith("codex-rs/hepta-matrix-store/migrations/"),b"hepta.matrix.migrations.v1"),
            "test_set_hash":grouped(idx,lambda p:p.startswith("scripts/tests/test_channel_matrix") or "/tests/" in f"/{p}/" or p.endswith("_tests.rs") or p.endswith("QUALIFICATION_SCENARIOS.json") or p=="codex-rs/.config/nextest.toml",b"hepta.matrix.tests.v1"),
            "qualification_profile_hash":one(PROFILE),"implementation_map_hash":one(MAP),
            "documentation_hash":grouped(idx,lambda p:p.startswith("docs/modules/channel.matrix/"),b"hepta.matrix.docs.v1"),
            "workflow_sha":s256(workflow_sha,"workflow digest"),"source_tree_hash":s1(source["testedTree"],"source tree"),
            "frozen_source_sha":s1(frozen_source_sha,"frozen source SHA")}

def derive_hashes(root:Path,source:dict,workflow_sha:str|None=None)->dict[str,str]:
    idx=source_index(source)
    def one(path:str)->str:
        if path not in idx: raise ValueError(f"source snapshot lacks {path}")
        return s256(idx[path]["sha256"],path)
    map_path=root/MAP
    if digest(map_path)!=one(MAP): raise ValueError("implementation map differs from source snapshot")
    observed=read(map_path).get("observedAtHead",{})
    if workflow_sha is None:
        legacy = ".github/workflows/channel-matrix-preserve-unknown.yml"
        workflow_sha = one(WORKFLOW) if WORKFLOW in idx else one(legacy)
    return snapshot_hashes(source,workflow_sha,s1(observed.get("commit"),"frozen source SHA"))

def require_same_execution(lanes:dict[str,dict])->tuple[str,str,str,str]:
    run_ids={str(x["manifest"].get("runId")) for x in lanes.values()}
    attempts={str(x["manifest"].get("runAttempt")) for x in lanes.values()}
    images={x["provenance"]["execution"]["runnerImage"] for x in lanes.values()}
    targets={x["provenance"]["execution"]["targetTriple"] for x in lanes.values()}
    if len(run_ids)!=1 or "None" in run_ids or len(attempts)!=1 or "None" in attempts:
        raise ValueError("lanes do not share one workflow run and attempt")
    if len(images)!=1 or len(targets)!=1: raise ValueError("lanes do not share one runner image and target triple")
    return run_ids.pop(),attempts.pop(),images.pop(),targets.pop()

def readiness(root_value:Path,source_head_dir:Path,base_merge_dir:Path,github_merge_dir:Path|None,mode:str,expected_source_sha:str,expected_base_sha:str,final_merge_sha:str|None)->dict[str,Any]:
    if mode not in ("pull-request","post-merge") or github_merge_dir is None: raise ValueError("three exact lanes are required")
    root=root_value.resolve(strict=True); source_sha=s1(expected_source_sha,"source SHA"); base_sha=s1(expected_base_sha,"base SHA")
    lanes={"source-head":load_lane(source_head_dir,"source-head"),"deterministic-merge":load_lane(base_merge_dir,"base-merge"),"github-merge":load_lane(github_merge_dir,"github-merge")}
    source=lanes["source-head"]["source"]; deterministic=lanes["deterministic-merge"]["source"]; github=lanes["github-merge"]["source"]
    if source["testedSha"]!=source_sha or source["sourceSha"]!=source_sha or source["baseSha"]!=base_sha: raise ValueError("source-head identity mismatch")
    registry=lanes["source-head"]["ledger"].get("registry_sha256"); external=lanes["source-head"]["ledger"].get("external_gates_remaining")
    workflow_digest=lanes["source-head"]["provenance"]["workflow"]["sha256"]
    for name,lane in lanes.items():
        if lane["source"]["sourceSha"]!=source_sha or lane["source"]["baseSha"]!=base_sha: raise ValueError(f"{name} source/base mismatch")
        if lane["ledger"].get("registry_sha256")!=registry or lane["ledger"].get("external_gates_remaining")!=external: raise ValueError(f"{name} scenario identity mismatch")
        if lane["provenance"]["workflow"]["sha256"]!=workflow_digest: raise ValueError("workflow identity differs across lanes")
    if deterministic["testedTree"]!=github["testedTree"]: raise ValueError("GitHub and deterministic merge trees differ")
    final=None
    if mode=="post-merge":
        final=s1(final_merge_sha,"final merge SHA")
        if final!=source_sha or github["testedSha"]!=final: raise ValueError("post-merge lane is not final merge SHA")
    elif final_merge_sha is not None: raise ValueError("PR cannot claim final merge SHA")
    run,attempt,image,target=require_same_execution(lanes)
    source_hashes=derive_hashes(root,source,workflow_digest)
    hashes=snapshot_hashes(github,workflow_digest,source_hashes["frozen_source_sha"])
    artifact_hashes={name:{"artifactSetSha256":s256(lane["manifest"].get("artifactSetSha256"),name),**lane["digests"]} for name,lane in lanes.items()}
    blockers=["target_qualification_not_proved","independent_acceptance_not_proved","activation_not_granted","release_not_granted"]
    if mode=="pull-request": blockers.append("final_merge_sha_not_yet_available")
    return {"schema":"hepta.channel-matrix-readiness.v1","mode":mode,"source_head_sha":source_sha,
            "frozen_source_sha":hashes.pop("frozen_source_sha"),"base_sha":base_sha,
            "deterministic_merge_sha":s1(deterministic["testedSha"],"deterministic merge SHA"),
            "github_merge_sha":s1(github["testedSha"],"GitHub merge SHA"),"workflow_sha":hashes.pop("workflow_sha"),
            "final_merge_sha":final,"workflow_run_id":run,"attempt_id":attempt,"runner_image":image,
            "target_triple":target,**hashes,"artifact_hashes":artifact_hashes,
            "required_lanes":{name:{"status":"passed","candidate":lane["status"]["candidate"]} for name,lane in lanes.items()},
            "scenario_registry_sha256":registry,"external_gates_remaining":external,"mergeReady":True,
            "productionQualified":False,"blockers":blockers,"claims":{"singleRunSingleAttempt":True,
            "mixedEvidenceAccepted":False,"allRepositoryControlledLanesPassed":True,
            "targetQualification":"not_proved","independentAcceptance":"not_proved","activation":False,
            "promotion":False,"release":False,"authorityGranted":False}}

def write(path_value:Path,row:dict,root:Path)->None:
    path=path_value.absolute(); parent=path.parent.resolve(strict=True)
    if path_value.is_symlink() or path.exists() or parent.is_relative_to(root.resolve()): raise ValueError("output must be new and outside checkout")
    with path.open("x",encoding="utf-8") as f: json.dump(row,f,indent=2,sort_keys=True); f.write("\n")

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-head",type=Path,required=True); p.add_argument("--base-merge",type=Path,required=True); p.add_argument("--github-merge",type=Path,required=True)
    p.add_argument("--mode",choices=("pull-request","post-merge"),required=True); p.add_argument("--expected-source-sha",required=True); p.add_argument("--expected-base-sha",required=True)
    p.add_argument("--final-merge-sha"); p.add_argument("--output",type=Path,required=True); p.add_argument("--repository-root",type=Path,default=ROOT,help=argparse.SUPPRESS)
    a=p.parse_args()
    try: write(a.output,readiness(a.repository_root,a.source_head,a.base_merge,a.github_merge,a.mode,a.expected_source_sha,a.expected_base_sha,a.final_merge_sha),a.repository_root)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc: p.exit(1,f"FAIL_CHANNEL_MATRIX_READINESS: {exc}\n")
    return 0
if __name__=="__main__": raise SystemExit(main())
