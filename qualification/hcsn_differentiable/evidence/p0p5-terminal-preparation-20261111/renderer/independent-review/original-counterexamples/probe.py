"""Independent pure-JSON contract probes; does not render, load Matplotlib or read actual C2."""
import copy,hashlib,json,pathlib,sys
SOURCE=pathlib.Path(sys.argv[1]).resolve();OUT=pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0,str(SOURCE))
import input_contract as contract
import native_analysis_envelope as gate
OUT.mkdir(exist_ok=False)
def raw(obj):return (json.dumps(obj,indent=2,sort_keys=True)+"\n").encode()
def identity(data):return {"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
def fixture():
    auth_id={"bytes":1,"sha256":"a"*64};binding_id={"bytes":1,"sha256":"b"*64}
    ids={key:{"bytes":1,"sha256":str(i)*64} for i,key in enumerate(("core_receipt","RESULT","ZIP"),1)}
    sha=gate.SOURCES["complete_os_envelope.py"]["sha256"]
    auth={"analysis_supervisor_source_sha256":sha}
    before={"observer_pid":200,"core_pid":None,"core_pgid":None,"records":[{"pid":200}],
        "same_group_pids":[],"tracked_live_descendants":[],"adopted_children":[],"scan_errors":[],
        "observed_monotonic":9.9}
    after=dict(copy.deepcopy(before),core_pid=201,core_pgid=201,records=[{"pid":201,"observed_absent":True}],observed_monotonic=11.1)
    outer={"schema":"c2-resource-analysis-complete-os-envelope-v1","status":"completed","process_started":True,
        "returncode":0,"timed_out":False,"child_terminal_unknown":False,"unreaped_descendants":False,
        "direct_child_CPU_complete":True,"total_attempt_CPU_unknown_or_lower_bound":False,
        "adopted_child_wait4":[],"cleanup_errors":[],"limits":gate.LIMITS,"whole_child_wall_seconds":1.,
        "wait4_child_CPU_seconds":.3,"wait4_peak_RSS_bytes":1000,"sampled_peak_RSS_bytes":1000,
        "program_manifest_sha256":contract.PROGRAM,"source_inputs_unchanged":True,"supervisor_source_sha256":sha,
        "supervisor_source_sha256_before":sha,"supervisor_source_sha256_after":sha,"artifacts":ids,
        "process_observations":{"subreaper_enabled":True,"unreadable":[],"before_start":before,
            "after_direct_wait4":after,"after_cleanup":dict(copy.deepcopy(after),observed_monotonic=11.2),
            "tracked_identities":[{"pid":201}]},
        "process_gate_passed":True,"popen_started_monotonic":10.,"wait4_completed_monotonic":11.,
        "supervisor_main_wall_prefix_seconds":3.,"metadata_finalization_wall_prefix_seconds":.3,
        "supervisor_peak_RSS_bytes":1000,"supervisor_CPU_prefix_seconds":.05,
        "argv":["/synthetic/python","-B","/synthetic/core/launch_analysis.py"]}
    core={"schema":"c2-resource-analysis-launch-v1","status":"completed","process_started":True,
        "spawn_attempted":True,"returncode":0,"archive_finalized":True,"child_CPU_complete":True,
        "CPU_unknown_or_lower_bound":False,"child_terminal_unknown":False,"whole_hard_wall_seconds":120,
        "peak_RSS_limit_bytes":contract.RSS,"workers":1,"threads":1,"whole_wall_seconds":.8,
        "exact_waited_child_CPU_seconds":.1,"own_process_CPU_sample_seconds":.05,
        "sampled_child_peak_RSS_bytes":1000,"exact_waited_child_peak_RSS_bytes":1000,"own_peak_RSS_bytes":1000,
        "archive":ids["ZIP"],"RESULT":ids["RESULT"],"members":5,"CRC_all_members_manifest_verified":True,
        "authorization":auth_id,"binding":binding_id,"result_status":"completed_metadata"}
    result={"authorization_identity":auth_id,"binding_identity":binding_id,"execution_status":"completed_metadata"}
    gnu={"printed_whole_wall_seconds":5.,"conservative_wall_upper_seconds":5.01,"printed_CPU_sum_seconds":1.}
    return {"outer":outer,"core":core,"result":result,"auth":auth,"ids":ids,"members":{str(i):None for i in range(5)},"gnu":gnu}
def run(name,mutation):
    value=fixture()
    if mutation=="finalization":value["outer"]["metadata_finalization_wall_prefix_seconds"]=29.
    if mutation=="worker_CPU":value["core"]["exact_waited_child_CPU_seconds"]=500.
    if mutation=="wrong_argv":value["outer"]["argv"]=["/synthetic/unrelated.py"]
    if mutation=="unknown":value["outer"]["total_attempt_CPU_unknown_or_lower_bound"]=True
    try:
        contract.envelopes(value["outer"],value["core"],value["result"],value["auth"],value["ids"],value["members"])
        returned=gate.accounting(value["outer"],value["core"],value["gnu"])
        accepted=True;error=None
    except Exception as exc:
        accepted=False;returned=None;error={"type":type(exc).__name__,"message":str(exc)}
    data=raw(value);(OUT/(name+"-INPUT.json")).write_bytes(data)
    return {"name":name,"mutation":mutation,"accepted_by_envelopes_and_accounting":accepted,
        "error":error,"returned":returned,"input":identity(data),
        "scope":"Direct actual metadata contract/accounting functions only; not the full raw-file authorize/load/verify_native path. All objects are explicit synthetic fixtures."}
rows=[run("positive_control",None),run("finalization_beyond_native_whole","finalization"),
    run("worker_CPU_beyond_complete_parent_CPU","worker_CPU"),run("unrelated_core_argv","wrong_argv"),
    run("unknown_CPU_negative_control","unknown")]
assert rows[0]["accepted_by_envelopes_and_accounting"]
assert all(r["accepted_by_envelopes_and_accounting"] for r in rows[1:4])
assert not rows[4]["accepted_by_envelopes_and_accounting"]
assert "matplotlib" not in sys.modules
report={"schema":"renderer-native155-independent-partial-contract-counterexamples-v1","cases":rows,
    "actual_analysis_model_E_native_render_execution":False,"Matplotlib_imported":False,
    "qualification":"None; prospective contract gaps, not claims about actual production records.",
    "static_full_consumer_scope":"verify_native calls accounting and does not otherwise compare finalization+child wall to GNU whole, inner CPU to outer wait4, or outer.argv to expected core argv."}
(OUT/"COUNTEREXAMPLES.json").write_bytes(raw(report))
print(json.dumps({"cases":len(rows),"positive":1,"cost_counterexamples_reproduced":2,
    "argv_noninspection_subpath_probe":1,"unknown_rejection":1,"Matplotlib_imported":False}))

