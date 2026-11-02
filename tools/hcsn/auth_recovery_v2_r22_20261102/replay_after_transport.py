"""Replay verified signed checkpoint artifacts in fresh private TEST directories."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

from .checkpoint import Client, context, restore

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT/"tools/hcsn/native_runtime_r20_20261101"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular_bytes(path):
    descriptor = os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode): raise ValueError("regular input file required")
        with os.fdopen(descriptor, "rb", closefd=False) as stream: return stream.read()
    finally:
        os.close(descriptor)


def write_private(path, raw):
    descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(parent)
    finally: os.close(parent)
    assert regular_bytes(path) == raw and stat.S_IMODE(path.stat().st_mode) == 0o600


def wait_endpoint(path, process):
    deadline = time.monotonic()+5
    while not path.exists():
        if process.poll() is not None or time.monotonic()>deadline: raise RuntimeError("child endpoint startup")
        time.sleep(.002)


def terminate(process):
    if process is None: return None
    if process.poll() is None: process.kill()
    return process.wait()


def run(transported, output, binary):
    protocol = json.loads((HERE/"TRANSPORT_REPLAY_PROTOCOL.json").read_text())
    pinned = regular_bytes(HERE/protocol["pinned_input_manifest"])
    assert sha(pinned) == protocol["pinned_input_manifest_sha256"]
    rows = {row["path"]: row for row in json.loads(pinned)["files"]}
    used = {}
    def recorded(name):
        row = rows[name];raw = regular_bytes(transported/name)
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], name
        used[name] = {"bytes":len(raw), "sha256":sha(raw)}
        return raw
    source = json.loads(regular_bytes(HERE/"SOURCE_FREEZE.json"))
    for row in source["source"]:
        raw = regular_bytes(ROOT/row["path"])
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
    old_manifest = regular_bytes(OLD/"ARTIFACT_MANIFEST.json")
    assert sha(old_manifest) == protocol["original_R20_manifest_sha256"]
    old_rows = {row["path"]:row for row in json.loads(old_manifest)["files"]}
    expected = {}
    for name,row in protocol["expected_R20_files"].items():
        assert old_rows[name]["bytes"] == row["bytes"] and old_rows[name]["sha256"] == row["sha256"]
        raw = regular_bytes(OLD/name)
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
        expected[Path(name).name] = raw
    raw_binary = regular_bytes(binary)
    assert len(raw_binary) == protocol["binary"]["bytes"] and sha(raw_binary) == protocol["binary"]["sha256"]
    result_source = json.loads(recorded("confirmation01/RESULTS.json"))
    selected = next(row for row in result_source["native_replays"] if row["case"].endswith("/16_03"))
    assert selected["paid_pending_provenance"]
    key = recorded("confirmation01/public-test-fixture.key")
    assert len(key) == 32
    signed_pair = recorded("confirmation01/native-envelope-16/00000000.checkpoint")
    damaged_original = recorded("confirmation01/witness-log/00000000.record")
    restored_records = []
    for index in range(protocol["witness_log_records"]):
        name = ("confirmation01/witness-log/00000000.before-tamper" if index==0
                else f"confirmation01/witness-log/{index:08}.record")
        restored_records.append((name, recorded(name)))
    runtime_inputs = {name: recorded("confirmation01/native-execution-16/"+name)
                      for name in ("MODEL", "PLAN", "CATALOG")}
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    keyfile = output/"public-fixture.key";write_private(keyfile, key)
    witness_log, pair = output/"private-test-witness-log", output/"private-test-pair"
    witness_log.mkdir(mode=0o700);pair.mkdir(mode=0o700)
    for index,(_,raw) in enumerate(restored_records): write_private(witness_log/f"{index:08}.record", raw)
    write_private(pair/"00000000.checkpoint", signed_pair)
    actor_inputs = output/"private-native-inputs";actor_inputs.mkdir(mode=0o700)
    for name,raw in runtime_inputs.items(): write_private(actor_inputs/name, raw)
    identifier = context(binary, actor_inputs/"MODEL", actor_inputs/"PLAN", sha(b"native:16:3"))
    assert identifier == selected["context"]
    endpoint = output/"witness.endpoint"
    witness_command = [sys.executable,"-m","tools.hcsn.auth_recovery_v2_r22_20261102.witness",
                       "--key",str(keyfile),"--log",str(witness_log),"--endpoint",str(endpoint)]
    witness, provider = None, None
    native = output/"native-after-authenticated-restore"
    with (output/"witness.stdout").open("xb") as witness_out, (output/"witness.stderr").open("xb") as witness_err:
        try:
            witness = subprocess.Popen(witness_command,cwd=ROOT,stdout=witness_out,stderr=witness_err)
            wait_endpoint(endpoint,witness)
            client = Client(keyfile,endpoint)
            tip = client.query(identifier)
            assert list(tip) == selected["authenticated_tip"]
            admission = restore(pair,client,identifier,native)
            assert admission == selected["admission"]
            for name,raw in runtime_inputs.items(): write_private(native/name, raw)
            provider_state = regular_bytes(native/"provider.state").splitlines()[0].split(b"\t")
            assert int(provider_state[-1]) > 0
            provider_command = [str(binary),"provider",str(native/"MODEL"),str(native/"PLAN"),str(native/"CATALOG"),
                                str(native/"provider.state"),str(native/"ENDPOINT"),"none",str(native/"provider.marker")]
            owner_command = [str(binary),"owner",str(native/"MODEL"),str(native/"PLAN"),str(native/"owner.state"),
                             str(native/"ENDPOINT"),"none",str(native/"owner.marker")]
            with (output/"provider.stdout").open("xb") as out,(output/"provider.stderr").open("xb") as err:
                provider = subprocess.Popen(provider_command,stdout=out,stderr=err)
                try:
                    wait_endpoint(native/"ENDPOINT",provider)
                    owner = subprocess.run(owner_command,capture_output=True,timeout=10)
                    (output/"owner.stdout").write_bytes(owner.stdout);(output/"owner.stderr").write_bytes(owner.stderr)
                    assert owner.returncode == 0
                finally:
                    provider_exit = terminate(provider);provider = None
            final = {}
            for name,raw in expected.items():
                actual = regular_bytes(native/name)
                assert actual == raw
                final[name] = sha(actual)
            assert client.query(identifier) == tip
        finally:
            terminate(provider)
            witness_exit = terminate(witness)
    # Rehydration was private test input construction, not a write to the archived witness.
    assert recorded("confirmation01/witness-log/00000000.record") == damaged_original
    for name,metadata in used.items():
        raw = regular_bytes(transported/name)
        assert len(raw) == metadata["bytes"] and sha(raw) == metadata["sha256"]
    for index,(_,raw) in enumerate(restored_records): assert regular_bytes(witness_log/f"{index:08}.record") == raw
    directory_modes = {str(path.relative_to(output)):stat.S_IMODE(path.stat().st_mode)
                       for path in (witness_log,pair,actor_inputs,native)}
    assert all(mode == 0o700 for mode in directory_modes.values())
    result = {"passed":True,"classification":protocol["classification"],"same_retained_R20_world":16,
              "new_independent_task_worlds":0,"actual_Rust_processes":2,"actual_TCP_witness_processes":1,
              "authenticated_tip":list(tip),"authenticated_admission":admission,"final_states":final,
              "native_owner_exit_code":owner.returncode,"native_provider_exit_code":provider_exit,
              "witness_exit_code":witness_exit,"verified_transport_inputs":used,
              "pinned_original_manifest_sha256":sha(pinned),"verified_binary_sha256":sha(raw_binary),
              "controlled_test_log_rehydration_records":len(restored_records),
              "original_tampered_log_unchanged":True,"all_used_transport_bytes_unchanged":True,
              "fresh_private_directory_modes":directory_modes,
              "transport_directory_modes_are_not_admitted_directly":True,
              "public_fixture_key_only":True,"production_log_repair":False,
              "cross_host_or_powerloss_qualification":False,"production_activation":False,
              "source_sha256":sha(Path(__file__).read_bytes()),
              "protocol_sha256":sha((HERE/"TRANSPORT_REPLAY_PROTOCOL.json").read_bytes())}
    with (output/"RESULTS.json").open("x") as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write("\n")
    print(json.dumps({"passed":True,"verified_transport_files":len(used),"native_processes":2,"witness_processes":1},sort_keys=True))


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--transported",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);parser.add_argument("--binary",type=Path)
    args=parser.parse_args();run(args.transported.resolve(),args.output.resolve(),args.binary.resolve() if args.binary else (ROOT/"tools/hcsn/native_runtime_r20_20261101/confirmation01/negative/identical_artifact"))
