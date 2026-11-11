from pathlib import Path
import collections,hashlib,json,os,re,subprocess,sys,tempfile,time,xml.etree.ElementTree as ET

if len(sys.argv)!=4: raise SystemExit("requires repository exact-source-sha evidence-output")
repo=Path(sys.argv[1]).resolve(strict=True)
source=sys.argv[2]
out=Path(sys.argv[3])
if not re.fullmatch(r"[0-9a-f]{40}",source): raise SystemExit("exact source SHA required")
if not str(repo).startswith("/home/qian-qi/hepta-learn-all-owners-ce434-20261111-"): raise SystemExit("unexpected qualification repository")
evidence=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111")
if out.parent!=evidence/"native" or not out.name.startswith("all-owners-"+source[:12]+"-"): raise SystemExit("unexpected evidence path")
out.mkdir(parents=True,exist_ok=False)
env=dict(os.environ)
env.update(CODEX_REPO_ROOT=str(repo),CARGO_TARGET_DIR="/home/qian-qi/hepta-learn-ce434-target",CARGO_BUILD_JOBS="4",CARGO_INCREMENTAL="0",CARGO_PROFILE_TEST_DEBUG="0",CARGO_PROFILE_DEV_DEBUG="0",CARGO_NET_OFFLINE="true",PYTHONDONTWRITEBYTECODE="1",SOURCE_SHA=source,TESTED_SHA=source,BASE_SHA="73f20ed9a09bc5716484f497654640aedcec268d",HEPTA_CI_LANE="source-head")
env["PATH"]="/home/qian-qi/hepta-learn-ce434-tools/uv-venv/bin:/home/qian-qi/.local/bin:/home/qian-qi/.cargo/bin:"+env["PATH"]
def sha(path):
    with path.open("rb") as stream: return hashlib.file_digest(stream,"sha256").hexdigest()
def git(*args): return subprocess.check_output(["git",*args],cwd=repo,env=env,text=True).strip()
if git("rev-parse","HEAD")!=source or git("status","--porcelain=v1","--untracked-files=all"):
    raise RuntimeError("fixed source must be clean before qualification")
pinroot=evidence/"native/v8-pinned-150-4-0-v2"
pinbytes=(pinroot/"manifest.json").read_bytes()
if hashlib.sha256(pinbytes).hexdigest()!="9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5": raise RuntimeError("V8 manifest changed")
pin=json.loads(pinbytes)
if pin["cargo_lock_sha256"]!=sha(repo/"codex-rs/Cargo.lock") or pin["resolver_sha256"]!=sha(repo/"scripts/codex_package/v8.py"): raise RuntimeError("V8 source changed")
expected={"RUSTY_V8_ARCHIVE":"a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583","RUSTY_V8_SRC_BINDING_PATH":"7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506"}
if set(pin["environment"])!=set(expected): raise RuntimeError("V8 pair incomplete")
for key,digest in expected.items():
    path=Path(pin["environment"][key])
    if path.parent!=pinroot or path.is_symlink() or sha(path)!=digest: raise RuntimeError("V8 artifact changed")
env.update(pin["environment"])
canonical=Path(tempfile.mkdtemp(prefix="hlca-",dir="/tmp")).resolve(strict=True)
if len(os.fsencode(canonical))>32 or canonical.is_symlink() or canonical.stat().st_uid!=os.getuid(): raise RuntimeError("short original owned temporary root required")
env["TMPDIR"]=str(canonical)
sys.dont_write_bytecode=True
report={"source_sha":source,"source_tree":git("rev-parse","HEAD^{tree}"),"canonical_tmpdir":str(canonical),"v8_manifest_sha256":hashlib.sha256(pinbytes).hexdigest(),"state":"starting","steps":[],"full_chain_acceptance":{"positive":0,"no_update":0,"daemon_root_cold_restart":0}}
def checkpoint():
    pending=out/"result.pending.json"
    pending.write_text(json.dumps(report,indent=2)+"\n")
    pending.replace(out/"result.json")
    print(json.dumps(report),flush=True)
def step(name,args):
    report["state"]=name
    checkpoint()
    log=out/(name+".driver.log")
    started=time.monotonic()
    with log.open("xb") as stream: result=subprocess.run(args,cwd=repo,env=env,stdout=stream,stderr=subprocess.STDOUT,check=False)
    report["steps"].append({"name":name,"exit_code":result.returncode,"seconds":time.monotonic()-started,"log_sha256":sha(log),"log_bytes":log.stat().st_size})
    checkpoint()
    return result.returncode

v8=["/usr/bin/python3",str(repo/"scripts/hepta_ci_v8.py"),"--run"]
helpers=out/"helpers"
code=step("helper-build",v8+["/usr/bin/python3",str(repo/"scripts/hepta_cell_test_helpers.py"),"--package","codex-hepta-infer-worker-host","--output-dir",str(helpers)])
if code:
    report["state"]="helper-failed"; checkpoint(); raise SystemExit(code)
code=step("helper-verify",["/usr/bin/python3",str(repo/"scripts/hepta_cell_test_helpers.py"),"--package","codex-hepta-infer-worker-host","--output-dir",str(helpers),"--verify-only"])
if code:
    report["state"]="helper-verification-failed"; checkpoint(); raise SystemExit(code)
env.update(json.loads((helpers/"env.json").read_text()))
junit=repo/"codex-rs/target/nextest/local/junit.xml"
junit.unlink(missing_ok=True)
command=["just","test","--locked","--offline","-p","codex-hepta-agentd","-p","codex-hepta-learning-ledger","-p","codex-hepta-learning-artifacts","-p","codex-hepta-intelligence-eval","--lib","--test-threads","2","--retries","0","--no-tests","fail","--status-level","pass","--success-output","final","--failure-output","final"]
full=out/"full-native.json"
full_exit=step("full-native",v8+["/usr/bin/python3",str(repo/"scripts/hepta_ci_exec.py"),"--output",str(full),"--minimum-tests","1326","--timeout-seconds","7200","--",*command])
full_xml=out/"full-native.junit.xml"
full_collect=step("full-junit",["/usr/bin/python3",str(repo/"scripts/hepta_ci_junit.py"),"--execution",str(full),"--junit",str(junit),"--output",str(full_xml)])
coverage_ok=False
if full_exit==0 and full_collect==0:
    sys.path.insert(0,str(repo/"scripts"))
    from hepta_windows_learn_regressions import expected_groups
    from hepta_ci_junit import NoDoctypeTreeBuilder
    from hepta_c_observer_coverage import assess_retained_original_observer_coverage
    xml=ET.fromstring(full_xml.read_bytes(),parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    cases=list(xml.iter("testcase"))
    counts=collections.Counter((case.get("classname"),case.get("name")) for case in cases)
    oldxml=evidence/"native/candidate-73f20ed9a09b-shorttmp-v2/full-native.junit.xml"
    if sha(oldxml)!="0f089417bdeaeefb22a9dc61018cf093bc3fee4b2503c413190d827b9f68936b": raise RuntimeError("baseline original native JUnit changed")
    old=ET.fromstring(oldxml.read_bytes(),parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    retained=[(c.get("classname"),c.get("name")) for c in old.iter("testcase")]
    if len(retained)!=1305 or len(set(retained))!=1305: raise RuntimeError("baseline test identity inventory mismatch")
    material_prefix="cell_q24_material_receipt_owner::tests::"
    material=[
      "original_material_pair_signs_recovers_and_feeds_actual_no_update_training",
      "original_material_pair_rejects_changed_custody_prefix_and_valid_freeze_resigning",
      "original_material_pair_withdrawal_refuses_cached_material_without_dataset_claim",
      "original_material_pair_pending_claim_reopens_without_signing_or_replacing_bytes",
      "original_material_pair_expired_work_only_reads_original_completed_windows",
      "original_material_pair_partial_creation_never_finishes_missing_dataset_during_recovery"]
    selector_prefix="runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::"
    selector=[
      "q24_original_selector_attests_actual_publication_and_recovers_exact_signature",
      "q24_original_selector_refuses_withdrawn_publication_before_claim",
      "q24_original_selector_refuses_valid_training_renewal_live_and_cold",
      "q24_original_selector_preserves_pending_and_recovers_completed_lost_ack",
      "q24_original_selector_rejects_substituted_custody_before_store_creation"]
    groups={"retained_73_native_1305":retained,**expected_groups(),
            "material_original_six":[("codex-hepta-agentd",material_prefix+n) for n in material],
            "selection_original_five":[("codex-hepta-agentd",selector_prefix+n) for n in selector]}
    assessed={}
    for group,pairs in groups.items():
        rejected=[]
        for pair in pairs:
            matches=[c for c in cases if (c.get("classname"),c.get("name"))==pair]
            suites=[s.get("name") for s in xml.iter("testsuite") for c in s.findall("testcase") if (c.get("classname"),c.get("name"))==pair]
            if counts[pair]!=1 or suites!=[pair[0]] or any(c.find(tag) is not None for c in matches for tag in ["failure","error","skipped","flakyFailure","flakyError","rerunFailure","rerunError"]):
                rejected.append({"package":pair[0],"test":pair[1],"count":counts[pair],"suites":suites})
        assessed[group]={"required":len(pairs),"rejected":rejected,"passed":not rejected}
    observer=assess_retained_original_observer_coverage(full,full_xml)
    coverage_ok=all(g["passed"] for g in assessed.values()) and observer["exact_pass_coverage"]
    report["required_coverage"]={"source_sha":source,"raw_junit_sha256":sha(full_xml),"total_cases":len(cases),"groups":assessed,"observer":observer,"passed":coverage_ok}
    (out/"required-coverage.json").write_text(json.dumps(report["required_coverage"],indent=2)+"\n")
    checkpoint()

alias_exit=alias_collect=None
if full_exit==0 and full_collect==0 and coverage_ok:
    alias=evidence/"native/alias-tmp"
    if not alias.is_symlink() or alias.resolve()!=(evidence/"native/alias-target").resolve(): raise RuntimeError("original alias fixture changed")
    env["TMPDIR"]=str(alias)
    junit.unlink(missing_ok=True)
    expression="test(/^circuit_task::driver::tests::/) | test(/^circuit_task::source::tests::/) | test(/^circuit_cell::tests::causal_tests::/) | test(=circuit_cell::tests::credit_tests::signed_tests::signed_credit_rejects_cross_owner_ledger_episode_before_any_append) | test(/^learning_iteration_research_external_material::tests::/)"
    alias_record=out/"canonical-alias-native.json"
    alias_command=["just","test","--locked","--offline","-p","codex-hepta-agentd","--lib","-E",expression,"--test-threads","2","--retries","0","--no-tests","fail","--success-output","final","--failure-output","final"]
    alias_exit=step("canonical-alias-native",v8+["/usr/bin/python3",str(repo/"scripts/hepta_ci_exec.py"),"--output",str(alias_record),"--minimum-tests","23","--timeout-seconds","1800","--",*alias_command])
    alias_collect=step("canonical-alias-junit",["/usr/bin/python3",str(repo/"scripts/hepta_ci_junit.py"),"--execution",str(alias_record),"--junit",str(junit),"--output",str(out/"canonical-alias.junit.xml")])
report.update(full_exit_code=full_exit,full_collection_exit_code=full_collect,alias_exit_code=alias_exit,alias_collection_exit_code=alias_collect,source_after=git("rev-parse","HEAD"),source_status_after=git("status","--porcelain=v1","--untracked-files=all"))
report["state"]="passed" if full_exit==0 and full_collect==0 and alias_exit==0 and alias_collect==0 and coverage_ok and report["source_after"]==source and not report["source_status_after"] else "failed"
checkpoint()
raise SystemExit(0 if report["state"]=="passed" else 1)
