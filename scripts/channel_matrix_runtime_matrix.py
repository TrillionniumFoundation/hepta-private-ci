#!/usr/bin/env python3
"""Validate distinct exact-candidate channel.matrix runtime crash evidence."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "docs/modules/channel.matrix/RUNTIME_CRASH_MATRIX.json"
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_JSON = 32 * 1024 * 1024

def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file(): raise ValueError(f"non-regular artifact: {path.name}")
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def read(path: Path) -> dict[str,Any]:
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out: raise ValueError(f"duplicate JSON key: {k}")
            out[k]=v
        return out
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_JSON: raise ValueError(f"invalid JSON artifact: {path}")
    value=json.loads(path.read_text(encoding="utf-8"),object_pairs_hook=unique)
    if not isinstance(value,dict): raise ValueError("JSON object required")
    return value

def exact(value:object, pattern:re.Pattern[str], label:str)->str:
    if not isinstance(value,str) or not pattern.fullmatch(value): raise ValueError(f"invalid {label}")
    return value

def canonical_dir(value:Path)->Path:
    if value.is_symlink(): raise ValueError("symlinked evidence directory")
    result=value.resolve(strict=True)
    if not result.is_dir() or result!=value.absolute(): raise ValueError("evidence directory must be canonical")
    return result

def artifact(directory:Path,row:object,used:set[str])->Path:
    if not isinstance(row,dict) or set(row)!={"path","bytes","sha256"}: raise ValueError("invalid artifact reference")
    name=row["path"]
    if not isinstance(name,str) or not name or Path(name).is_absolute() or ".." in Path(name).parts or name in used: raise ValueError("unsafe or reused artifact path")
    path=(directory/name).resolve(strict=True)
    if not path.is_relative_to(directory) or path.is_symlink() or not path.is_file(): raise ValueError("artifact escapes evidence directory")
    if type(row["bytes"]) is not int or row["bytes"]!=path.stat().st_size or exact(row["sha256"],SHA256,"artifact digest")!=digest(path): raise ValueError(f"artifact mismatch: {name}")
    used.add(name); return path

def validate(evidence_value:Path,manifest_path:Path,expected_commit:str,expected_tree:str,profile_path:Path=PROFILE)->dict[str,Any]:
    directory=canonical_dir(evidence_value); commit=exact(expected_commit,SHA1,"candidate commit"); tree=exact(expected_tree,SHA1,"candidate tree")
    profile=read(profile_path); manifest=read(manifest_path)
    if profile.get("schema")!="hepta.channel-matrix-runtime-crash-profile.v1" or profile.get("schemaVersion")!=1: raise ValueError("unsupported runtime profile")
    storage=profile.get("storage",{})
    if storage.get("canonicalOwner")!="sqlite" or storage.get("postgresqlRequired") is not False or storage.get("postgresqlSubstitutionForbidden") is not True: raise ValueError("runtime profile weakens canonical SQLite ownership")
    if manifest.get("schema")!="hepta.channel-matrix-runtime-evidence.v1" or manifest.get("candidate")!={"commit":commit,"tree":tree} or manifest.get("storageOwner")!="sqlite" or manifest.get("postgresqlSubstitutionUsed") is not False: raise ValueError("runtime manifest identity/storage mismatch")
    claims=manifest.get("claims",{})
    for key in ("productionQualified","activation","promotion","release","authorityGranted"):
        if claims.get(key) is not False: raise ValueError(f"runtime manifest escalates {key}")
    used:set[str]=set()
    runner_path=artifact(directory,manifest.get("runnerEvidence"),used); runner=read(runner_path)
    required_true=("exact_candidate_evidence","test_assertions_passed","durable_artifacts_verified","explicit_process_shutdown_completed","all_historical_product_pids_absent","loopback_proxy_shutdown_completed","loopback_proxy_pid_absent","docker_resources_removed","runtime_root_removed","credential_capabilities_removed","private_fixture_root_removed")
    if runner.get("schema_version")!=profile.get("transport",{}).get("runnerEvidenceSchemaVersion") or runner.get("candidate_sha")!=commit or runner.get("candidate_tree_sha")!=tree or any(runner.get(k) is not True for k in required_true) or runner.get("promotion") is not False or runner.get("operator_acceptance") is not False: raise ValueError("runner evidence is incomplete or wrong-candidate")
    for field,ref_name in (("artifact_set_sha256","artifactSet"),("completion_sha256","completion")):
        path=artifact(directory,manifest.get(ref_name),used)
        if exact(runner.get(field),SHA256,field)!=digest(path): raise ValueError(f"runner evidence does not bind {ref_name}")
    scenarios=profile.get("scenarios")
    if not isinstance(scenarios,list) or not scenarios: raise ValueError("runtime profile has no scenarios")
    expected={row.get("id"):row for row in scenarios if isinstance(row,dict)}
    if None in expected or len(expected)!=len(scenarios): raise ValueError("duplicate/invalid profile scenario")
    supplied=manifest.get("scenarios")
    if not isinstance(supplied,list): raise ValueError("runtime scenarios must be a list")
    supplied_map={row.get("id"):row for row in supplied if isinstance(row,dict)}
    if None in supplied_map or len(supplied_map)!=len(supplied) or set(supplied_map)!=set(expected): raise ValueError("missing, duplicate or unknown runtime scenario")
    validated=[]
    for scenario_id in sorted(expected):
        ref=supplied_map[scenario_id]
        if ref.get("result")!="pass": raise ValueError(f"runtime scenario did not pass: {scenario_id}")
        path=artifact(directory,ref.get("artifact"),used); row=read(path); spec=expected[scenario_id]
        if row.get("schema")!="hepta.channel-matrix-runtime-scenario.v1" or row.get("id")!=scenario_id or row.get("candidate")!={"commit":commit,"tree":tree} or row.get("storageOwner")!="sqlite" or row.get("evidenceClass")!=spec.get("evidenceClass") or row.get("result")!="pass": raise ValueError(f"invalid runtime scenario artifact: {scenario_id}")
        oracles=row.get("oracles")
        required=spec.get("oracles")
        if not isinstance(oracles,dict) or not isinstance(required,list) or set(oracles)!=set(required) or any(oracles.get(name) is not True for name in required): raise ValueError(f"runtime scenario oracles incomplete: {scenario_id}")
        row_claims=row.get("claims",{})
        if row_claims.get("authorityGranted") is not False or row_claims.get("productionQualified") is not False: raise ValueError(f"runtime scenario escalates authority: {scenario_id}")
        validated.append({"id":scenario_id,"artifact":ref["artifact"],"oracles":required})
    return {"schema":"hepta.channel-matrix-runtime-validation.v1","candidate":{"commit":commit,"tree":tree},"profile_sha256":digest(profile_path),"manifest_sha256":digest(manifest_path),"storageOwner":"sqlite","postgresqlSubstitutionUsed":False,"runtimeMatrixQualified":True,"scenarios":validated,"invariants":profile.get("invariants"),"productionQualified":False,"independentAcceptance":False,"activation":False,"promotion":False,"release":False,"authorityGranted":False}

def write(path_value:Path,value:dict,directory:Path)->None:
    path=path_value.absolute(); parent=path.parent.resolve(strict=True)
    if path_value.is_symlink() or path.exists() or parent.is_relative_to(directory): raise ValueError("output must be new and outside evidence directory")
    with path.open("x",encoding="utf-8") as f: json.dump(value,f,indent=2,sort_keys=True); f.write("\n")

def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--evidence-directory",type=Path,required=True); p.add_argument("--manifest",type=Path,required=True); p.add_argument("--expected-commit",required=True); p.add_argument("--expected-tree",required=True); p.add_argument("--profile",type=Path,default=PROFILE); p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        directory=canonical_dir(a.evidence_directory); value=validate(directory,a.manifest,a.expected_commit,a.expected_tree,a.profile); write(a.output,value,directory)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc: p.exit(1,f"FAIL_CHANNEL_MATRIX_RUNTIME_MATRIX: {exc}\n")
    return 0
if __name__=="__main__": raise SystemExit(main())
