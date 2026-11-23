"""Operate a subsequent consenting B use from the original protected paired intake."""

import argparse
from contextlib import closing, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

from . import adoption, data, paired_cold, paired_consumer_run as cold
from . import paired_intake as intake, paired_source

require = intake.require
field = intake.digest_field


def put(path, value):
    paired_source._publish_bytes(path, data.canonical(value) + b"\n")


def context(home, admission):
    field(admission)
    with closing(intake.open_database(home)) as db:
        row = db.execute("SELECT binding,request_sha,state FROM admissions WHERE id=?", (admission,)).fetchone()
        require(row is not None and row[2] == "released", "original published admission required")
        cfg = json.loads(db.execute("SELECT value FROM settings").fetchone()[0])
    binding = json.loads(row[0])
    release = binding["release"]
    require(data.digest(binding) == admission and release["request_sha256"] == row[1]
            and release["scope"] == cfg["scope"] and release["study_sha256"] == cfg["study"]
            and release["freeze_sha256"] == cfg["freeze"] and binding["anchor"] == cfg["anchor"]
            and intake.witness(cfg, "freeze") == binding["anchor"]
            and binding["native_sha256"] == cfg["native_sha256"], "admission or issuer binding changed")
    arrival = binding["arrival"]
    require(intake.witness(cfg, field(arrival["arrival_id"])) == arrival
            and binding["native"]["use"] == "evaluate_only"
            and binding["native"]["delivery_id"] == arrival["consent_delivery_id"]
            and binding["native"]["study_principal_sha256"] == arrival["study_principal_sha256"],
            "original B or source arrival differs")
    if cfg["scope"] == "owner_intake":
        require("enrollment" in binding, "original A and B enrollment required")
        for role, name in (("a", "training-person"), ("b", "person-" + arrival["arrival_id"])):
            person = intake.witness(cfg, name)
            require(data.digest(person) == binding["enrollment"][role + "_enrollment_sha256"],
                    "enrollment witness differs")
            with intake.owner_file(cfg, "enrollment-" + field(person["enrollment_receipt_sha256"]) + ".bin") as stream:
                require(hashlib.file_digest(stream, "sha256").hexdigest() == person["enrollment_receipt_sha256"],
                        "original site enrollment material differs")
    directory = home / admission
    require(adoption.read_json(directory / "release.json") == dict(release, admission_sha256=admission),
            "published release differs")
    req = paired_cold.checked_request(directory / "paired.json", row[1])
    require(data.digest(req["candidate"]) == release["candidate_sha256"], "released candidate differs")
    if cfg["scope"] == "owner_intake":
        require("paired_source_exposure" in req["candidate"]
                and field(release["source_retention_sha256"]) == binding["anchor"]["source_retention_sha256"],
                "qualified original source training required")
    return cfg, binding, req


@contextmanager
def locked(directory):
    directory.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(directory, os.O_NOFOLLOW | os.O_DIRECTORY | os.O_RDONLY)
    try:
        info = os.fstat(fd)
        require(info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0, "private owner directory required")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def request_scope(admission, release, task, selection):
    base = dict(pair=field(release["request_sha256"]), candidate=field(release["candidate_sha256"]), task=field(task))
    op = data.digest(["hepta.paired-learning.subsequent-operation.v1", admission, field(selection), base])
    return dict(use="request_consumer_run", operation=op, **base)


def outcome_scope(request, receipt, effect, outcome):
    require(outcome in ("accepted", "rejected"), "an explicit B decision is required")
    return dict(request, use="report_consumer_outcome", run_receipt=data.digest(receipt),
                output=field(receipt["output_sha256"]), effect=field(effect), outcome=outcome)


def native(cfg, binding, scope, delivery, launch):
    for fd in (3, 4):
        os.fstat(fd)
    field(delivery)
    require(delivery != binding["native"]["delivery_id"], "evaluation delivery cannot authorize subsequent use")
    base = dict(study_sha256=cfg["study"], scope=scope)
    principal = field(binding["native"]["study_principal_sha256"])
    with open(cfg["native"], "rb") as binary:
        require(hashlib.file_digest(binary, "sha256").hexdigest() == cfg["native_sha256"], "native executable changed")
        fd = binary.fileno()
        def invoke(args, payload, fds):
            completed = subprocess.run([f"/proc/self/fd/{fd}", *map(str, args)],
                                       input=data.canonical(payload), stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, env={"PATH": os.defpath, "LANG": "C"},
                                       pass_fds=(*fds, fd), timeout=30)
            require(completed.returncode == 0 and 0 < len(completed.stdout) <= 32768,
                    "original native statement or live Root event unavailable")
            return completed.stdout
        statement = invoke(["--print-statement"], base, ())
        answer = json.loads(invoke(launch, dict(base, delivery_id=delivery), (3, 4)))
    expected = dict(schema="hepta.paired-learning.consumer-statement-readback.v1",
                    study_sha256=cfg["study"], delivery_id=delivery, use=scope["use"],
                    statement_sha256=intake.sha(statement), study_principal_sha256=principal)
    require(answer == expected, "live statement, original B, or delivery differs")
    return answer


def private_material(cfg, basename, limit):
    with intake.owner_file(cfg, basename) as stream:
        raw = stream.read(limit + 1)
    require(0 < len(raw) <= limit, "original private material missing or oversized")
    return raw


def read_run(path, scope, selection, req, materials):
    run = adoption.read_json(path / "RUN.json")
    started = adoption.read_json(path / "STARTED.json")
    payload = adoption.read_json(path / "worker-input.json")
    wire = adoption.read_json(path / "worker-output.json")
    pred = wire["prediction"]
    task = payload["task"]
    require(payload["model"] == req["candidate"] and payload["candidate"] == scope["candidate"]
            and data.digest(task) == scope["task"] and wire["nonce"] == started["nonce"] == payload["nonce"]
            and started["request"] == scope and started["local_selection_sha256"] == selection,
            "retained worker input, selection or nonce differs")
    output = cold.inspect(req, task, materials, pred)
    require((path / "answer.utf8").read_bytes() == output, "original delivered bytes differ")
    expected = dict(schema="hepta.paired-learning.consumer-run.v1", request=scope,
                    nonce=field(started["nonce"]), selection_sha256=selection,
                    grant_sha256=data.digest(started["grant"]), prediction_sha256=data.digest(wire),
                    local_child_pid=pred["pid"], output_sha256=intake.sha(output))
    require(run == expected, "retained local process receipt differs")
    return run


def execute(path, cfg, req, scope, selection, grant, materials):
    if (path / "RUN.json").exists():
        require(adoption.read_json(path / "STARTED.json")["grant"] == grant, "different run authorization")
        return read_run(path, scope, selection, req, materials)
    require(not (path / "STARTED.json").exists(), "prior execution uncertain; keep original for reconciliation")
    raw = private_material(cfg, "consumer-task-" + scope["task"] + ".json", data.MAX_RECORD_BYTES)
    task = data._parse(raw)
    require(data.digest(task) == scope["task"], "subsequent task bytes differ from B's statement")
    _, _, input_ids = cold.encoding(req, task, materials)
    reservation = dict(operation=scope["operation"])
    put(path.parent / ("tokens-" + data.digest(input_ids) + ".json"), reservation)
    put(path.parent / ("request-delivery-" + field(grant["delivery_id"]) + ".json"), reservation)
    nonce = secrets.token_hex(32)
    # A torn run stays spent: B authorized one use. No second generation on restart.
    put(path / "STARTED.json", dict(request=scope, nonce=nonce, grant=grant, local_selection_sha256=selection))
    put(path / "worker-input.json", dict(task=task, nonce=nonce, candidate=scope["candidate"], model=req["candidate"]))
    with (path / "worker.log").open("xb") as log:
        with subprocess.Popen([sys.executable, "-m", "cell_experiments.paired_consumer_run", str(materials), str(path)],
                              stdout=log, stderr=log, env={**os.environ, **cold.OFFLINE}) as proc:
            try:
                status = proc.wait(timeout=req["timeout_seconds"])
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
            require(status == 0, "local inference did not complete")
    wire = adoption.read_json(path / "worker-output.json")
    pred = wire["prediction"]
    require(wire["nonce"] == nonce and pred["pid"] == proc.pid, "original nonce or observed child differs")
    answer = cold.inspect(req, task, materials, pred)
    paired_source._publish_bytes(path / "answer.utf8", answer)
    run = dict(schema="hepta.paired-learning.consumer-run.v1", request=scope, nonce=nonce,
               selection_sha256=selection, grant_sha256=data.digest(grant), prediction_sha256=data.digest(wire),
               local_child_pid=proc.pid, output_sha256=intake.sha(answer))
    put(path / "RUN.json", run)
    return read_run(path, scope, selection, req, materials)


def operate(a):
    cfg, binding, req = context(a.home, a.admission)
    folder = a.home / a.admission / "consumer"
    release = binding["release"]
    pair = release["request_sha256"]
    with locked(folder):
        selected = cold.selection(folder, pair, req, a.materials, create=a.cmd == "select")
        if a.cmd == "select":
            return dict(pair=pair, candidate=release["candidate_sha256"], selection_sha256=selected)
        scope = request_scope(a.admission, release, a.task, selected)
        path = folder / scope["operation"]
        if a.cmd == "request-scope":
            return dict(study_sha256=cfg["study"], scope=scope)
        if a.cmd == "run":
            grant = native(cfg, binding, scope, a.delivery, (a.root_pid, a.sqlite_home, a.route))
            path.mkdir(mode=0o700, exist_ok=True)
            run = execute(path, cfg, req, scope, selected, grant, a.materials)
            return dict(operation=scope["operation"], run_receipt=data.digest(run), output=run["output_sha256"])
        run = read_run(path, scope, selected, req, a.materials)
        started = adoption.read_json(path / "STARTED.json")
        if a.cmd == "verify-request":
            grant = native(cfg, binding, scope, started["grant"]["delivery_id"], (a.root_pid, a.sqlite_home, a.route))
            require(grant == started["grant"], "original run grant differs")
            return dict(verified_request=data.digest(grant), run_receipt=data.digest(run))
        if a.cmd == "verify":
            final = adoption.read_json(path / "OUTCOME.json")
            effect, decision, delivery = final["scope"]["effect"], final["scope"]["outcome"], final["grant"]["delivery_id"]
        else:
            effect, decision = a.effect, a.outcome
            delivery = getattr(a, "delivery", None)
        statement = outcome_scope(scope, run, effect, decision)
        if a.cmd == "outcome-scope":
            return dict(study_sha256=cfg["study"], scope=statement)
        require(delivery != started["grant"]["delivery_id"], "request delivery reused for outcome")
        grant = native(cfg, binding, statement, delivery, (a.root_pid, a.sqlite_home, a.route))
        raw = private_material(cfg, "consumer-effect-" + statement["effect"] + ".bin", 16 * 1024 * 1024)
        require(intake.sha(raw) == statement["effect"], "original outcome material differs")
        record = dict(scope=statement, grant=grant, evidence_scope=cfg["scope"],
                      execution="observed_local_cold_process", outcome_evidence="participant_report",
                      independently_verified_business_effect=False, payment_authorized=False)
        if a.cmd == "report":
            # First signed decision is immutable; contradictions require a separate adjudication.
            if (path / "OUTCOME.json").exists():
                require(adoption.read_json(path / "OUTCOME.json") == record, "original outcome is immutable")
            paired_source._publish_bytes(path / "effect.bin", raw)
            put(path / "OUTCOME.json", record)
        else:
            require((path / "effect.bin").read_bytes() == raw, "retained original effect bytes differ")
            require(final == record, "retained outcome differs from live original")
        return dict(operation=scope["operation"], receipt_sha256=data.digest(record), **record)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("home", type=Path)
    p.add_argument("admission")
    p.add_argument("materials", type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)
    for command in ("select", "request-scope", "run", "outcome-scope", "report", "verify-request", "verify"):
        c = sub.add_parser(command)
        if command != "select":
            c.add_argument("task")
        if command in ("outcome-scope", "report"):
            c.add_argument("effect")
            c.add_argument("outcome", choices=("accepted", "rejected"))
        if command in ("run", "report"):
            c.add_argument("delivery")
        if command in ("run", "report", "verify-request", "verify"):
            c.add_argument("root_pid")
            c.add_argument("sqlite_home")
            c.add_argument("route")
    a = p.parse_args()
    if a.cmd in ("run", "report", "verify-request", "verify"):
        for fd in (3, 4):
            os.fstat(fd)
    print(data.canonical(operate(a)).decode())


if __name__ == "__main__":
    main()
