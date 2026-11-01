"""Native protocol qualification against frozen Python numerical replay frames.

The Rust owner does not evaluate the CTMC or choose neural actions. It owns
durable replay cursors, outbox/inbox, time and charges; the separate service
performs actual persistent metering effects. This is engineering fault replay.
"""

import argparse
import gzip
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ..addressed_decision_r15_20261101.execution import price
from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..cold_recovery_r17_20261101.runtime import Session, canonical, digest
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import execute


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def fnv(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) % 2**64
    return value


def seal(body):
    return body + f"CHECK\t{fnv(body.encode()):016x}\n"


def read_sealed(path):
    text = path.read_text()
    body, check = text.rsplit("CHECK\t", 1)
    assert check == f"{fnv(body.encode()):016x}\n"
    return body.splitlines()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def total_fee(state):
    return sum(q["fee"] for q in state["queries"]) + (state["current"]["fee"] if state["current"] else 0.)


def job_frames(config, destination):
    session = Session(config)
    state = session.initial()
    original = execute(session.law, session.episode, policy=config["policy"], pattern=config["pattern"],
                       representation=config["representation"])
    state_hex = canonical(state).encode().hex()
    lines = [f"RUN\t{digest(config)}\t{state_hex}\n"]
    sequence, expected_provider_count, provider_fee = 0, 0, 0
    while state["status"] != "done":
        before_hex = state_hex
        old_clock, old_fee = state["memory"]["clock"], total_fee(state)
        event = session.advance(state)
        state_hex = canonical(state).encode().hex()
        elapsed = round((state["memory"]["clock"] - old_clock) * 1e9)
        fee = round((total_fee(state) - old_fee) * 1e6)
        assert elapsed >= 0 and fee >= 0
        assert abs(elapsed / 1e9 - (state["memory"]["clock"] - old_clock)) < 1e-12
        assert abs(fee / 1e6 - (total_fee(state) - old_fee)) < 1e-12
        pending = state["pending"]
        opid = pending["id"] if pending else "-"
        token = pending.get("token", -1) if pending else -1
        token = -1 if token is None else token
        remote_fee = 0
        if event in ("received:READ", "received:REFRESH"):
            scale = price(session.episode.seed, state["query"])
            remote_fee = round((.025 if event == "received:READ" else .07) * scale * 1e6)
            expected_provider_count += 1
            provider_fee += remote_fee
        lines.append(f"FRAME\t{sequence}\t{event}\t{opid}\t{token}\t{elapsed}\t{fee}\t{remote_fee}\t{fnv(before_hex.encode()):016x}\t{state_hex}\n")
        sequence += 1
    assert state["queries"] == original["queries"]
    text = seal("".join(lines))
    with destination.open("x") as stream:
        stream.write(text)
    return dict(run=digest(config), frames=sequence, final_state=state,
        clock_ns=round(state["memory"]["clock"]*1e9), fee_micros=round(total_fee(state)*1e6),
        provider_count=expected_provider_count, provider_fee_micros=provider_fee,
        job_sha256=hashlib.sha256(text.encode()).hexdigest())


class Meter:
    def __init__(self, output, binary):
        self.output, self.binary, self.receipts = output, binary, []

    def start(self, label, role, job, state, sock, stage="none", marker=None):
        stdout = (self.output / f"{label}.stdout").open("xb")
        stderr = (self.output / f"{label}.stderr").open("xb")
        args = [str(self.binary), role, str(job), str(state), str(sock), stage,
                str(marker or self.output / f"{label}.marker")]
        process = subprocess.Popen(args, stdout=stdout, stderr=stderr)
        return dict(process=process, label=label, command=args, stdout=stdout,
                    stderr=stderr, started=time.perf_counter())

    def wait(self, item, kill=False):
        process = item["process"]
        if kill:
            os.kill(process.pid, signal.SIGKILL)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
        item["stdout"].close()
        item["stderr"].close()
        receipt = dict(label=item["label"], command=item["command"], pid=process.pid,
            exit_code=process.returncode, cpu_seconds=usage.ru_utime+usage.ru_stime,
            max_rss_kib=usage.ru_maxrss, wall_seconds=time.perf_counter()-item["started"])
        save(self.output / f"{item['label']}.process.json", receipt)
        self.receipts.append(receipt)
        return receipt


def await_file(path, process, seconds=10):
    deadline = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(str(path))
        # Do not poll the child with Popen.poll(): wait4 owns complete metering.
        time.sleep(.005)


REQUEST = 1000000


def rpc(mailbox, *fields):
    global REQUEST
    REQUEST += 1
    identifier = f"{os.getpid()}-{REQUEST:010d}"
    request = "\t".join(map(str, fields))
    body = seal(f"REQ\t{identifier}\t{request.encode().hex()}\n")
    temporary = mailbox / f"{identifier}.tmp"
    with temporary.open("x") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.rename(mailbox / f"{identifier}.req")
    response = mailbox / f"{identifier}.resp"
    await_file(response, None, seconds=5)
    row = read_sealed(response)[0].split("\t")
    assert row[:2] == ["RESP", identifier]
    response.unlink()
    return bytes.fromhex(row[2]).decode()


def await_provider(mailbox, process):
    deadline = time.monotonic() + 10
    while not (mailbox / "READY").exists() or (mailbox / "READY").read_text().strip() != str(process.pid):
        if time.monotonic() > deadline:
            raise TimeoutError("provider readiness")
        time.sleep(.005)


def verify_case(directory, expected):
    owner = read_sealed(directory / "owner.state")
    provider = read_sealed(directory / "provider.state")
    header = owner[0].split("\t")
    phead = provider[0].split("\t")
    actual_state = json.loads(bytes.fromhex(owner[1].split("\t")[1]))
    assert actual_state == expected["final_state"]
    assert int(header[4]) == expected["frames"]
    assert int(header[5]) == expected["clock_ns"]
    assert int(header[6]) == expected["fee_micros"]
    assert int(phead[4]) == expected["provider_count"]
    assert int(phead[5]) == expected["provider_fee_micros"]
    effects = [line for line in provider[1:] if line.startswith("EFFECT\t")]
    assert owner[2:] == effects
    assert len({row.split("\t")[2] for row in effects}) == len(effects)
    return effects


def run(output, binary):
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text())
    for relative, sha in manifest["files"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == sha, relative
    owner_law = Law(tuple(protocol["world_theta"]))
    checks, all_receipts, sample_effects, negatives = [], [], None, {}
    with tempfile.TemporaryDirectory(prefix="h18-") as socket_directory:
        sock = Path(socket_directory) / "s"
        for fit in protocol["fits"]:
            training = json.loads(gzip.decompress((ROOT / protocol["training_pattern"].format(fit=fit)).read_bytes()))
            law = BlockLaw.from_payload(training["calibration"]["models"]["hx"]["payload"])
            for domain in protocol["domains"]:
                episode = make_episode(owner_law, protocol["seed"]+(domain=="ood"), domain)
                for representation in protocol["representations"]:
                    for policy, pattern in protocol["policies"]:
                        name = f"{fit}_{domain}_{representation}_{policy}_{pattern}"
                        folder = output / name
                        folder.mkdir()
                        config = dict(model=law.export(),owner_model=owner_law.export(),seed=episode.seed,
                            domain=domain,owner_fingerprint=episode.fingerprint,
                            representation=representation,policy=policy,pattern=pattern)
                        job = folder / "job.tsv"
                        expected = job_frames(config, job)
                        save(folder / "EXPECTED.json", expected)
                        modes = protocol["owner_faults"]+["provider_committed", "stale_owner"]
                        if not checks:
                            modes += ["provider_storage_error"]
                        for mode in modes:
                            case = folder / mode
                            case.mkdir()
                            meter = Meter(case, binary)
                            ps, own = case / "provider.state", case / "owner.state"
                            marker = case / "fault.marker"
                            provider = meter.start("provider1", "provider", job, ps, sock,
                                mode if mode in ("provider_committed", "provider_storage_error") else "none", marker)
                            await_provider(sock, provider["process"])
                            if mode=="stale_owner":
                                old = meter.start("old", "owner", job, own, sock, "owner_leased", marker)
                                await_file(marker, old["process"])
                                fresh = meter.start("fresh", "owner", job, own, sock)
                                assert meter.wait(fresh)["exit_code"] == 0
                                marker.with_suffix(".release").write_text("release\n")
                                assert meter.wait(old)["exit_code"] == 2
                            else:
                                first = meter.start("owner1", "owner", job, own, sock,
                                    mode if mode not in ("provider_committed", "provider_storage_error") else "none", marker)
                                if mode != "provider_storage_error":
                                    await_file(marker, first["process"])
                                if mode in ("provider_committed", "provider_storage_error"):
                                    assert meter.wait(provider,kill=mode=="provider_committed")["exit_code"] == (-9 if mode=="provider_committed" else 2)
                                    assert meter.wait(first)["exit_code"] == 2
                                    if mode == "provider_storage_error":
                                        failed_header = read_sealed(ps)[0].split("\t")
                                        negatives["persist_failure_fail_stop_no_ack"] = int(failed_header[4]) == 0
                                        assert "No space left on device" in (case / "provider1.stderr").read_text()
                                    provider = meter.start("provider2", "provider", job, ps, sock)
                                    await_provider(sock, provider["process"])
                                else:
                                    assert meter.wait(first,kill=True)["exit_code"] == -9
                                second = meter.start("owner2", "owner", job, own, sock)
                                assert meter.wait(second)["exit_code"] == 0
                            effects = verify_case(case,expected)
                            if sample_effects is None:
                                sample_effects = effects
                                generation=int(read_sealed(ps)[0].split("\t")[3])
                                first_effect=effects[0].split("\t")
                                negatives["stale_generation"]=rpc(sock,"CHECK",expected["run"],generation-1).startswith("ERR")
                                negatives["wrong_run"]=rpc(sock,"CHECK","0"*64,generation).startswith("ERR")
                                negatives["unknown_operation"]=rpc(sock,"CALL",expected["run"],generation,"unknown","READ",25000).startswith("ERR")
                                negatives["altered_duplicate"]=rpc(sock,"CALL",expected["run"],generation,first_effect[2],first_effect[3],int(first_effect[5])+1).startswith("ERR")
                                replay=rpc(sock,"CALL",expected["run"],generation,first_effect[2],first_effect[3],first_effect[5])
                                negatives["duplicate_returns_exact_receipt"]=replay==effects[0]
                                assert verify_case(case,expected)==effects
                            assert meter.wait(provider,kill=True)["exit_code"] == -9
                            shutil.rmtree(sock)
                            all_receipts += meter.receipts
                            checks.append(dict(case=f"{name}/{mode}",mode=mode,exact_numeric_state=True,
                                provider_count=expected["provider_count"],provider_fee_micros=expected["provider_fee_micros"]))
    assert all(negatives.values())
    summary=dict(schema="hcsn-native-r18-stateful-replay-v1",scope=protocol["scope"],checks=checks,
        cases=len(checks),negative_checks=negatives,all_passed=True,
        native_processes=len(all_receipts),complete_child_cpu_seconds=sum(p["cpu_seconds"] for p in all_receipts),
        max_child_rss_kib=max(p["max_rss_kib"] for p in all_receipts),
        source_manifest_sha256=hashlib.sha256((HERE/"SOURCE_MANIFEST.json").read_bytes()).hexdigest(),
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),production_activation=False)
    save(output/"SUMMARY.json",summary)
    save(output/"EFFECT_RECEIPT_SAMPLE.json",dict(lines=sample_effects,
        format="EFFECT\\trunsha\\topid\\tREAD|REFRESH\\ttoken\\tfee_micros\\tprovider_effect_index; newline terminates canonical receipt"))
    print(canonical({k:v for k,v in summary.items() if k!="checks"}),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--binary",type=Path,required=True)
    args=parser.parse_args()
    run(args.output.resolve(),args.binary.resolve())
