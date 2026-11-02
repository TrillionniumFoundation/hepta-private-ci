"""Generation transactions around the real Rust owner; no external-effect once claim.

Only a fully durable child generation is published. Unprepared child failures
are quarantined, prepared IO receipts are reused, and a lost publication reply
is recovered by the same request id and parent ACK. Before a durable IO receipt,
read-only packet opens/FullHX execution may repeat. Published task fees do not.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".write-", delete=False) as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, path); sync_directory(path.parent)


def identity(config):
    return dict(schema="joint-native-generation-identity-v1", controller=config["controller"], seed=config["seed"],
                mode="qualification", files={name: digest(config[name]) for name in ("binary", "public", "policy", "content")},
                coordinator_sha256=digest(__file__))


def validate(directory, ack, expected):
    manifest_path = directory/"manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if digest(manifest_path) != ack or manifest["identity"] != expected:
        raise ValueError("generation ACK or source identity mismatch")
    payload = directory/"payload"
    if payload.is_symlink() or any(x.is_symlink() or not x.is_file() for x in payload.iterdir()):
        raise ValueError("regular generation payload required")
    actual = {x.name: digest(x) for x in payload.iterdir()}
    if actual != manifest["payload"] or digest(directory/"result.json") != manifest["result_sha256"]:
        raise ValueError("generation payload or IO receipt changed")
    result = json.loads((directory/"result.json").read_bytes())
    if result["acknowledged_sha256"] != digest(payload/"owner.json"):
        raise ValueError("child native ACK mismatch")
    return manifest, result


def crash(stage, requested):
    if requested == stage:
        os._exit(87)


def transact(root, config, request_id, ack, steps, fault=None, initialize=False):
    if not 1 <= len(request_id) <= 128 or (not initialize and not 1 <= steps <= 7):
        raise ValueError("bounded request id and action count required")
    if not initialize and (not isinstance(ack, str) or len(ack) != 64 or set(ack)-set("0123456789abcdef")):
        raise ValueError("external generation ACK required")
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True, mode=0o700)
    expected = identity(config)
    with (root/"LOCK").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        generations = root/"generations"; generations.mkdir(exist_ok=True)
        current = root/"CURRENT.json"
        parent, parent_result = None, None
        if current.exists():
            current_ack = json.loads(current.read_bytes())["ack"]
            if len(current_ack) != 64 or set(current_ack)-set("0123456789abcdef"):
                raise ValueError("invalid current generation pointer")
            parent, parent_result = validate(generations/current_ack, current_ack, expected)
            if initialize:
                raise ValueError("existing generation requires external ACK")
            if parent["request_id"] == request_id and parent["parent_ack"] == ack:
                if parent["steps"] != steps:
                    raise ValueError("committed request contract differs")
                return dict(ack=current_ack, request_id=request_id, duplicate=True, recovered_prepared=False, result=parent_result)
            if ack != current_ack:
                raise ValueError("external ACK is missing, stale or mismatched")
            cursor = parent
            for _ in range(8):
                if cursor["request_id"] == request_id:
                    raise ValueError("request id cannot be reused for another transition")
                if cursor["parent_ack"] is None:
                    break
                cursor, _ = validate(generations/cursor["parent_ack"], cursor["parent_ack"], expected)
            else:
                raise ValueError("generation depth exceeds task bound")
            if parent_result["after"]["task"]["terminal"]:
                raise ValueError("task already terminated")
        elif not initialize or ack is not None:
            raise ValueError("only explicit genesis may omit the external ACK")
        key = hashlib.sha256(encoded(dict(request_id=request_id, parent_ack=ack))).hexdigest()
        stage = root/("staging-"+key)
        prepared = False
        if not (stage/"manifest.json").exists():
            children = list(generations.iterdir())
            if len(children) > 40:
                raise ValueError("bounded prepared-generation allowance exhausted")
            matches = []
            for directory in children:
                candidate = json.loads((directory/"manifest.json").read_bytes())
                if candidate["request_id"] == request_id and candidate["parent_ack"] == ack:
                    matches.append(directory)
            if len(matches) > 1:
                raise ValueError("ambiguous prepared generation")
            if matches:
                stage = matches[0]
        if stage.exists() and (stage/"manifest.json").exists():
            candidate_ack = digest(stage/"manifest.json")
            manifest, result = validate(stage, candidate_ack, expected)
            if manifest["request_id"] != request_id or manifest["parent_ack"] != ack or manifest["steps"] != steps:
                raise ValueError("prepared request contract differs")
            prepared = True
        else:
            if stage.exists():
                if len(list(root.glob("abandoned-*"))) >= 32:
                    raise ValueError("bounded abandoned-attempt allowance exhausted")
                os.rename(stage, root/("abandoned-"+uuid.uuid4().hex)); sync_directory(root)
            stage.mkdir(mode=0o700)
            save(stage/"intent.json", dict(request_id=request_id, parent_ack=ack, identity=expected, steps=steps))
            payload = stage/"payload"
            if parent is None:
                payload.mkdir()
            else:
                shutil.copytree(generations/ack/"payload", payload)
            command = [str(config["binary"]), "--public", str(config["public"]), "--policy", str(config["policy"]),
                       "--content-model", str(config["content"]), "--controller", config["controller"],
                       "--seed", str(config["seed"]), "--mode", "qualification", "--steps", str(steps),
                       "--snapshot", str(payload/"owner.json")]
            if parent_result is not None:
                command += ["--ack", parent_result["acknowledged_sha256"]]
            env = dict(os.environ); env.pop("HEPTA_JOINT_CRASH_AT", None)
            if fault in ("after_native_tick", "after_due_read", "after_child_commit"):
                env["HEPTA_JOINT_CRASH_AT"] = fault
            process = subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)
            save(stage/"child_process.json", dict(command=command, returncode=process.returncode, stdout=process.stdout, stderr=process.stderr))
            if process.returncode:
                raise RuntimeError("unpublished native child failed; acknowledged generation unchanged")
            result = json.loads(process.stdout)
            if not result["actual_native"] or result["production_activation"] or result["forced_control"] or result["authority"] != "DENY_ALL":
                raise ValueError("unexpected child execution authority")
            save(stage/"result.json", result)
            files = {}
            for path in payload.iterdir():
                if path.is_symlink() or not path.is_file():
                    raise ValueError("regular native store files required")
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
                files[path.name] = digest(path)
            sync_directory(payload)
            manifest = dict(schema="joint-native-generation-v1", request_id=request_id, parent_ack=ack,
                            identity=expected, steps=steps, payload=files, result_sha256=digest(stage/"result.json"))
            save(stage/"manifest.json", manifest)
            candidate_ack = digest(stage/"manifest.json")
            validate(stage, candidate_ack, expected)
        crash("after_io_receipt", fault)
        destination = generations/candidate_ack
        if destination.exists():
            validate(destination, candidate_ack, expected)
        else:
            os.rename(stage, destination); sync_directory(generations); sync_directory(root)
        crash("after_generation_move", fault)
        save(current, dict(ack=candidate_ack))
        crash("after_publish", fault)
        return dict(ack=candidate_ack, request_id=request_id, duplicate=False, recovered_prepared=prepared, result=result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=("init", "step")); p.add_argument("--root", type=Path, required=True)
    for name in ("binary", "public", "policy", "content"):
        p.add_argument("--"+name, type=Path, required=True)
    p.add_argument("--controller", choices=("fixed", "value", "structured_value"), required=True)
    p.add_argument("--seed", type=int, required=True); p.add_argument("--request-id", required=True)
    p.add_argument("--ack"); p.add_argument("--steps", type=int, default=1)
    p.add_argument("--fault", choices=("after_native_tick", "after_due_read", "after_child_commit", "after_io_receipt", "after_generation_move", "after_publish"))
    a = p.parse_args(); config = {k: getattr(a, k) for k in ("binary", "public", "policy", "content", "controller", "seed")}
    output = transact(a.root, config, a.request_id, a.ack, 0 if a.operation == "init" else a.steps,
                      a.fault, a.operation == "init")
    print(json.dumps(output, sort_keys=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
