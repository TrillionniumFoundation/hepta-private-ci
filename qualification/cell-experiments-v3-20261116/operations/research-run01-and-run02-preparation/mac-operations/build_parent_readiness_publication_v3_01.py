"""Build only a reviewed evidence input ZIP; never mutate the publication Git worktree."""
from pathlib import Path
import collections,gzip,hashlib,io,json,os,stat,subprocess,time,zipfile

ROOT=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
WORK=ROOT/"publication-native-01"
BASE="182774e5b12d138ea536d179e6539f1f6a3ee53a"
BUILD=ROOT/"parent-readiness-frozen-01"
PREFIX="qualification/cell-experiments-v3-20261116/operations/parent-readiness-closed-03"
BRANCH="codex/cell-experiments-v3-20261116-0c078a-s"
ARCHIVE=ROOT/"publication-parent-readiness-input-01.zip"

def sha(raw):return hashlib.sha256(raw).hexdigest()
def canon(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()+b"\n"
def write(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
def git(*argv):
    result=subprocess.run(["git",*argv],cwd=WORK,capture_output=True,check=True)
    return result.stdout
def stable(path):
    assert path.is_file() and path.resolve()==path
    before=path.stat();raw=path.read_bytes();after=path.stat()
    assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
    return raw
def main():
    assert git("rev-parse","HEAD").decode().strip()==BASE
    assert not git("status","--porcelain=v1").strip()
    assert not git("ls-tree","-r",BASE,"--",PREFIX).strip()
    core={}
    for line in git("ls-tree","-r",BASE,"--","scripts/cell_experiments").decode().splitlines():
        meta,name=line.split("\t",1)
        if name.endswith(".py"):core[name]=meta.split()[2]
    assert len(core)==64
    entries={};stages=[]
    definitions=[
      (44,"prior-baselines","Archive original parent01 and incomplete parent02 evidence"),
      (45,"parent03-raw","Archive complete parent03 phases and independent exit evidence"),
      (46,"workspace-binding","Bind parent03 RAM materials and the minimal source change"),
      (47,"owned-capture","Preserve the owned launcher and original-stream checkpoint tools"),
      (48,"preflight-history","Retain actual preflight observations and their precise correction"),
      (49,"outcome-accounting","Record failed tasks, real SQLite effects and additional replay costs"),
      (50,"helper04-closed","Archive fixed helper04 sources and completed engineering deployment"),
      (51,"package-coverage","Document exact coverage, known gaps and the frozen assembly")]
    for number,label,title in definitions:
        stages.append({"id":"s%d-%s"%(number,label),"number":number,"commit_subject":title,"draft_pr_head":BRANCH+str(number),"draft_pr_base":BRANCH+str(number-1),"files":[],"kind":"bounded_evidence_and_reviewable_source","mechanical_evidence_exception":None})
    def add(index,relative,raw,origin):
        name=PREFIX+"/"+relative
        assert name not in entries and len(raw)<512000,(name,len(raw))
        if name.endswith(".bin"):assert len(raw)<=322560
        entries[name]={"raw":raw,"origin":origin}
        stages[index]["files"].append(name)
    def file(index,relative,path):add(index,relative,stable(path),str(path))
    def tree(index,label,directory,select):
        for path in sorted(directory.iterdir()):
            if path.is_file() and select(path):file(index,label+"/"+path.name,path)
    old=ROOT/"parent02-salvage-ram01"
    tree(0,"prior02/archive",old/"salvage-parent02-01",lambda p:p.name=="MANIFEST.json" or ".part" in p.name)
    for name in ("TRANSFER_WAIT.json","VERIFIED.json","WORKSPACE_OWNERSHIP.json"):
        file(0,"prior02/"+name,old/name)
    history=ROOT/"parent03-recovery-history01"
    for name in ("MANIFEST.json","RECOVERY_HISTORY.zip"):file(0,"recovery-history/"+name,history/name)
    tree(0,"recovery-history/controller",history/"controller-recovered",lambda p:True)
    checkpoints=("parent03-setup-checkpoint01","parent03-repository-checkpoint01","parent03-terminal-checkpoint01")
    for directory in checkpoints:
        tree(1,directory,ROOT/directory,lambda p:p.name in ("MANIFEST.json","POSTHOC_CAPTURE.json","TRANSFER_WAIT.json","REMOTE_SOURCE.py","stderr.log") or ".part" in p.name or p.name.startswith("CONTROLLER_"))
    prepared=ROOT/"parent03-preparation-01"
    for name in ("QWEN_READINESS_03_DIFF.patch","copy_qwen_materials_ram03.py","QWEN_MATERIALS_RAM_03_RAW.json","QWEN_RAM_WORKSPACE_OWNERSHIP_RAW.json"):
        file(2,"preparation/"+name,prepared/name)
    for name in ("launch_qwen_parent03_owned.py","checkpoint_qwen_parent03_mac.py","check_owned_notify_postrun.py","OWNED_NOTIFY_POSTRUN_RECHECK.json"):
        file(3,"capture/"+name,prepared/name)
    for name in ("preflight_qwen_readiness_v3_04.py","preflight_qwen_readiness_v3_05.py","QWEN_READINESS_03_PREFLIGHT_RAW.json","QWEN_READINESS_03_PREFLIGHT_FIRST_RAW.json","QWEN_READINESS_03_PREFLIGHT_TERMINAL.json"):
        file(4,"preflight/"+name,prepared/name)
    file(4,"preflight/FORMAT_04.json",ROOT/"FORMAT_04.json")
    assert sha(entries[PREFIX+"/preflight/FORMAT_04.json"]["raw"])=="836ca8e35c74b5ef03dd101a829bb8d3d70f737d0d26bd2a547776d75a0a6e82"
    for name in ("analyze_parent02_mac.py","analyze_parent03_mac.py"):file(5,"analysis/"+name,prepared/name)
    file(5,"analysis/QWEN_PARENT02_POSTHOC_COUNTS.json",old/"QWEN_PARENT02_POSTHOC_COUNTS.json")
    current=ROOT/"parent03-terminal-checkpoint01"
    file(5,"analysis/QWEN_PARENT03_POSTHOC_SUMMARY.json",current/"QWEN_PARENT03_POSTHOC_SUMMARY.json")
    tree(5,"analysis/raw-summary",current/"raw-summary",lambda p:True)
    helper=ROOT/"operations/qwen-development-helpers-04.zip"
    file(6,"helper04/qwen-development-helpers-04.zip",helper)
    with zipfile.ZipFile(helper) as package:
        assert package.testzip() is None and len(package.namelist())==11
        helper_members=[{"path":i.filename,"bytes":i.file_size,"sha256":sha(package.read(i))} for i in package.infolist()]
        for name in ("QWEN_DEVELOPMENT_HELPERS_04.diff","QWEN_DEVELOPMENT_HELPERS_04.json","QWEN_DEVELOPMENT_HELPERS_04_CHANGES.md","QWEN_DEVELOPMENT_TESTS_03.json","QWEN_DEVELOPMENT_TESTS_03.log","QWEN_DEVELOPMENT_TESTS_03.stdout.log"):
            add(6,"helper04/engineering/"+name,package.read(name),str(helper)+"!"+name)
    file(6,"helper04/HELPERS04_DEPLOYMENT_OBSERVATION_01.json",ROOT/"operations/HELPERS04_DEPLOYMENT_OBSERVATION_01.json")
    file(6,"helper04/deploy_qwen_helpers04_01.py",ROOT/"operations/deploy_qwen_helpers04_01.py")
    tree(6,"helper04/deployment",ROOT/"helper04-deployment-01",lambda p:p.name in ("STARTED.json","RESULT.json","stdout.log","stderr.log"))

    prior_bytes=stable(old/"salvage-parent02-01/QWEN_PARENT02_PARTIAL_RAW.zip")
    assert sha(prior_bytes)=="6fb45706a7123b65cdc260ed33ce0a4afc9456eafd96b08a7dc9707cf38a70e7"
    with zipfile.ZipFile(io.BytesIO(prior_bytes)) as package:
        assert package.testzip() is None and len(package.namelist())==114
        original01=package.read("prior-failed-operation01/QWEN_READINESS_EVIDENCE_01.zip")
        assert sha(original01)=="e4189a4eddbf8d48bd59515de284b064416c7830cac040442d089ce48e1e0070"
        with zipfile.ZipFile(io.BytesIO(original01)) as child:
            assert child.testzip() is None and len(child.namelist())==21
        parent01_coverage={"archive_sha256":sha(original01),"raw_members":21,"container_member":"prior-failed-operation01/QWEN_READINESS_EVIDENCE_01.zip"}
    for directory in (old/"salvage-parent02-01",*(ROOT/name for name in checkpoints)):
        manifest=json.loads((directory/"MANIFEST.json").read_bytes())
        joined=b"".join((directory/item["path"]).read_bytes() for item in manifest["parts"])
        assert (len(joined),sha(joined))==(manifest["archive"]["bytes"],manifest["archive"]["sha256"])
        for part in manifest["parts"]:
            raw=(directory/part["path"]).read_bytes()
            assert (len(raw),sha(raw))==(part["bytes"],part["sha256"]) and len(raw)<=322560
        with zipfile.ZipFile(io.BytesIO(joined)) as package:assert package.testzip() is None
    coordinator=[json.loads(line) for line in gzip.decompress((ROOT/"coordinator-provenance-01/MEMBERS.jsonl.gz").read_bytes()).decode().splitlines() if line]
    historical={row["name"]:row for row in coordinator if row.get("kind")=="member"}
    missing_first_envelopes=[name for name in ("QWEN_PARENT02_LOST_PROCESS_OBSERVATION.json","QWEN_PARENT02_PARTIAL_TERMINAL_READ.json") if name not in historical]
    scope={
      "schema":"hepta.closed-parent-evidence-coverage.v3","base_commit":BASE,"stage_range":[44,51],
      "parent01":parent01_coverage,
      "parent02":{"raw_members":114,"archive_sha256":sha(prior_bytes),"operation_complete":False,"known_generations_are_lower_bound":14,"original_exit_code":None,"capture_complete":False},
      "parent03":{"raw_members":308,"archive_sha256":"036322be9179b66580717ace8f23faa5bdbaaa6a09145c329d2bbd7742863e4b","operation_status":"COMPLETE","repository_status":"NOT_READY","repository_successes":0,"repository_tasks":9,"sqlite_successes":0,"sqlite_tasks":3,"model_generations":54},
      "real_sqlite_execution":{"actions":36,"write_transactions":11,"newly_applied_effects":3,"task_successes":0,"database_complete_scenarios":2,"all_agent_terminal_verifications_failed":True},
      "cost":{"parent03_output_tokens":5499,"prior02_retained_output_tokens_lower_bound":3819,"combined_observed_calls_lower_bound":68,"combined_observed_output_tokens_lower_bound":9318,"cost_scopes_are_nested_not_additive":True,"monetary_cost":None,"energy_joules":None},
      "helper04":{"archive_sha256":sha(stable(helper)),"members":helper_members,"sources_frozen":True,"engineering_scope":"preserved TESTS_03 fixture results plus helper04 deployment; no training/model result added by this package"},
      "already_published":{"base":BASE,"coordinator_snapshot_utc":"2026-11-17T02:27:09Z","old_helper01_helper02_and_recovery04_sources_referenced_not_reexpanded":True,"nested_original_archives_retain_embedded_duplicate_bytes_to_preserve_original_identity":True},
      "gaps":{"unavailable_original_local_only_envelopes":missing_first_envelopes,"replacement_not_claimed":True,"later_independent_reobservation_preserved":"recovery-history/controller/QWEN_PARENT02_LOST_POSTHOC_REOBSERVATION.json","original_4096_terminal_bytes_preserved":True,"original_parent02_OS_exit_still_unknown":True,"unused_local_export_drafts_and_earlier_local_posthoc_outputs_not_claimed_as_archived":True,"initial_local_notify_test_stdout_not_recovered":True,"postrun_real_pipe_recheck_explicitly_labeled":True},
      "exclusions":["3GB model weights","venv/wheels/caches","research-sft-v1 modules under active development","research model runs or results","new confirmation data","changes to the frozen64 core","production adoption"],
      "new_C":False,"new_users":0,"new_external_teachers":0,"independent_sample_increment":0,"original_inputs_modified":False}
    add(7,"COVERAGE.json",canon(scope),"generated coverage index from verified original bytes")
    readme="""# Closed parent readiness evidence: operations 01, 02 and 03

This package preserves original outputs and separately labels later analysis.
It contains no training result, new user/source, confirmation C, or production adoption.

## Actual results

- Parent01 ended before reference/model execution because an exact receipt timeout
  check incorrectly expected integer 1200 instead of the recorded residual value.
  Its completed failure archive contains 21 original members and is nested intact
  in the parent02 preservation archive. It added zero model calls.
- Parent02 completed at least 14 generations before the HOME filesystem filled.
  Its original 4096-byte terminal capture and truncated/empty JSON files remain
  unchanged. The original OS exit is unknown and terminal capture is incomplete.
  The known 3819 generated tokens and 249.60339490897604 generation seconds remain
  additional lower-bound costs; they are not erased by replay.
- Parent03 used the same model, exact119 source members,64 frozen core files,
  task order and generation budget. Actual copies of the9 pinned model files
  were placed in RAM; the original HOME runtime/materials remained unchanged.
  All temporary files, caches and new outputs used the dedicated RAM workspace.
- Parent03 completed both panels and postverification. Repository readiness is
  NOT_READY:0/9 tasks, with18 JSON parser rejections before business execution.
  SQLite had36 real primitive actions,11 write transactions and3 new effects.
  Two database goals were physically complete, but all3 terminal task checks
  failed at the decision budget. Side effects are not task-success substitutes.
- Parent03 made54 generations, producing5499 tokens. Its measured operation wall
  time was376.4983984899882s. Model/panel/operation/wrapper timing scopes overlap;
  do not add nested scopes. Money, energy and device-wide GPU time were not measured.
- Replay adds0 independent samples. The combined retained lower bound is68 calls
  and9318 generated tokens. This is exposed development evidence, not confirmation.

## Restoration and provenance

Concatenate each archive's ordered .part files outside the repository, verify
part size/SHA256 and complete ZIP size/SHA256 from its MANIFEST, then verify
every member using the original member index or POSTHOC_CAPTURE.
Every published object is below512000 bytes; binary parts are at most322560.
Do not commit the reconstructed larger ZIPs.

The phase archives retain original stdout/stderr and actual child Popen.wait
STARTED/EXIT receipts. Independent Mac PTY observations are separate controller
evidence. A child wait result does not fabricate an h terminal capture status.
The storage-recovery archive preserves failed DATA preparation, actual available
space, the delayed successful RAM job, and the rejected cross-API mkdir attempt.
The initial text-key lookup was not proof that a queued job had not launched.

The first RAM preflight's MemAvailable output field was overwritten by a GPU
memory string. Its original file remains intact. A new precisely corrected
preflight was executed; only that actual second receipt is the launch binding.
The published code diff and all source/archive hashes identify the exact run.
The complete helper03 source is an original member of the terminal archive.

COVERAGE.json lists exact included scopes and known local-only gaps. Native
remote receipts and a later original-terminal observation are preserved without
claiming byte recovery of unavailable earlier controller envelopes.
The postrun closed-pipe check is labeled as a later engineering recheck.

The helper04 ZIP is a separate closed source/engineering/deployment snapshot.
Its preserved TESTS_03 fixtures are not actual training results. Active research
modules, research runs and new results are deliberately outside this package.
Prior runtime/material/source artifacts already published throughs43 are
referenced through their hashes and the coordinator snapshot; original nested
bundles keep any embedded repeats solely to preserve original archive identity.
"""
    add(7,"README.md",readme.encode(),"written scope and restoration documentation")
    file(7,"build_parent_readiness_publication_v3_01.py",Path(__file__))

    BUILD.mkdir(mode=0o700,exist_ok=False)
    for name,item in entries.items():write(BUILD/"payload"/name,item["raw"])
    files={}
    for name,item in entries.items():
        path=BUILD/"payload"/name
        result=subprocess.run(["git","diff","--no-index","--numstat","--","/dev/null",str(path)],capture_output=True,text=True)
        assert result.returncode in (0,1),(name,result.stderr)
        fields=result.stdout.split("\t",2)
        added=0 if fields[0]=="-" else int(fields[0] or "0")
        files[name]={"bytes":len(item["raw"]),"sha256":sha(item["raw"]),"git_added_text_lines":added,"origin":item["origin"]}
    for stage in stages:
        stage["added_text_lines"]=sum(files[name]["git_added_text_lines"] for name in stage["files"])
        assert stage["added_text_lines"]<=800,stage
        stage["prefer_under_500_met"]=stage["added_text_lines"]<500
        stage["mechanical_json_evidence"]=[name for name in stage["files"] if name.endswith((".json",".jsonl",".log",".txt"))]
        stage["draft_pr_title"]="[draft] "+stage["commit_subject"]
        stage["draft_pr_body"]="Preserve the closed parent-readiness operation evidence for this stage. Original bytes and exact hashes are retained. The parent baseline failed all terminal task checks; real SQLite side effects and incomplete prior costs remain distinct. No new independent samples, training result or production adoption is claimed."
    plan={"schema":"hepta.native-final-publication-plan.v3","base_commit":BASE,"expected_complete_core_git_blobs":core,
          "files":files,"stages":stages,"source_scope":"closed parent01/02/03 and frozen helper04 only","new_model_execution":False,
          "frozen_at_ns":time.time_ns(),"binary_part_limit":322560,"git_object_limit_exclusive":512000}
    plan_raw=canon(plan);write(BUILD/"NATIVE_FINAL_PLAN_01.json",plan_raw)
    with zipfile.ZipFile(ARCHIVE,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        archive.writestr("NATIVE_FINAL_PLAN_01.json",plan_raw)
        for name,item in entries.items():
            info=zipfile.ZipInfo(name,date_time=(2026,11,17,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            archive.writestr(info,item["raw"])
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None and set(archive.namelist())==set(files)|{"NATIVE_FINAL_PLAN_01.json"}
        for name,row in files.items():assert (len(archive.read(name)),sha(archive.read(name)))==(row["bytes"],row["sha256"])
    assert git("rev-parse","HEAD").decode().strip()==BASE and not git("status","--porcelain=v1").strip()
    report={"status":"FROZEN_NOT_PUBLISHED","archive":str(ARCHIVE),"archive_bytes":ARCHIVE.stat().st_size,"archive_sha256":sha(stable(ARCHIVE)),
            "plan":str(BUILD/"NATIVE_FINAL_PLAN_01.json"),"plan_sha256":sha(plan_raw),"base_commit":BASE,"files":len(files),
            "total_payload_bytes":sum(row["bytes"] for row in files.values()),"largest_object_bytes":max(row["bytes"] for row in files.values()),
            "stages":[{"id":s["id"],"files":len(s["files"]),"text_lines":s["added_text_lines"],"under500":s["prefer_under_500_met"]} for s in stages],
            "publication_worktree_modified":False,"model_calls_added":0}
    write(BUILD/"MANIFEST.json",canon(report));print(json.dumps(report),flush=True)
if __name__=="__main__":main()
