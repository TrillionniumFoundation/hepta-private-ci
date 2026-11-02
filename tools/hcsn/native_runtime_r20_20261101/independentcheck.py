"""Linux process-death replay against independent matrix algebra, not owner code."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time

import numpy as np
from scipy.linalg import expm

from tools.hcsn.addressed_decision_r15_20261101.law import Law, default_free_raw

HERE = Path(__file__).resolve().parent
SCHEDULES = (("none", "none"), ("owner_initialized", "none"),
             ("owner_prepared:1", "none"), ("owner_received:1", "none"),
             ("owner_computed:1", "none"), ("owner_committed:1", "none"),
             ("owner_committed:2", "none"), ("none", "provider_effect_committed:1"),
             ("owner_received:1", "provider_reply_published:1"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fnv(data):
    value = 0xCBF29CE484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001B3) % 2**64
    return value


def seal(text):
    return text + f"CHECK\t{fnv(text.encode()):016x}\n"


def unseal(data):
    text = data.decode() if isinstance(data, bytes) else data
    body, check = text.rsplit("CHECK\t", 1)
    if check != f"{fnv(body.encode()):016x}\n":
        raise ValueError("checksum mismatch")
    return body


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def wait_path(path):
    deadline = time.monotonic() + 8
    while not path.exists():
        if time.monotonic() > deadline:
            raise TimeoutError(str(path))
        time.sleep(.002)


def identify(binary, model, label="MODEL_IDENTIFY"):
    started = time.monotonic()
    out = model.with_name(label + ".stdout").open("xb")
    err = model.with_name(label + ".stderr").open("xb")
    args = [str(binary), "identify", str(model)]
    child = subprocess.Popen(args, stdout=out, stderr=err)
    _, status, use = os.wait4(child.pid, 0)
    child.returncode = os.waitstatus_to_exitcode(status)
    out.close()
    err.close()
    token = model.with_name(label + ".stdout").read_text().strip()
    save(model.with_name(label + ".json"), dict(command=args, model_sha256=digest(model.read_bytes()),
         binary_sha256=digest(binary.read_bytes()), exit_code=child.returncode, observed_model_id=token,
         child_cpu_seconds=use.ru_utime + use.ru_stime, wall_seconds=time.monotonic() - started))
    assert child.returncode == 0 and len(token) == 16 and all(c in "0123456789abcdef" for c in token)
    return token


class Processes:
    def __init__(self):
        self.active, self.records = {}, []

    def start(self, binary, role, paths, fault, label):
        directory = paths["directory"]
        args = [str(binary), role, str(directory / "MODEL"), str(directory / "PLAN")]
        if role == "provider":
            args += [str(directory / "CATALOG"), str(directory / "provider.state")]
        else:
            args.append(str(directory / "owner.state"))
        args += [str(directory / "ENDPOINT"), fault, str(directory / (label + ".marker"))]
        out, err = (directory / (label + ".stdout")).open("xb"), (directory / (label + ".stderr")).open("xb")
        process = subprocess.Popen(args, stdout=out, stderr=err)
        item = dict(process=process, args=args, out=out, err=err, started=time.monotonic(),
                    directory=directory, label=label)
        self.active[process.pid] = item
        return item

    def wait(self, item, kill=False):
        process = item["process"]
        if kill:
            os.kill(process.pid, signal.SIGKILL)
        deadline = time.monotonic() + 9
        while True:
            observation = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
            if observation is not None:
                break
            if time.monotonic() > deadline:
                os.kill(process.pid, signal.SIGKILL)
                kill = True
            time.sleep(.002)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
        item["out"].close()
        item["err"].close()
        row = dict(command=item["args"], label=item["label"], pid=process.pid,
                   exit_code=process.returncode, killed=kill, child_cpu_seconds=usage.ru_utime + usage.ru_stime,
                   wall_seconds=time.monotonic() - item["started"], max_rss_kib=usage.ru_maxrss)
        save(item["directory"] / (item["label"] + ".process.json"), row)
        self.records.append(row)
        del self.active[process.pid]
        return process.returncode

    def close(self):
        for item in list(self.active.values()):
            self.wait(item, kill=True)


def fixture(binary, namespace, index, directory, financial=False):
    rng = np.random.default_rng(namespace * 1000 + index)
    model = (Law((.3, .018)) if index % 4 == 0 else Law((.15, .002)) if index % 4 == 1 else
             Law(mode="free", free_raw=default_free_raw() + ((-1., .2, -.4, -.5) if index % 4 == 2 else (.7, -.3, .2, .8))))
    if financial:
        theta = ((.3, .018), (.15, .002), (.4, .04), (.22, .01))[index % 4]
        model = Law(theta)
        prior = model.prior.copy()
        text = "HCSN_FINANCIAL_3_V1 " + " ".join(format(x, ".17e") for x in (*theta, 1.3)) + "\n"
    else:
        prior = rng.dirichlet(np.full(40, .8))
        text = "HCSN_FINITE_40_V1\n" + " ".join(format(float(x), ".17e")
                for a in (model.Q, model.E_read, model.E_refresh, prior) for x in a.ravel()) + "\n"
    directory.mkdir(parents=True)
    (directory / "MODEL").write_text(text)
    model_id = identify(binary, directory / "MODEL")
    run = digest(f"hcsn-r20-runtime:{namespace}:{index}".encode())
    commands = list(zip(("PROP", "READ", "RESET", "REFRESH", "PROP", "MISSING", "READ"),
                        (110000000, 80000000, 60000000, 120000000, 250000000, 70000000, 90000000),
                        (0, 25, 0, 70, 0, 0, 25), strict=True))
    rows = [f"PLAN\t{run}\t{model_id}\n"]
    for i, (action, duration, fee) in enumerate(commands):
        rows.append(f"CMD\t{i}\t{action}\t{duration}\t{'paid'+str(i) if fee else '-'}\t{fee}\n")
    plan = seal("".join(rows))
    (directory / "PLAN").write_text(plan)
    catalog = [f"CATALOG\t{run}\t{model_id}\t{fnv(plan.encode()):016x}\n"]
    state, reference, tokens = prior.copy(), [], {}
    for i, (action, duration, fee) in enumerate(commands):
        if action == "RESET":
            state = np.r_[np.zeros(32), state.reshape(10, 4).sum(0), np.zeros(4)]
        state = state @ expm(model.Q * (duration / 1e9))
        if fee:
            emission = model.E_read if action == "READ" else model.E_refresh
            probabilities = state @ emission
            token = int(rng.choice(len(probabilities), p=probabilities / probabilities.sum()))
            tokens[i] = token
            state *= emission[:, token]
            state /= state.sum()
            catalog.append(f"TOKEN\t{i}\tpaid{i}\t{token}\n")
        reference.append(state.copy().tolist())
    (directory / "CATALOG").write_text(seal("".join(catalog)))
    world = dict(run=run, native_financial=financial, commands=commands, tokens=tokens, prior=prior.tolist(), q=model.Q.tolist(),
                 read=model.E_read.tolist(), refresh=model.E_refresh.tolist(), reference=reference,
                 clock_ns=sum(x[1] for x in commands), fee=sum(x[2] for x in commands))
    save(directory / "REFERENCE.json", world)
    return world


def owned(directory):
    rows = unseal((directory / "owner.state").read_bytes()).splitlines()
    header, values = rows[0].split("\t"), rows[1].split("\t")[1:]
    state = np.array([struct.unpack(">d", bytes.fromhex(x))[0] for x in values])
    return dict(header=header, state=state, receipts=[x for x in rows[2:] if x.startswith("EFFECT\t")])


def verify(directory, world):
    owner = owned(directory)
    header = owner["header"]
    ledger = unseal((directory / "provider.state").read_bytes()).splitlines()
    ph, effects = ledger[0].split("\t"), ledger[1:]
    assert header[0] == "OWNER" and header[1] == world["run"]
    assert [int(x) for x in header[4:7]] == [7, world["clock_ns"], world["fee"]] and header[7] == "-"
    assert owner["state"].shape == (40,) and np.isfinite(owner["state"]).all()
    error = float(np.max(abs(owner["state"] - world["reference"][-1])))
    assert error <= 2e-11 and abs(owner["state"].sum() - 1) <= 4e-11
    assert ph[0] == "PROVIDER" and ph[1:4] == header[1:4]
    assert [int(x) for x in ph[5:7]] == [3, world["fee"]]
    assert sorted(effects) == sorted(owner["receipts"]) and len(effects) == 3
    seen = set()
    for row in effects:
        fields = row.split("\t")
        index, token, fee, ordinal = map(int, (fields[4], fields[7], fields[8], fields[9]))
        assert fields[:4] == ["EFFECT", *header[1:4]] and index not in seen
        assert fields[5:7] == [f"paid{index}", world["commands"][index][0]]
        assert token == world["tokens"][str(index)] and fee == world["commands"][index][2]
        assert ordinal == len(seen) + 1
        seen.add(index)
    return dict(maximum_reference_error=error, clock_ns=int(header[5]), fee=int(header[6]), effects=len(effects),
                owner_sha256=digest((directory / "owner.state").read_bytes()),
                provider_sha256=digest((directory / "provider.state").read_bytes()))


def run_case(binary, source, directory, owner_fault, provider_fault, processes):
    directory.mkdir(parents=True)
    for name in ("MODEL", "PLAN", "CATALOG", "REFERENCE.json"):
        shutil.copyfile(source / name, directory / name)
    world = json.loads((directory / "REFERENCE.json").read_text())
    paths = dict(directory=directory)
    p = processes.start(binary, "provider", paths, provider_fault, "provider")
    wait_path(directory / "ENDPOINT")
    o = processes.start(binary, "owner", paths, owner_fault, "owner")
    if provider_fault != "none":
        wait_path(directory / "provider.marker")
        if owner_fault != "none":
            wait_path(directory / "owner.marker")
        for name in ("owner.state", "provider.state"):
            if (directory / name).exists():
                shutil.copyfile(directory / name, directory / ("at_fault_" + name))
        if owner_fault != "none":
            assert processes.wait(o, kill=True) == -9
        assert processes.wait(p, kill=True) == -9
        if owner_fault == "none":
            assert processes.wait(o) != 0
        (directory / "ENDPOINT").unlink()
        p = processes.start(binary, "provider", paths, "none", "provider_restart")
        wait_path(directory / "ENDPOINT")
        o = processes.start(binary, "owner", paths, "none", "owner_restart")
    elif owner_fault != "none":
        wait_path(directory / "owner.marker")
        for name in ("owner.state", "provider.state"):
            if (directory / name).exists():
                shutil.copyfile(directory / name, directory / ("at_fault_" + name))
        assert processes.wait(o, kill=True) == -9
        o = processes.start(binary, "owner", paths, "none", "owner_restart")
    assert processes.wait(o) == 0
    result = verify(directory, world)
    processes.wait(p, kill=True)
    return result


def worker(args):
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    frozen_files = {}
    if args.namespace == protocol["formal_namespace"]:
        assert args.worlds == protocol["formal_worlds"], "Formal world count differs from frozen protocol"
        assert args.financial_worlds == protocol["formal_native_financial_worlds"], "Formal native financial count differs"
        freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
        publication = json.loads((HERE / "SOURCE_PUBLICATION.json").read_text())
        assert publication["readback_verified"] is True
        assert publication["freeze_sha256"] == digest((HERE / "SOURCE_FREEZE.json").read_bytes())
        for name, value in freeze["files"].items():
            assert digest((HERE / name).read_bytes()) == value, "Frozen source changed: " + name
        frozen_files = freeze["files"]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    processes, results = Processes(), []
    try:
        for index in range(args.worlds + args.financial_worlds):
            source = output / "worlds" / str(index)
            fixture(args.binary.resolve(), args.namespace, index, source, financial=index >= args.worlds)
            expected = None
            for number, (owner_fault, provider_fault) in enumerate(SCHEDULES):
                result = run_case(args.binary.resolve(), source, output / "cases" / f"{index:02}_{number:02}",
                                  owner_fault, provider_fault, processes)
                if expected is None:
                    expected = result
                assert result["owner_sha256"] == expected["owner_sha256"]
                assert result["provider_sha256"] == expected["provider_sha256"]
                results.append(dict(world=index, owner_fault=owner_fault, provider_fault=provider_fault, **result))
        from .negativecheck import run as negative_run
        negative_results = negative_run(args.binary.resolve(), output / "cases" / "00_00", output / "negative", processes)
    finally:
        processes.close()
        save(output / "PROCESS_RECORDS.json", processes.records)
    for name, value in frozen_files.items():
        assert digest((HERE / name).read_bytes()) == value, "Source changed during formal execution: " + name
    identifies = [json.loads(p.read_text()) for p in output.rglob("*IDENTIFY.json")]
    save(output / "RESULT.json", dict(passed=True, worlds=args.worlds + args.financial_worlds,
         generic_worlds=args.worlds, native_financial_worlds=args.financial_worlds, cases=len(results),
         native_processes=len(processes.records) + len(identifies),
         native_owner_provider_processes=len(processes.records), native_identification_processes=len(identifies),
         cases_detail=results,
         negative_and_intervention_cases=len(negative_results),
         binary_sha256=digest(args.binary.read_bytes()), source_sha256=digest(Path(__file__).read_bytes()),
         limits="Trusted Linux local IPv4/fsync process-death profile; no hostile writer, paired rollback, power-loss or production admission."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--namespace", type=int, required=True)
    parser.add_argument("--worlds", type=int, default=16)
    parser.add_argument("--financial-worlds", type=int, default=4)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args)
    else:
        start = time.perf_counter()
        process = subprocess.Popen([sys.executable, "-m", __spec__.name, "--binary", str(args.binary),
            "--output", str(args.output), "--namespace", str(args.namespace), "--worlds", str(args.worlds),
            "--financial-worlds", str(args.financial_worlds), "--worker"])
        _, status, usage = os.wait4(process.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        process.returncode = code
        save(args.output / "PROCESS_RECEIPT.json", dict(exit_code=code,
             child_cpu_seconds=usage.ru_utime + usage.ru_stime, wall_seconds=time.perf_counter() - start,
             max_rss_kib=usage.ru_maxrss, scope="Complete worker imports, reference generation, every native child and evidence write; inner native CPU not added."))
        raise SystemExit(code)
