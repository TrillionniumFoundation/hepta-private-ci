"""Artificial recovery fixture; no experiment, checkpoint or test data access."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace

if __package__:
    from . import resume_training as r
else:
    import resume_training as r


def fake_fit(work,task,seed,mode):
    """Generate inert bytes and trace metadata, never real model parameters."""
    protocol=r.read(work/"PROTOCOL.json");name=f"{task}_s{seed}_{mode}";fit=work/"fits"/name;fit.mkdir(parents=True)
    (fit/"final.pt").write_bytes(f"artificial final {seed} {mode}".encode())
    (fit/"selected.pt").write_bytes(f"artificial selected {seed} {mode}".encode())
    r.atomic_json(fit/"DATA.json",dict(train="train",val="val",development=False))
    trace=[dict(step=i,ids=[0,1],losses={f:.1 for f in protocol["families"]},cpu=i/100,
                target_policy="read_all_warmup" if i<=128 else "actual_greedy") for i in range(1,769)]
    r.atomic_json(fit/"TRACE.json",trace);r.atomic_json(fit/"POSTERIOR_QUALIFICATION.json",{})
    identities={family:"a"*64 for family in protocol["families"]}
    r.atomic_json(fit/"SUMMARY.json",dict(task=task,seed=seed,train_mode=mode,updates=768,development=False,selected_step=768,
        validations=[dict(step=i) for i in range(0,769,128)],initial_hashes=identities,model_hashes=identities,final_hashes=identities,
        checkpoint_sha256=r.sha(fit/"selected.pt"),final_checkpoint_sha256=r.sha(fit/"final.pt")))


def selfcheck(output):
    temporary=Path(tempfile.mkdtemp(prefix="hcsn-r15-resume-fixture-e8334-"));repo=temporary/"project";repo.mkdir()
    run=repo/"results/formal_03";run.mkdir(parents=True)
    (repo/"science.py").write_text("# inert fixture source, never executed\n")
    protocol=dict(tasks=["fixture"],seeds=[1,2],modes=["light","value"],families=["ordinary","analytic"],updates=768,
                  warmup_updates=128,batch_size=2,validate_every=128,splits=dict(train=[4,0]))
    r.atomic_json(run/"PROTOCOL.json",protocol)
    r.atomic_json(run/"TRAINING_DATA_CONTEXTS.json",dict(fixture=dict(train=dict(data_sha256="train"),val=dict(data_sha256="val"))))
    r.atomic_json(run/"SOURCE_FREEZE.json",dict(files={"science.py":r.sha(repo/"science.py")},protocol_sha256=r.sha(run/"PROTOCOL.json"),
        training_data_contexts_sha256=r.sha(run/"TRAINING_DATA_CONTEXTS.json")))
    r.atomic_json(run/"RESTART_REGISTRATION.json",dict(utc=(datetime.now(timezone.utc)-timedelta(seconds=60)).isoformat()))
    fake_fit(run,"fixture",1,"light")
    receipts=run/"receipts/train";receipts.mkdir(parents=True)
    r.atomic_json(receipts/"fixture_s1_light.json",dict(name="fixture_s1_light",task="fixture",seed=1,train_mode="light",exit_code=0,
        cpu_user_seconds=1,cpu_system_seconds=.1,wall_seconds=2,maximum_rss_kib=100))
    partial=run/"fits/fixture_s1_value";partial.mkdir()
    (partial/"final.pt").write_bytes(b"original partial bytes, not a model")
    r.atomic_json(partial/"DATA.json",dict(partial=True))
    (receipts/"fixture_s1_value.json").write_bytes(b"")
    second=run/"fits/fixture_s2_light";second.mkdir();r.atomic_json(second/"DATA.json",dict(partial=True))
    for name in ("fixture_s1_light","fixture_s1_value","fixture_s2_light"):
        for stream in ("stdout","stderr"):(receipts/f"{name}.{stream}.log").write_bytes(b"")
    original=r.inspect(run,repo);protected=original["retained_successful_groups"][0]["canonical_files"]
    helper=Path(__file__).resolve()
    command_code=("import sys;from pathlib import Path;sys.path.insert(0,"+repr(str(helper.parent))+");"
                  "from resume_training_selfcheck import fake_fit;fake_fit(Path(sys.argv[1]),sys.argv[2],int(sys.argv[3]),sys.argv[4])")
    def commands(work,group):return [sys.executable,"-c",command_code,str(work),group["task"],str(group["seed"]),group["train_mode"]]
    result=r.run_attempt(run,workers=2,repo=repo,command_factory=commands)
    r.check_files(run,protected)
    preserved=r.read(run/"attempts/train_02_enospc/PRESERVATION.json")
    total=r.read(receipts/"TOTAL.json")
    attempts=run/"attempts/train_resume_001/jobs"
    rows=[r.read(path) for path in attempts.glob("*/RECEIPT.json")]
    promotions=[r.read(path) for path in attempts.glob("*/PROMOTION.json")]
    checks=dict(retained_original_success_unchanged=True,
        original_classification=len(original["retained_successful_groups"])==1 and len(original["pending_groups"])==3,
        complete_original_budget=result["completed"] and result["complete_groups"]==4,
        byte_zero_receipt_preserved=(run/"attempts/train_02_enospc/original/receipts/train/fixture_s1_value.json").read_bytes()==b"",
        partial_final_preserved=(run/"attempts/train_02_enospc/original/fits/fixture_s1_value/final.pt").read_bytes()==b"original partial bytes, not a model",
        unknown_attempts_not_zero=len(preserved["original_process_attempts"])==2 and all(x["cpu_seconds"] is None and x["measurement_status"]=="not_measured" for x in preserved["original_process_attempts"]),
        wait4_cpu_measured=len(rows)==3 and all(x["cpu_user_seconds"]+x["cpu_system_seconds"]>0 and x["exit_code"]==0 for x in rows),
        canonical_receipts_exact_alias=all(r.sha(run/x["canonical_receipt"])==x["receipt_sha256"]==r.sha(attempts/x["name"]/"RECEIPT.json") for x in promotions),
        registrations_copied_exactly=all(r.sha(run/name)==r.sha(job/"work"/name) for job in attempts.iterdir() for name in r.REGISTRATIONS),
        consolidated_cpu_disjoint=abs(total["process_cpu_seconds"]-(1.1+sum(x["cpu_user_seconds"]+x["cpu_system_seconds"] for x in rows)))<1e-10,
        interrupted_wall_label=total["wall_scope"]==r.WALL_SCOPE and total["wall_seconds"]>=60 and total["original_launcher_completed"] is False,
        partial_final_comparison_only=any(x["prior_partial_final_comparison"].get("byte_identical") is False for x in promotions))
    signals=[];events=temporary/"guard_events.jsonl"
    own=dict(process=SimpleNamespace(pid=12345),process_attempt_id="fixture/owned",paused=False,pause_seconds=0.)
    sender=lambda pid,sig:signals.append((pid,sig))
    r.disk_guard([own],0,1,2,events,sender);r.disk_guard([own],1,1,2,events,sender);r.disk_guard([own],2,1,2,events,sender)
    checks["disk_guard_only_owned_pid_and_hysteresis"]=signals==[(12345,signal.SIGSTOP),(12345,signal.SIGCONT)] and own["pause_seconds"]>=0
    # A complete fit cannot be accepted with a shortened trace or wrong bytes.
    fit=run/"fits/fixture_s2_value";trace=r.read(fit/"TRACE.json");(fit/"TRACE.json").write_text(json.dumps(trace[:-1]))
    try:r.fit_validation(fit,"fixture",2,"value",protocol,r.read(run/"TRAINING_DATA_CONTEXTS.json"))
    except ValueError:checks["incomplete_update_trace_rejected"]=True
    else:checks["incomplete_update_trace_rejected"]=False
    (fit/"TRACE.json").write_text(json.dumps(trace));(fit/"final.pt").write_bytes(b"tampered")
    try:r.fit_validation(fit,"fixture",2,"value",protocol,r.read(run/"TRAINING_DATA_CONTEXTS.json"))
    except ValueError:checks["checkpoint_hash_mismatch_rejected"]=True
    else:checks["checkpoint_hash_mismatch_rejected"]=False
    report=dict(schema="hcsn.r15.training-resume.fixture.v1",source_sha256=r.sha(r.SOURCE),fixture_helper_sha256=r.sha(helper),fixture_root=str(temporary),
        real_training_or_test_accessed=False,checks=checks,passed=all(checks.values()))
    r.atomic_json(output,report);r.require(report["passed"],"Recovery fixture failed")
    return report
