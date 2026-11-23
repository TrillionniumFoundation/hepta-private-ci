"""Exercise an explicitly selected local SDK client over the real MCP stdio transport."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from cell_experiments import data, paired_source, selected_session_mcp as adapter


def check(value, why):
    if not value:
        raise AssertionError(why)


def refuses(callback, reason):
    try:
        callback()
    except (ValueError, OSError) as exc:
        check(reason in str(exc), str(exc))
    else:
        raise AssertionError("negative control was accepted")


async def run(root):
    key = Ed25519PrivateKey.generate()
    plan = {
        "study": data.digest(["engineering-fixture", 1]), "session": "selected-test-client",
        "task": "count-two", "input": "Return an object with count equal to the number of entries in [2, 3].",
        "expected": {"count": 2}, "policy_sha256": adapter.sha(Path(__file__).read_bytes()),
        "producer_public_key": key.public_key().public_bytes_raw().hex(),
        "rights_basis": "locally authored engineering task; zero enrolled people",
    }
    unbound = root.with_name("unbound")
    u = adapter.prepare(unbound, {**plan, "policy_sha256": None, "producer_public_key": None})
    adapter.submit(unbound, u["scope_sha256"], u["session_capability"], "failure", "0")
    check(adapter.handoff(unbound, u["scope_sha256"], {})["status"] == "Pending" and
          not (unbound / "failure.json").exists(), "unidentified producer admitted")
    grant = adapter.prepare(root, plan)
    token, scope_sha = grant["session_capability"], grant["scope_sha256"]
    statements, calls = {}, []
    params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "cell_experiments.selected_session_mcp",
                                   "serve", str(root), scope_sha], env={"PYTHONPATH": os.environ["PYTHONPATH"]})
    async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
        await client.initialize()
        check([t.name for t in (await client.list_tools()).tools] == ["submit_json_artifact"], "unexpected tools")

        async def call(slot, text, **extras):
            return await client.call_tool("submit_json_artifact", {
                "session_capability": token, "slot": slot, "artifact_text": text, **extras})

        invalid = [await call("failure", "0", session_capability="0"*64),
                   await call("failure", "0", path="../../somewhere"), await call("failure", "0", command="no"),
                   await call("correction", "0")]
        check(all(v.isError for v in invalid) and not list((root / "attempts").iterdir()), "invalid request mutated sink")
        rows = [2, 3]
        for slot in adapter.SLOTS:
            if slot == "failure":
                count = len(rows[1:])
            else:
                check(calls[-1]["semantic_success"] is False, "missing real negative feedback")
                count = len(rows)
            text = json.dumps({"count": count}, separators=(",", ":")) + "\n"
            original = adapter.statement(scope_sha, plan, slot, adapter.sha(text.encode()))
            statements[slot] = {"statement": original, "signature": key.sign(data.canonical(original)).hex()}
            result = await call(slot, text)
            check(not result.isError, str(result.content))
            observed = json.loads(result.content[0].text)
            check(observed["semantic_success"] == (slot == "correction"), "unexpected outcome")
            calls.append(observed)
            again = await call(slot, text)
            check(not again.isError and json.loads(again.content[0].text) == observed, "retry changed original")
            check((await call(slot, text + " ")).isError, "different retry replaced original")
    check(adapter.handoff(root, scope_sha, {})["status"] == "Pending"
          and not (root / "failure.json").exists(), "unsigned material admitted")
    swapped = json.loads(json.dumps(statements))
    swapped["correction"]["signature"] = swapped["failure"]["signature"]
    refuses(lambda: adapter.handoff(root, scope_sha, swapped), "invalid producing-runtime signature")
    other = json.loads(json.dumps(statements))
    other["failure"]["statement"]["session"] = "another"
    refuses(lambda: adapter.handoff(root, scope_sha, other), "mismatched producing-runtime statement")
    proposal = adapter.handoff(root, scope_sha, statements)
    check(proposal["status"] == "PendingOriginalAConsent", "proposal became authorization")
    records = [adapter.obj(root / (slot + ".json")) for slot in adapter.SLOTS]
    derived = paired_source.derive(*records, root / "originals")
    check(derived["final_answer"] == '{"count":2}\n' and all(data.digest(rec) == proposal["scope"][slot]
          for slot, rec in zip(adapter.SLOTS, records, strict=True)), "original paired_source rejected records")
    artifact = root / "attempts/correction.artifact"
    original = artifact.read_bytes()
    artifact.write_bytes(b"altered")
    refuses(lambda: adapter.handoff(root, scope_sha, statements), "original artifact differs")
    artifact.write_bytes(original)
    denial = subprocess.run([sys.executable, "-B", "-m", "cell_experiments.paired_source_train",
                             *(["unavailable"]*8)], close_fds=True, capture_output=True, timeout=30)
    check(denial.returncode != 0 and b"Bad file descriptor" in denial.stderr, "missing owner handles accepted")
    readout = {"scope": "engineering_fixture", "actor": "authored offline SDK client",
               "issuer_validation": "Ed25519 signature under operator-selected key only",
               "external_enrollments_verified_by_adapter": 0, "vendor_model_or_identity_verified": False,
               "adapter_sha256": adapter.sha(Path(adapter.__file__).read_bytes()),
               "paired_source_sha256": adapter.sha(Path(paired_source.__file__).read_bytes()),
               "tool_calls": calls, "proposal": proposal, "native_training_without_owner_handles": "denied",
               "native_original_A_grants": 0, "real_people": 0, "trained_models": 0, "payments": 0,
               "controls": ["wrong session", "arbitrary path", "arbitrary command", "reversed arrival",
                            "idempotent retry", "different retry", "missing producer receipt", "swapped signature",
                            "wrong producing session", "altered output", "unregistered producer"]}
    adapter.publish(root / "producer-receipts.json", data.canonical(statements))
    adapter.publish(root / "READOUT.json", data.canonical(readout))
    print(json.dumps(readout, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "capture"
        asyncio.run(run(root))
        if args.archive:
            names = ["scope.json", "producer-receipts.json", "proposed-scope.json", "READOUT.json",
                     "failure.json", "correction.json"]
            names += [str(p.relative_to(root)) for p in (root / "originals").iterdir()]
            names += [str(p.relative_to(root)) for p in (root / "attempts").iterdir() if p.suffix != ".inode"]
            with zipfile.ZipFile(args.archive, "x", compression=zipfile.ZIP_DEFLATED) as out:
                for name in sorted(names):
                    out.write(root / name, name)
            print("selected-session-originals", args.archive.stat().st_size, adapter.sha(args.archive.read_bytes()))


if __name__ == "__main__":
    main()
