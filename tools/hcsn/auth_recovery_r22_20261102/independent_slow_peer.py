"""Independent unauthenticated slow-peer availability counterexample, not safety repair."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
KEY = hashlib.sha256(b"PUBLIC INDEPENDENT SLOW PEER FIXTURE ONLY").digest()
ZERO = "0"*64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def tag(domain, body):
    return hmac.new(KEY, domain.encode()+b"\0"+canonical(body), hashlib.sha256).hexdigest()


def exchange(endpoint, nonce):
    body = {"context": hashlib.sha256(b"slow-peer-independent-context").hexdigest(),
            "nonce": nonce, "op": "tip", "prev_seq": -1, "prev_digest": ZERO, "seq": 0, "digest": ZERO}
    request = canonical({"body": body, "tag": tag("hcsn-witness-request-v1", body)})
    with socket.create_connection(endpoint, timeout=3) as stream:
        stream.settimeout(3)
        stream.sendall(request+b"\n")
        with stream.makefile("rb") as reader:
            response = json.loads(reader.readline(2**20+1))
    assert response["tag"] == tag("hcsn-witness-response-v1", response["body"])
    assert response["body"]["nonce"] == nonce and response["body"]["seq"] == -1
    return {"request_sha256": hashlib.sha256(request).hexdigest(), "authenticated_tip": response["body"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    key = folder/"public-fixture.key"
    descriptor = os.open(key, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(KEY)
    endpoint_file = folder/"endpoint.json"
    command = [sys.executable, "-m", "tools.hcsn.auth_recovery_r22_20261102.witness", "--key", str(key),
               "--log", str(folder/"witness-log"), "--endpoint", str(endpoint_file)]
    started = time.monotonic()
    cpu_started = time.process_time()
    with (folder/"witness.stdout").open("xb") as stdout, (folder/"witness.stderr").open("xb") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        attack = None
        thread = None
        try:
            while not endpoint_file.exists():
                if process.poll() is not None or time.monotonic()-started>5:
                    raise RuntimeError("witness startup")
                time.sleep(.002)
            info = json.loads(endpoint_file.read_text())
            endpoint = (info["host"], info["port"])
            baseline = exchange(endpoint, "1"*64)
            attack = socket.create_connection(endpoint, timeout=3)
            attack.sendall(b"{")
            drip_times = []
            def drip():
                begin = time.monotonic()
                while time.monotonic()-begin < 4.4:
                    attack.sendall(b" ")
                    drip_times.append(time.monotonic()-begin)
                    time.sleep(.2)
            thread = threading.Thread(target=drip)
            thread.start()
            time.sleep(.1)
            before = time.monotonic()
            try:
                exchange(endpoint, "2"*64)
            except (TimeoutError, socket.timeout) as error:
                denied = {"error_type": type(error).__name__, "seconds": time.monotonic()-before}
            else:
                raise AssertionError("the frozen serial/idle-timeout candidate did not exhibit the predicted denial")
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("slow peer did not terminate")
            attack.close(); attack = None
            recovered = exchange(endpoint, "3"*64)
        finally:
            if attack is not None: attack.close()
            if thread is not None: thread.join(timeout=5)
            if process.poll() is None: process.kill()
            _, status, use = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
    result = {"counterexample_observed": True, "candidate_changed": False,
              "baseline": baseline, "victim": denied, "recovered_after_peer_closes": recovered,
              "unauthenticated_drip_bytes": len(drip_times)+1, "drip_interval_seconds": .2,
              "drip_duration_seconds": 4.4, "observed_drip_times": drip_times,
              "witness_exit_code": process.returncode,
              "witness_child_cpu_seconds": use.ru_utime+use.ru_stime,
              "parent_body_cpu_seconds_after_imports": time.process_time()-cpu_started,
              "wall_seconds": time.monotonic()-started,
              "complete_process_family_cpu_seconds": None,
              "interpretation": "The 3-second socket timeout is idle per read, not an absolute request deadline. Serial handling permits an unauthenticated drip peer to block a legitimate authenticated tip query. Existing bounded MAC/retained-witness safety results are not refuted; service/deadline qualification remains open.",
              "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (folder/"COUNTEREXAMPLE.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"counterexample_observed": True, "victim_timeout_seconds": denied["seconds"]}, sort_keys=True))


if __name__ == "__main__":
    main()
