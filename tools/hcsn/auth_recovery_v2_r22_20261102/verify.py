"""Fixed-size authenticated-pair/witness checks and actual retained native replay."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import socket
import subprocess
import sys
import threading
import time

from .checkpoint import Client, DOMAIN, commit, context, restore
from .security import (canonical, count, durable_new, keyfile, open_seal,
                       parse, read_regular, seal, sha)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OLD = REPO / "tools/hcsn/native_runtime_r20_20261101"
PUBLIC_KEY = hashlib.sha256(b"PUBLIC TEST FIXTURE ONLY HCSN AUTH V1").digest()


class Witness:
    def __init__(self, root, key):
        self.root, self.key = root, key
        self.process = None
        self.starts = 0
        self.receipts = []

    def start(self):
        endpoint = self.root / (f"endpoint{self.starts}.json")
        out = (self.root / f"witness{self.starts}.stdout").open("xb")
        err = (self.root / f"witness{self.starts}.stderr").open("xb")
        args = [sys.executable, "-m", "tools.hcsn.auth_recovery_v2_r22_20261102.witness",
                "--key", str(self.key), "--log", str(self.root / "witness-log"),
                "--endpoint", str(endpoint)]
        self.process = subprocess.Popen(args, stdout=out, stderr=err, cwd=REPO)
        self.streams, self.args = (out, err), args
        self.started = time.monotonic()
        self.starts += 1
        while not endpoint.exists():
            if self.process.poll() is not None or time.monotonic() - self.started > 5:
                self.stop()
                raise RuntimeError("witness startup failure")
            time.sleep(.002)
        self.client = Client(self.key, endpoint)
        return self.client

    def stop(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.kill()
        # Popen.wait can reap implicitly after poll; CPU is metered by the outer worker.
        code = self.process.wait()
        for stream in self.streams:
            stream.close()
        self.receipts.append({"command": self.args, "pid": self.process.pid, "exit_code": code,
                              "wall_seconds": time.monotonic() - self.started})
        self.process = None


def expect_reject(name, operation, rows):
    try:
        operation()
    except (ValueError, OSError, TypeError, KeyError) as error:
        rows.append({"name": name, "rejected": True, "error_type": type(error).__name__})
    else:
        raise AssertionError("accepted negative control " + name)


def native_replay(binary, case, expected, states, output):
    output.mkdir(mode=0o700)
    for name in ("MODEL", "PLAN", "CATALOG"):
        shutil.copyfile(case / name, output / name)
    for role in ("owner", "provider"):
        shutil.copyfile(states / (role + ".state"), output / (role + ".state"))
    provider_cmd = [str(binary), "provider", str(output / "MODEL"), str(output / "PLAN"),
                    str(output / "CATALOG"), str(output / "provider.state"), str(output / "ENDPOINT"),
                    "none", str(output / "provider.marker")]
    owner_cmd = [str(binary), "owner", str(output / "MODEL"), str(output / "PLAN"),
                 str(output / "owner.state"), str(output / "ENDPOINT"), "none", str(output / "owner.marker")]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    with (output / "provider.stdout").open("xb") as out, (output / "provider.stderr").open("xb") as err:
        provider = subprocess.Popen(provider_cmd, stdout=out, stderr=err)
        try:
            while not (output / "ENDPOINT").exists():
                if provider.poll() is not None or time.monotonic() - started > 5:
                    raise RuntimeError("native provider startup")
                time.sleep(.002)
            owner = subprocess.run(owner_cmd, capture_output=True, timeout=10)
            (output / "owner.stdout").write_bytes(owner.stdout)
            (output / "owner.stderr").write_bytes(owner.stderr)
            if owner.returncode != 0:
                raise AssertionError("native owner refusal")
        finally:
            if provider.poll() is None:
                provider.kill()
            provider.wait()
    values = {}
    for role in ("owner", "provider"):
        raw = (output / (role + ".state")).read_bytes()
        if raw != (expected / (role + ".state")).read_bytes():
            raise AssertionError("native recovered bytes differ " + role)
        values[role] = sha(raw)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"case": case.relative_to(REPO).as_posix(), "same_existing_world": True,
            "owner_exit": owner.returncode, "provider_exit": provider.returncode,
            "native_processes": 2, "owner_command": owner_cmd, "provider_command": provider_cmd,
            "final_states": values, "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime}


def run(output, development):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    key = output / "public-test-fixture.key"
    durable_new(key, PUBLIC_KEY)
    binary = OLD / "confirmation01/negative/identical_artifact"
    if sha(binary.read_bytes()) != "b30befcb76f00533029c60ce7a430a2b057bc152107625d7a5a4be3cd16f2798":
        raise ValueError("exact binary identity")
    witness = Witness(output, key)
    rows, controls, replays = [], [], []
    client = witness.start()
    try:
        for i in range(4 if development else 32):
            identity = sha(f"HCSN-R22-auth-fixed-roster:{i}".encode())
            folder = output / f"pair{i}"
            owner, provider = hashlib.shake_256(f"owner{i}".encode()).digest(137), hashlib.shake_256(f"provider{i}".encode()).digest(181)
            first = commit(folder, client, identity, owner, provider)
            current = commit(folder, client, identity, owner + b"next", provider + b"next")
            record = restore(folder, client, identity, output / f"restored{i}")
            if (output / f"restored{i}/owner.state").read_bytes() != owner + b"next":
                raise AssertionError("state roundtrip")
            current_path = folder / "00000001.checkpoint"
            data = current_path.read_bytes()
            # Roll back BOTH actor states inside a previously valid authenticated envelope.
            current_path.write_bytes((folder / "00000000.checkpoint").read_bytes())
            expect_reject(f"paired_rollback_{i}", lambda: restore(folder, client, identity, output / f"badrollback{i}"), controls)
            current_path.write_bytes(data)
            altered = bytearray(data)
            altered[-3] ^= 1
            current_path.write_bytes(altered)
            expect_reject(f"tamper_{i}", lambda: restore(folder, client, identity, output / f"badtamper{i}"), controls)
            current_path.write_bytes(data)
            rows.append({"context": identity, "first": first, "current": current, "restored": record,
                         "checkpoint": current_path.relative_to(output).as_posix(), "checkpoint_sha256": sha(data)})
        identity = rows[0]["context"]
        expect_reject("stale_compare_and_swap", lambda: client.query(identity, "commit", (-1, "0"*64), (0, "1"*64)), controls)
        expect_reject("boolean_sequence", lambda: count(True), controls)
        expect_reject("duplicate_json_key", lambda: parse(b'{"a":1,"a":2}'), controls)
        expect_reject("wrong_mac_domain", lambda: open_seal(PUBLIC_KEY, "wrong", seal(PUBLIC_KEY, DOMAIN, {})), controls)
        expect_reject("nonfinite_json", lambda: parse(b'{"a":NaN}'), controls)
        wrong_key = output / "wrong-fixture.key"
        durable_new(wrong_key, hashlib.sha256(PUBLIC_KEY).digest())
        expect_reject("wrong_key", lambda: Client(wrong_key, output/"endpoint0.json").query(identity), controls)
        bad_key = output / "permissions-fixture.key"
        durable_new(bad_key, PUBLIC_KEY)
        bad_key.chmod(0o644)
        expect_reject("key_permissions", lambda: keyfile(bad_key), controls)
        linked_key = output / "symlink-fixture.key"
        linked_key.symlink_to(key)
        expect_reject("key_symlink", lambda: keyfile(linked_key), controls)
        response = seal(PUBLIC_KEY, "hcsn-witness-response-v1", {"context": identity, "nonce": "0"*64,
                        "seq": rows[0]["current"][0], "digest": rows[0]["current"][1]})
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            def replay_response():
                with listener.accept()[0] as stream:
                    stream.recv(8192); stream.sendall(response+b"\n")
            thread = threading.Thread(target=replay_response)
            thread.start()
            fake = output / "replayed_endpoint.json"
            durable_new(fake, canonical({"host": "127.0.0.1", "port": listener.getsockname()[1]}))
            expect_reject("replayed_witness_response", lambda: Client(key, fake).query(identity), controls)
            thread.join(timeout=3)
            if thread.is_alive(): raise AssertionError("replay peer did not exit")
        # One unauthenticated peer may keep sending bytes; an absolute deadline evicts it.
        attack = socket.create_connection(client.endpoint, timeout=3)
        attack.settimeout(3)
        attack.sendall(b"{")
        stop_drip = threading.Event()
        drip_times = []
        begin = time.monotonic()
        def drip():
            while not stop_drip.wait(.1):
                try:
                    attack.sendall(b" ")
                    drip_times.append(time.monotonic()-begin)
                except OSError:
                    break
        dripping = threading.Thread(target=drip)
        dripping.start()
        try:
            time.sleep(.05)
            request_started = time.monotonic()
            if client.query(identity) != tuple(rows[0]["current"]):
                raise AssertionError("legitimate request after slow peer")
            elapsed = time.monotonic()-request_started
            rejected = attack.recv(4096)
            if elapsed > 2.5 or not drip_times or parse(rejected) != {"error": "rejected"}:
                raise AssertionError("slow peer was not bounded")
            controls.append({"name": "slow_peer_absolute_deadline", "rejected": True,
                             "legitimate_tip_seconds": elapsed, "drip_times": drip_times,
                             "server_reply_sha256": sha(rejected)})
        finally:
            stop_drip.set()
            attack.close()
            dripping.join(timeout=1)
            if dripping.is_alive(): raise AssertionError("drip worker did not finish")
        with socket.create_connection(client.endpoint, timeout=3) as oversized:
            oversized.settimeout(3)
            oversized.sendall(b"x"*8193+b"\n")
            try:
                reply = oversized.recv(4096)
                if parse(reply) != {"error": "rejected"}:
                    raise AssertionError("oversized request accepted")
            except ConnectionResetError:
                pass
        if client.query(identity) != tuple(rows[0]["current"]):
            raise AssertionError("service after oversized peer")
        controls.append({"name": "oversized_request", "rejected": True, "bytes": 8194})
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            stop_response = threading.Event()
            def drip_response():
                with listener.accept()[0] as peer:
                    peer.recv(8192)
                    peer.sendall(b"{")
                    while not stop_response.wait(.1):
                        try:
                            peer.sendall(b" ")
                        except OSError:
                            break
            slow_response = threading.Thread(target=drip_response)
            slow_response.start()
            fake = output / "slow-response-endpoint.json"
            durable_new(fake, canonical({"host": "127.0.0.1", "port": listener.getsockname()[1]}))
            response_started = time.monotonic()
            try:
                expect_reject("slow_response_absolute_deadline", lambda: Client(key, fake).query(identity), controls)
                controls[-1]["seconds"] = time.monotonic()-response_started
                if controls[-1]["seconds"] > 4.0:
                    raise AssertionError("response deadline not bounded")
            finally:
                stop_response.set()
                slow_response.join(timeout=1)
                if slow_response.is_alive(): raise AssertionError("response peer did not finish")
        witness.stop()
        expect_reject("witness_unavailable", lambda: client.query(identity), controls)
        client = witness.start()
        if client.query(identity) != tuple(rows[0]["current"]):
            raise AssertionError("durable witness restart")
        roster = ((16, 2),) if development else ((16, 3), (17, 7), (18, 8), (19, 4))
        for number, cut in roster:
            case = OLD / f"confirmation01/cases/{number:02}_{cut:02}"
            owner = (case / "at_fault_owner.state").read_bytes()
            provider = (case / "at_fault_provider.state").read_bytes()
            if not development and int(provider.splitlines()[0].split(b"\t")[-1]) <= 0:
                raise AssertionError("formal checkpoint must retain actual paid effect")
            identifier = context(binary, case / "MODEL", case / "PLAN", sha(f"native:{number}:{cut}".encode()))
            folder = output / f"native-envelope-{number}"
            tip = commit(folder, client, identifier, owner, provider)
            states = output / f"native-states-{number}"
            restored = restore(folder, client, identifier, states)
            replay = native_replay(binary, case, OLD / f"confirmation01/cases/{number:02}_00", states, output / f"native-execution-{number}")
            replay.update({"context": identifier, "authenticated_tip": tip, "admission": restored,
                           "paid_pending_provenance": not development})
            replays.append(replay)
            if not development and number == 16:
                changed_model = output / "changed-model"
                durable_new(changed_model, (case / "MODEL").read_bytes() + b" ")
                changed_plan = output / "changed-plan"
                durable_new(changed_plan, (case / "PLAN").read_bytes() + b" ")
                wrong_contexts = {
                    "changed_model_context": context(binary, changed_model, case/"PLAN", sha(f"native:{number}:{cut}".encode())),
                    "changed_plan_context": context(binary, case/"MODEL", changed_plan, sha(f"native:{number}:{cut}".encode())),
                    "changed_executable_context": context(OLD/"confirmation01/negative/alternate_artifact", case/"MODEL", case/"PLAN", sha(f"native:{number}:{cut}".encode()))}
                for name, wrong_context in wrong_contexts.items():
                    expect_reject(name, lambda c=wrong_context: restore(folder, client, c, output/name), controls)
                linked = output / "linked-pair-folder"
                linked.symlink_to(folder, target_is_directory=True)
                expect_reject("pair_directory_symlink", lambda: restore(linked, client, identifier, output/"badlinked"), controls)
                candidate = folder / "00000000.checkpoint"
                moved = folder / "retained-original.checkpoint"
                candidate.rename(moved)
                candidate.symlink_to(moved)
                expect_reject("checkpoint_symlink", lambda: restore(folder, client, identifier, output/"badfilesymlink"), controls)
                candidate.unlink(); moved.rename(candidate)
        witness.stop()
        log = output / "witness-log/00000000.record"
        data = log.read_bytes()
        durable_new(log.with_suffix(".before-tamper"), data)
        log.write_bytes(data[:-1])
        try:
            witness.start()
        except RuntimeError:
            controls.append({"name": "tampered_witness_log", "rejected": True})
        else:
            raise AssertionError("tampered witness log admitted")
    finally:
        witness.stop()
    result = {"passed": True, "development": development, "synthetic_contexts": len(rows),
              "negative_controls": len(controls), "controls": controls, "pairs": rows,
              "native_replays": replays, "native_worlds_are_retained_R20_worlds": True,
              "witness_processes": witness.receipts, "test_key_is_public_fixture_not_live_credential": True,
              "production_activation": False, "cross_host_or_powerloss_qualification": False}
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    result = run(args.output.resolve(), args.development)
    print(json.dumps({key: result[key] for key in ("passed", "development", "synthetic_contexts", "negative_controls")}, sort_keys=True))


if __name__ == "__main__":
    main()
