"""Independent real-peer checks for prospective absolute framed-I/O deadlines."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KEY = hashlib.sha256(b"PUBLIC INDEPENDENT V2 FRAMING FIXTURE ONLY").digest()
ZERO = "0"*64
CONTEXT = hashlib.sha256(b"independent-v2-network-context").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def tag(domain, body):
    return hmac.new(KEY, domain.encode()+b"\0"+canonical(body), hashlib.sha256).hexdigest()


def exchange(endpoint, nonce, frame_bytes=None):
    body = {"context": CONTEXT, "nonce": nonce, "op": "tip", "prev_seq": -1,
            "prev_digest": ZERO, "seq": 0, "digest": ZERO}
    data = canonical({"body": body, "tag": tag("hcsn-witness-request-v1", body)})
    if frame_bytes is not None:
        assert len(data)+1 <= frame_bytes
        data += b" "*(frame_bytes-len(data)-1)
    with socket.create_connection(endpoint, timeout=3) as connection:
        connection.settimeout(3)
        connection.sendall(data+b"\n")
        with connection.makefile("rb") as reader:
            raw = reader.readline(2**20+1)
    response = json.loads(raw)
    if "tag" not in response:
        return {"rejected": True, "response": response}
    assert response["tag"] == tag("hcsn-witness-response-v1", response["body"])
    assert response["body"]["nonce"] == nonce and response["body"]["seq"] == -1
    return {"rejected": False, "tip": response["body"]}


def fake_reply(folder, mode):
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); listener.listen(1)
        (folder/"endpoint.json").write_bytes(canonical({"host": "127.0.0.1", "port": listener.getsockname()[1]}))
        with listener.accept()[0] as connection:
            connection.settimeout(4)
            with connection.makefile("rb") as reader:
                request_raw = reader.readline(8193)
            request = json.loads(request_raw)
            assert request["tag"] == tag("hcsn-witness-request-v1", request["body"])
            sent, peer_closed = 0, False
            if mode == "slow":
                started = time.monotonic()
                while time.monotonic()-started < 4.2:
                    try:
                        connection.sendall(b"{" if sent == 0 else b" ")
                        sent += 1
                    except OSError:
                        peer_closed = True; break
                    time.sleep(.1)
            else:
                size = int(mode)
                body = {"context": request["body"]["context"], "nonce": request["body"]["nonce"],
                        "seq": -1, "digest": ZERO}
                raw = canonical({"body": body, "tag": tag("hcsn-witness-response-v1", body)})
                response = raw+b" "*(size-len(raw)-1)+b"\n"
                assert len(response) == size
                connection.sendall(response); sent = size
            (folder/"PEER.json").write_text(json.dumps({"mode": mode, "sent_bytes": sent,
                "peer_closed": peer_closed, "request_sha256": hashlib.sha256(request_raw).hexdigest()}, indent=2)+"\n")


def start_process(command, folder, endpoint_file):
    stdout = (folder/"child.stdout").open("xb")
    stderr = (folder/"child.stderr").open("xb")
    process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
    begin = time.monotonic()
    while not endpoint_file.exists():
        if process.poll() is not None or time.monotonic()-begin > 5:
            raise RuntimeError("peer startup")
        time.sleep(.002)
    return process, (stdout, stderr)


def stop(process, streams):
    try:
        code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill(); code = process.wait()
    for stream in streams: stream.close()
    return code


def run(folder):
    # The actual client is the subject under test; reference request/response
    # construction above uses only stdlib and imports no candidate MAC/framing helper.
    from .checkpoint import Client
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    freeze = json.loads((HERE/"SOURCE_FREEZE.json").read_text())
    for row in freeze["source"]:
        assert hashlib.sha256((ROOT/row["path"]).read_bytes()).hexdigest() == row["sha256"]
    key = folder/"public-fixture.key"
    fd = os.open(key, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream: stream.write(KEY)
    witness_folder = folder/"actual-witness"
    witness_folder.mkdir(mode=0o700)
    endpoint_file = witness_folder/"endpoint.json"
    command = [sys.executable, "-m", "tools.hcsn.auth_recovery_v2_r22_20261102.witness",
               "--key", str(key), "--log", str(witness_folder/"log"), "--endpoint", str(endpoint_file)]
    process, streams = start_process(command, witness_folder, endpoint_file)
    attack, thread = None, None
    stop_drip = threading.Event()
    records = []
    try:
        info = json.loads(endpoint_file.read_text()); endpoint = (info["host"], info["port"])
        assert not exchange(endpoint, "1"*64)["rejected"]
        attack = socket.create_connection(endpoint, timeout=3)
        attack.sendall(b"{")
        sent = []
        def drip():
            begin = time.monotonic()
            while not stop_drip.is_set() and time.monotonic()-begin < 3.5:
                try: attack.sendall(b" ")
                except OSError: break
                sent.append(time.monotonic()-begin); time.sleep(.1)
        thread = threading.Thread(target=drip)
        thread.start(); time.sleep(.1)
        started = time.monotonic()
        valid = exchange(endpoint, "2"*64)
        elapsed = time.monotonic()-started
        assert not valid["rejected"] and elapsed < 1.8
        stop_drip.set(); thread.join(timeout=2)
        assert not thread.is_alive()
        attack.settimeout(1)
        rejection = attack.recv(4096)
        assert json.loads(rejection) == {"error": "rejected"}
        attack.close(); attack = None
        records.append({"name": "slow_ingress_evicted_and_valid_service_resumes", "passed": True,
                        "valid_query_seconds": elapsed, "drip_sent_blanks": len(sent), "margin_seconds": 1.8})
        assert not exchange(endpoint, "3"*64, 8192)["rejected"]
        assert exchange(endpoint, "4"*64, 8193)["rejected"]
        assert not exchange(endpoint, "5"*64)["rejected"]
        records.append({"name": "request_boundary", "accepted_frame_bytes": 8192,
                        "rejected_frame_bytes": 8193, "service_after_rejection": True, "passed": True})
    finally:
        stop_drip.set()
        if attack is not None: attack.close()
        if thread is not None: thread.join(timeout=2)
        if process.poll() is None: process.kill()
        witness_code = stop(process, streams)
    peer_codes = []
    for mode in ("slow", "8192", "8193"):
        parent = folder/("reply-"+mode); parent.mkdir(mode=0o700)
        peer_folder = parent/"peer"
        command = [sys.executable, "-m", "tools.hcsn.auth_recovery_v2_r22_20261102.independent_v2_network",
                   "--fake-reply", str(peer_folder), "--reply-mode", mode]
        process, streams = start_process(command, parent, peer_folder/"endpoint.json")
        started = time.monotonic()
        error = None
        try:
            try:
                answer = Client(key, peer_folder/"endpoint.json").query(CONTEXT)
            except (ValueError, TimeoutError, OSError) as problem:
                error = type(problem).__name__
            elapsed = time.monotonic()-started
            if mode == "slow":
                assert error == "TimeoutError" and elapsed < 3.8
            elif mode == "8192":
                assert error is None and answer == (-1, ZERO)
            else:
                assert error is not None
            records.append({"name": "reply_"+mode, "error_type": error,
                            "seconds": elapsed, "passed": True})
        finally:
            peer_codes.append(stop(process, streams))
    assert peer_codes == [0, 0, 0]
    result = {"passed": True, "cases": records, "case_count": len(records),
              "real_peer_processes": 4, "fake_reply_peer_exit_codes": peer_codes,
              "actual_witness_exit_code": witness_code,
              "source_freeze_sha256": hashlib.sha256((HERE/"SOURCE_FREEZE.json").read_bytes()).hexdigest(),
              "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "Sequential bounded engineering controls only. Scheduling margins are test contracts, not hard realtime/flood/parallel-owner/cross-host/power-loss qualification."}
    (folder/"RESULTS.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"passed": True, "cases": len(records), "real_peer_processes": 4}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fake-reply", type=Path)
    parser.add_argument("--reply-mode", choices=("slow", "8192", "8193"))
    args = parser.parse_args()
    if args.fake_reply:
        fake_reply(args.fake_reply, args.reply_mode)
    else:
        if args.output is None: parser.error("--output required")
        run(args.output.resolve())
