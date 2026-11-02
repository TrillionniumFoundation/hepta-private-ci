"""Native transport regression with real processes, TCP loss and durable effects."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import time


def fnv(data):
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) % 2**64
    return h


def sealed(body):
    return body + f"CHECK\t{fnv(body.encode()):016x}\n"


def body(path):
    text = path.read_text()
    data, check = text.rsplit("CHECK\t", 1)
    assert check == f"{fnv(data.encode()):016x}\n"
    return data


def save(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def await_path(path, seconds=6):
    end = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() > end:
            raise TimeoutError(str(path))
        time.sleep(.003)


class Campaign:
    def __init__(self, output):
        self.output, self.processes, self.active, self.cases = output, [], {}, []

    def start(self, label, binary, role, job, state, endpoint, stage="none", gated=False):
        args = [str(binary), role, str(job), str(state), str(endpoint), stage,
                str(state.parent / (label + ".marker"))]
        out = (state.parent / (label + ".stdout")).open("xb")
        err = (state.parent / (label + ".stderr")).open("xb")
        started = time.monotonic()
        if gated:
            reader, writer = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(writer)
                os.read(reader, 1)
                os.close(reader)
                os.dup2(out.fileno(), 1)
                os.dup2(err.fileno(), 2)
                os.execv(args[0], args)
            os.close(reader)
            proc = None
        else:
            proc = subprocess.Popen(args, stdout=out, stderr=err)
            pid, writer = proc.pid, None
        item = dict(pid=pid, process=proc, command=args, label=label, started=started,
                    out=out, err=err, gate=writer, directory=state.parent)
        self.active[pid] = item
        return item

    def wait(self, item, kill=False):
        if kill:
            os.kill(item["pid"], signal.SIGKILL)
        pid, status, use = os.wait4(item["pid"], 0)
        code = os.waitstatus_to_exitcode(status)
        if item["process"] is not None:
            item["process"].returncode = code
        item["out"].close()
        item["err"].close()
        row = dict(pid=pid, command=item["command"], label=item["label"], exit_code=code,
                   cpu_seconds=use.ru_utime + use.ru_stime, max_rss_kib=use.ru_maxrss,
                   wall_seconds=time.monotonic() - item["started"])
        save(item["directory"] / (item["label"] + ".process.json"), row)
        self.processes.append(row)
        del self.active[pid]
        return code

    def cleanup(self):
        for item in list(self.active.values()):
            self.wait(item, kill=True)


def job(path):
    run, before = "a" * 64, "00"
    rows = [f"RUN\t{run}\t{before}\n"]
    events = [("prepared:READ", "op1", -1, 10, 0, 0),
              ("received:READ", "op1", 7, 20, 25, 25),
              ("applied:READ", "-", -1, 0, 0, 0),
              ("received:REFRESH", "op2", 9, 40, 70, 70),
              ("query_boundary", "-", -1, 0, 0, 0)]
    for i, (event, opid, token, elapsed, fee, remote) in enumerate(events):
        after = f"{i+1:02x}"
        rows.append(f"FRAME\t{i}\t{event}\t{opid}\t{token}\t{elapsed}\t{fee}\t{remote}\t{fnv(before.encode()):016x}\t{after}\n")
        before = after
    path.write_text(sealed("".join(rows)))
    return run


def mailbox_request(mailbox, identifier, request):
    req = mailbox / (identifier + ".req")
    req.write_text(sealed(f"REQ\t{identifier}\t{request.encode().hex()}\n"))
    response = mailbox / (identifier + ".resp")
    await_path(response)
    row = body(response).strip().split("\t")
    assert row[:2] == ["RESP", identifier]
    response.unlink()
    return bytes.fromhex(row[2]).decode()


def tcp_request(endpoint, request):
    host, port = endpoint.read_text().strip().split(":")
    with socket.create_connection((host, int(port)), timeout=5) as conn:
        conn.sendall(struct.pack(">I", len(request)) + request.encode())
        def exact(n):
            data = b""
            while len(data) < n:
                part = conn.recv(n - len(data))
                if not part:
                    raise EOFError()
                data += part
            return data
        return exact(struct.unpack(">I", exact(4))[0]).decode()


def verify(directory, count=2):
    provider = body(directory / "provider.state").splitlines()
    header = provider[0].split("\t")
    effects = [x.split("\t") for x in provider[1:] if x.startswith("EFFECT\t")]
    assert int(header[4]) == count == len(effects)
    assert int(header[5]) == sum(int(x[5]) for x in effects)
    if count == 2:
        assert {x[2] for x in effects} == {"op1", "op2"}
        owner = body(directory / "owner.state").splitlines()
        h = owner[0].split("\t")
        assert h[4:] == ["5", "70", "95"] and owner[1] == "STATE\t05"
        assert sorted(x for x in owner[2:]) == sorted("\t".join(x) for x in effects)
    return dict(count=count, charged_micros=int(header[5]), generation=int(header[3]))


def campaign(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    c = Campaign(output)
    try:
        for label, binary, expected in [("baseline_alias", args.baseline, 2),
                                        ("candidate_alias", args.binary, 0)]:
            d = output / label
            d.mkdir()
            run = job(d / "job")
            p = c.start("provider", binary, "provider", d / "job", d / "provider.state", d / "mailbox")
            await_path(d / "mailbox/READY")
            o = c.start("owner", binary, "owner", d / "job", d / "owner.state", d / "mailbox", gated=True)
            alias = f"{o['pid']}-0000000000"
            assert mailbox_request(d / "mailbox", alias, "LEASE\t" + run) == "LEASE\t1"
            assert mailbox_request(d / "mailbox", "999999999-0000000001", "LEASE\t" + run) == "LEASE\t2"
            os.write(o["gate"], b"x")
            os.close(o["gate"])
            assert c.wait(o) == expected
            result = verify(d, count=0 if expected else 2)
            if expected:
                assert "stale owner generation" in (d / "owner.stderr").read_text()
            c.wait(p, kill=True)
            c.cases.append(dict(name=label, passed=True, historical_pid_alias=alias, **result))

        for stage in ["none", "relay_after_effect"]:
            d = output / ("tcp_" + stage)
            d.mkdir()
            run = job(d / "job")
            p = c.start("provider", args.binary, "provider", d / "job", d / "provider.state", d / "mailbox")
            await_path(d / "mailbox/READY")
            r = c.start("relay", args.binary, "relay", d / "job", d / "endpoint", d / "mailbox", stage)
            await_path(d / "endpoint")
            if stage == "none":
                host, port = d.joinpath("endpoint").read_text().strip().split(":")
                for wire in [struct.pack(">I", 65537), struct.pack(">I", 0),
                             struct.pack(">I", 4) + b"x", struct.pack(">I", 1) + b"\xff"]:
                    with socket.create_connection((host, int(port)), timeout=3) as conn:
                        conn.sendall(wire)
                        conn.shutdown(socket.SHUT_WR)
                        assert conn.recv(1) == b""
                assert tcp_request(d / "endpoint", "BAD").startswith("ERR\t")
            o = c.start("owner", args.binary, "owner", d / "job", d / "owner.state", d / "endpoint")
            if stage != "none":
                await_path(d / "relay.marker")
                verify(d, count=1)
                assert c.wait(r, kill=True) == -9
                assert c.wait(o) == 2
                (d / "endpoint").unlink()
                r = c.start("relay_restart", args.binary, "relay", d / "job", d / "endpoint", d / "mailbox")
                await_path(d / "endpoint")
                o = c.start("owner_restart", args.binary, "owner", d / "job", d / "owner.state", d / "endpoint")
            assert c.wait(o) == 0
            result = verify(d)
            assert tcp_request(d / "endpoint", f"CALL\t{run}\t0\top1\tREAD\t25").startswith("ERR\t")
            assert verify(d) == result
            c.wait(r, kill=True)
            c.wait(p, kill=True)
            c.cases.append(dict(name=d.name, passed=True, malformed_frames=4 if stage == "none" else 0, **result))

        for label, counter in [("counter_corrupt", "broken\n"), ("counter_exhausted", sealed(str(2**64-1) + "\n"))]:
            d = output / label
            d.mkdir()
            job(d / "job")
            p = c.start("provider", args.binary, "provider", d / "job", d / "provider.state", d / "mailbox")
            await_path(d / "mailbox/READY")
            (d / "mailbox/client-sequence").write_text(counter)
            o = c.start("owner", args.binary, "owner", d / "job", d / "owner.state", d / "mailbox")
            assert c.wait(o) == 2
            result = verify(d, count=0)
            c.wait(p, kill=True)
            c.cases.append(dict(name=label, passed=True, **result))
    finally:
        c.cleanup()
        save(output / "PROCESS_RECORDS.json", c.processes)
    result = dict(cases=c.cases, processes=len(c.processes),
                  child_cpu_seconds=sum(x["cpu_seconds"] for x in c.processes),
                  all_passed=len(c.cases) == 6,
                  binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                  baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest())
    save(output / "RESULT.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    campaign(p.parse_args())
