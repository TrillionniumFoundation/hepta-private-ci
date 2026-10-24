"""Public black-box API adapter. This program is NOT a security boundary.

For model-produced candidates the operator must launch it inside an admitted
OS sandbox containing no hidden tests/expected values/reference solutions.
The trusted grader remains outside that sandbox. It compares observations;
it never imports the candidate. No expected answer is part of this adapter.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

PROTOCOL = "hepta.native-ab.observation.v1"
MAX_REQUEST_BYTES = 131072


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def observe(function, *args):
    try:
        return function(*args)
    except UnicodeError:
        return {"error": "UnicodeError"}
    except ValueError:
        return {"error": "ValueError"}
    except OSError:
        return {"error": "OSError"}
    except Exception as error:
        return {"error": type(error).__name__}


def decode_overlay(value, sentinel):
    if isinstance(value, dict):
        if value == {"$delete": True}:
            return sentinel
        return {key: decode_overlay(child, sentinel) for key, child in value.items()}
    if isinstance(value, list):
        return [decode_overlay(child, sentinel) for child in value]
    return value


def encode_overlay(value, sentinel):
    if value is sentinel:
        return {"$delete": True}
    if isinstance(value, dict):
        return {key: encode_overlay(child, sentinel) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_overlay(child, sentinel) for child in value]
    return value


def mutable_ids(value):
    if isinstance(value, dict):
        result = {id(value)}
        for child in value.values():
            result.update(mutable_ids(child))
        return result
    if isinstance(value, list):
        result = {id(value)}
        for child in value:
            result.update(mutable_ids(child))
        return result
    return set()


def dispatch(module, task, payload):
    if task == "stream_frames":
        instance = module.ByteFramer(payload["max_payload"])
        result = {"feeds": []}
        for chunk in payload["chunks"]:
            value = observe(instance.feed, bytes.fromhex(chunk))
            if isinstance(value, list):
                value = [item.hex() for item in value]
            result["feeds"].append(value)
        if payload.get("finish"):
            result["finish"] = observe(instance.finish)
        return result
    if task == "stream_lines":
        instance = module.Utf8Lines()
        result = {"feeds": [observe(instance.feed, bytes.fromhex(chunk))
                            for chunk in payload["chunks"]]}
        if payload.get("finish"):
            result["finish"] = observe(instance.finish)
        if payload.get("after_finish"):
            result["after_feed"] = observe(instance.feed, b"x")
            result["after_finish"] = observe(instance.finish)
        return result
    if task == "state_schedule":
        instance = module.ScheduleQueue()
        result = []
        for operation in payload["ops"]:
            if operation[0] not in ("schedule", "cancel", "pop_due"):
                raise ValueError("unknown queue operation")
            result.append(observe(getattr(instance, operation[0]), *operation[1:]))
        return result
    if task == "state_window":
        instance = module.WindowLimiter(payload["capacity"], payload["window"])
        return [observe(instance.allow, *operation) for operation in payload["ops"]]
    if task == "transform_overlay":
        base = decode_overlay(payload["base"], module.DELETE)
        override = decode_overlay(payload["override"], module.DELETE)
        before = canonical(encode_overlay([base, override], module.DELETE))
        original_ids = mutable_ids(base) | mutable_ids(override)
        result = module.merge(base, override)
        return {"result": encode_overlay(result, module.DELETE),
                "inputs_unchanged": before == canonical(encode_overlay([base, override], module.DELETE)),
                "no_mutable_aliases": not bool(original_ids & mutable_ids(result))}
    if task == "transform_intervals":
        values = copy.deepcopy(payload["intervals"])
        before = copy.deepcopy(values)
        provided = (item for item in values) if payload.get("as_generator") else values
        result = module.normalize(provided)
        return {"result": result,
                "list_of_tuples": isinstance(result, list) and all(type(item) is tuple for item in result),
                "input_unchanged": values == before}
    if task == "durable_store":
        with tempfile.TemporaryDirectory(prefix="ab-store-", dir=".") as directory:
            path = Path(directory) / "state.json"
            store = module.JsonStore(path)
            snapshot = None
            result = []
            for operation in payload["ops"]:
                action = operation[0]
                if action == "load":
                    value = observe(store.load)
                elif action == "commit":
                    value = observe(store.commit, *operation[1:])
                elif action == "snapshot":
                    snapshot = path.read_bytes() if path.exists() else None
                    value = path.exists()
                elif action == "matches_snapshot":
                    value = (path.read_bytes() if path.exists() else None) == snapshot
                elif action == "files":
                    value = sorted(item.name for item in path.parent.iterdir())
                elif action == "corrupt":
                    path.write_text(operation[1], encoding="utf-8")
                    value = None
                elif action == "fail_replace":
                    original = os.replace
                    def fail_replace(*args, **kwargs):
                        raise OSError("injected replace failure")
                    os.replace = fail_replace
                    try:
                        value = observe(store.commit, *operation[1:])
                    finally:
                        os.replace = original
                else:
                    raise ValueError("unknown store operation")
                result.append(value)
            return result
    if task == "durable_journal":
        raw = bytes.fromhex(payload["hex"]) if "hex" in payload else payload["text"].encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="ab-journal-", dir=".") as directory:
            path = Path(directory) / "events.jsonl"
            path.write_bytes(raw)
            result = module.read_journal(path)
            return {"records": result, "bytes_unchanged": path.read_bytes() == raw}
    raise ValueError("unknown task")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    path = Path(args.candidate)
    source = path.read_bytes()
    if len(source) > 65536:
        raise ValueError("candidate source exceeds the registered 64 KiB limit")
    candidate_sha = hashlib.sha256(source).hexdigest()
    spec = importlib.util.spec_from_file_location("repair_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for raw in sys.stdin.buffer:
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds limit")
        request = json.loads(raw)
        if request.get("schema") != "hepta.native-ab.case-request.v1":
            raise ValueError("wrong request schema")
        input_sha = hashlib.sha256(canonical(request["input"])).hexdigest()
        if input_sha != request["input_sha256"]:
            raise ValueError("input digest mismatch")
        observed = observe(dispatch, module, request["slug"], request["input"])
        response = {"schema": PROTOCOL, "task_id": request["task_id"], "slug": request["slug"],
                    "case_id": request["case_id"], "input_sha256": input_sha,
                    "candidate_sha256": candidate_sha, "observed": observed}
        sys.stdout.buffer.write(canonical(response) + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
