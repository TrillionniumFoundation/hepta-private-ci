"""Explicit local MCP artifact sink for one selected task and its private A proposal."""
import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import stat
import time

from . import adoption, data, paired_source

require = adoption.require
SLOTS = ("failure", "correction")
SOURCE = "hepta.paired-learning.selected-session.v1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, limit=131072):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        st = os.fstat(stream.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_size <= limit, "bounded regular original required")
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "oversize original")
    return raw


def obj(path):
    return data._parse(read(path))


def publish(path, raw):
    require(len(raw) <= 131072, "oversize material")
    paired_source._publish_bytes(path, raw)
    require(read(path) == raw, "original bytes changed")


def private(path):
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid() and not st.st_mode & 0o077,
            "owner-private directory required")


def prepare(root, plan):
    keys = {"study", "session", "task", "input", "expected", "policy_sha256", "producer_public_key", "rights_basis"}
    require(set(plan) == keys, "invalid site plan")
    paired_source.sha(plan["study"])
    require((plan["policy_sha256"] is None) == (plan["producer_public_key"] is None),
            "provide both independently registered producer pins or neither")
    if plan["policy_sha256"] is not None:
        paired_source.sha(plan["policy_sha256"])
        paired_source.sha(plan["producer_public_key"])
    for k in ("session", "task", "input", "rights_basis"):
        limit = 32768 if k == "input" else 256
        require(isinstance(plan[k], str) and 0 < len(plan[k].encode()) <= limit, "invalid " + k)
    require(len(data.canonical(plan)) <= 48000, "scope too large")
    token = secrets.token_hex(32)
    scope = {"schema": SOURCE, "plan": plan, "nonce": secrets.token_hex(32), "capability_sha256": sha(token.encode())}
    root.mkdir(mode=0o700)
    for name in ("attempts", "originals"):
        (root / name).mkdir(mode=0o700)
    (root / "lock").touch(mode=0o600, exist_ok=False)
    publish(root / "scope.json", data.canonical(scope))
    return {"scope_sha256": data.digest(scope), "session_capability": token}


@contextmanager
def locked(root, expected):
    for path in (root, root / "attempts", root / "originals"):
        private(path)
    with os.fdopen(os.open(root / "lock", os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        scope = obj(root / "scope.json")
        require(scope["schema"] == SOURCE and data.digest(scope) == expected, "scope or original changed")
        yield scope


def original(root, expected, slot):
    path = root / "attempts"
    meta = obj(path / (slot + ".json"))
    raw = read(path / (slot + ".artifact"), 32768)
    require(meta["scope_sha256"] == expected and meta["slot"] == slot and sha(raw) == meta["text_sha256"],
            "original artifact differs")
    require(os.path.samefile(path / (slot + ".inode"), path / (slot + ".artifact")), "foreign artifact inode")
    intent = {"schema": "hepta.selected-mcp.tool-call.v1", "scope_sha256": expected,
              "tool": "submit_json_artifact", "slot": slot, "artifact_text": raw.decode()}
    require(read(path / (slot + ".intent")) == data.canonical(intent)
            and meta["intent_sha256"] == data.digest(intent), "original selected call changed")
    return meta, raw, intent


def submit(root, expected, token, slot, text):
    require(slot in SLOTS and isinstance(text, str) and 0 < len(text.encode()) <= 32768, "invalid slot or content")
    raw = text.encode()
    with locked(root, expected) as scope:
        require(isinstance(token, str) and hmac.compare_digest(sha(token.encode()), scope["capability_sha256"]),
                "wrong session capability")
        if slot == "correction":
            first, _, _ = original(root, expected, "failure")
            require(not first["semantic_success"], "a failed original must precede correction")
        path = root / "attempts"
        intent = {"schema": "hepta.selected-mcp.tool-call.v1", "scope_sha256": expected,
                  "tool": "submit_json_artifact", "slot": slot, "artifact_text": text}
        require(len(data.canonical(intent)) <= 65536, "encoded tool call too large")
        publish(path / (slot + ".intent"), data.canonical(intent))
        inode = path / (slot + ".inode")
        target = path / (slot + ".artifact")
        publish(inode, raw)
        try:
            os.link(inode, target)
            paired_source.sync_directory(path)
        except FileExistsError:
            require(not target.is_symlink() and os.path.samefile(target, inode), "foreign artifact inode")
        require(read(target, 32768) == raw, "artifact readback differs")
        receipt = path / (slot + ".json")
        if not receipt.exists():
            passed = data._json_artifact({"expected": scope["plan"]["expected"]}, text)["success"]
            publish(receipt, data.canonical({"schema": "hepta.selected-mcp.sink.v1", "scope_sha256": expected,
                    "slot": slot, "intent_sha256": data.digest(intent), "text_sha256": sha(raw),
                    "observed_ns": time.time_ns(), "semantic_success": passed}))
        meta, _, _ = original(root, expected, slot)
        return {"slot": slot, "text_sha256": sha(raw), "effect_sha256": data.digest(meta),
                "semantic_success": meta["semantic_success"], "training": "pending_original_A_consent"}


def statement(scope_sha, plan, slot, text_sha):
    return {"schema": "hepta.selected-mcp.original-producer.v1", "scope_sha256": scope_sha,
            "session": plan["session"], "task": plan["task"], "policy_sha256": plan["policy_sha256"],
            "slot": slot, "text_sha256": text_sha}


def record(root, scope_sha, scope, slot, signed):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    plan = scope["plan"]
    meta, raw, intent = original(root, scope_sha, slot)
    issued = statement(scope_sha, plan, slot, sha(raw))
    require(isinstance(signed, dict) and set(signed) == {"statement", "signature"}
            and signed["statement"] == issued, "mismatched producing-runtime statement")
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(plan["producer_public_key"]))
        key.verify(bytes.fromhex(signed["signature"]), data.canonical(issued))
    except (TypeError, ValueError, InvalidSignature) as exc:
        raise ValueError("invalid producing-runtime signature") from exc
    originals = root / "originals"
    source = data.canonical({"scope": scope, "call": intent, "effect": meta, "issuer_receipt": signed})
    source_sha = sha(source)
    publish(originals / source_sha, source)
    publish(originals / sha(raw), raw)
    action = {"index": 0, "actor": "student", "kind": "action", "executed": False, "content": raw.decode(),
              "receipt_actor": "student", "policy_sha256": plan["policy_sha256"]}
    item = {"schema": data.SCHEMA, "record_id": scope_sha + "/" + slot, "task_id": plan["task"],
            "project_id": plan["study"], "lineage_id": scope_sha, "family_id": "selected-json-artifact",
            "source_id": scope_sha, "split": "train", "exposure": "previously_exposed",
            "origin_kind": "authorized_agent_run", "teacher_id": None,
            "observed_at": meta["observed_ns"], "available_at": meta["observed_ns"],
            "authorization": {"training_allowed": True, "evaluation_allowed": True,
                              "rights_basis": plan["rights_basis"], "scope": "proposal for original A grant"},
            "source": {"repository": "local:selected-session-mcp", "path": slot, "sha256": source_sha,
                       "original_task_id": plan["task"], "operation_id": meta["intent_sha256"]},
            "task": {"input": plan["input"], "verifier": {"name": "json_artifact", "version": "1",
                     "parameters": {"expected": plan["expected"]}}}, "final_answer": raw.decode(), "trajectory": [action]}
    semantic = data.verify_answer(item, raw.decode())
    require(semantic["success"] == meta["semantic_success"] == (slot == "correction"),
            "actual sink does not show a failure followed by success")
    publish(originals / semantic["receipt_sha256"], data.canonical(semantic))
    effect = {"schema": "hepta.paired-learning.artifact-readback.v1", "record_id": item["record_id"],
              "task_id": plan["task"], "actor": "student", "source_sha256": source_sha,
              "input_sha256": paired_source.text_sha(plan["input"]), "policy_sha256": plan["policy_sha256"],
              "readback_sha256": sha(raw), "semantic_receipt_sha256": semantic["receipt_sha256"]}
    effect_sha = data.digest(effect)
    publish(originals / effect_sha, data.canonical(effect))
    action.update(executed=True, receipt_sha256=effect_sha)
    item["verified_outcome"] = {"success": semantic["success"], "receipt_sha256": semantic["receipt_sha256"],
                                "verifier_name": "json_artifact", "verifier_version": "1"}
    paired_source.check_attempt(item, slot == "correction", originals)
    return item


def handoff(root, expected, issued):
    with locked(root, expected) as scope:
        if scope["plan"]["producer_public_key"] is None:
            return {"status": "Pending", "reason": "producer and policy not independently registered"}
        if not isinstance(issued, dict) or set(issued) != set(SLOTS) or any(
                not (root / "attempts" / (s + ".json")).is_file() for s in SLOTS):
            return {"status": "Pending", "reason": "missing effect or producing-runtime receipt"}
        records = [record(root, expected, scope, slot, issued[slot]) for slot in SLOTS]
        paired_source.derive(*records, root / "originals")
        consent = {"study_sha256": scope["plan"]["study"], "scope": {"use": "train"}}
        for slot, item in zip(SLOTS, records, strict=True):
            publish(root / (slot + ".json"), data.canonical(item) + b"\n")
            consent["scope"][slot] = data.digest(item)
        publish(root / "proposed-scope.json", data.canonical(consent))
        return {"status": "PendingOriginalAConsent", **consent}


def serve(root, scope_sha):
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    server = Server("selected-session-json-artifact")
    tool = types.Tool(name="submit_json_artifact", description="Write and read back a fixed local artifact slot.",
                      inputSchema={"type": "object", "additionalProperties": False,
                      "required": ["session_capability", "slot", "artifact_text"], "properties": {
                          "session_capability": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                          "slot": {"type": "string", "enum": list(SLOTS)},
                          "artifact_text": {"type": "string", "minLength": 1, "maxLength": 32768}}})

    @server.list_tools()
    async def available():
        return [tool]

    @server.call_tool()
    async def execute(name, arguments):
        require(name == tool.name, "unknown tool")
        return submit(root, scope_sha, arguments["session_capability"], arguments["slot"], arguments["artifact_text"])

    async def run():
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())

    asyncio.run(run())


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    for mode in ("prepare", "serve", "handoff"):
        p = modes.add_parser(mode)
        p.add_argument("private_directory", type=Path)
        if mode == "prepare":
            p.add_argument("site_plan", type=Path)
        else:
            p.add_argument("scope_sha256")
        if mode == "handoff":
            p.add_argument("receipts", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        print(data.canonical(prepare(args.private_directory, obj(args.site_plan))).decode())
    elif args.mode == "serve":
        serve(args.private_directory, args.scope_sha256)
    else:
        print(data.canonical(handoff(args.private_directory, args.scope_sha256, obj(args.receipts))).decode())


if __name__ == "__main__":
    main()
