"""Observe only the original five event waits in the detached-session integration test."""

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from xml.etree import ElementTree

TEST = Path("codex-rs/exec-server/tests/process.rs")
TEST_NAME = "exec_server_resumes_detached_session_without_killing_processes"
SOURCE = "7414417781eff69bf9cfdb84767ec8c29d101068"
WAITS = ["initialize_id", "process_start_id", "resume_initialize_id", "process_read_id", "terminate_id"]


def instrument(path):
    original = path.read_text(encoding="utf-8")
    raw = original.encode()
    git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if git_sha != SOURCE:
        raise ValueError(f"incorrect original fixture {git_sha}")
    before, header, fixture = original.partition(f"async fn {TEST_NAME}()")
    if not header or fixture.count(".wait_for_event(|event| {") != len(WAITS):
        raise ValueError("unrecognized source shape")
    for request in WAITS:
        selector = f"id == &{request}"
        match = (
            "            matches!(\n"
            "                event,\n"
            f"                JSONRPCMessage::Response(JSONRPCResponse {{ id, .. }}) if {selector}\n"
            "            )\n"
            "        })\n"
            "        .await?;"
        )
        if fixture.count(match) != 1:
            raise ValueError(f"missing unique wait for {request}")
        trace = (
            "            if let JSONRPCMessage::Error(reply) = event\n"
            f"                && reply.id == {request}\n"
            "            {\n"
            '                eprintln!(\n'
            f'                    "WRESUME wait={request} rpc_code={{}} active_owner={{}}",\n'
            '                    reply.error.code,\n'
            '                    reply.error.message.contains("is already attached to another connection"),\n'
            '                );\n'
            "            }\n"
        )
        contextual = match.replace(
            "        .await?;",
            f'        .await\n        .map_err(|error| error.context("WRESUME wait={request}"))?;',
        )
        fixture = fixture.replace(match, trace + contextual, 1)
    path.write_bytes((before + header + fixture).encode())


def collect(lane, repeat, code):
    root = Path(os.environ["BAZEL_OUTPUT_BASE"]) / "execroot"
    dest = Path(os.environ["RUNNER_TEMP"]) / "resume-observation" / f"{lane}-{repeat}"
    dest.mkdir(parents=True, exist_ok=False)
    matches = list(root.glob("*/bazel-out/*/testlogs/codex-rs/exec-server/exec-server-process-test/test.log"))
    if len(matches) != 1:
        raise ValueError(f"expected one test.log, found {len(matches)}")
    log = matches[0]
    xml = log.with_suffix(".xml")
    ElementTree.parse(xml)
    raw = log.read_bytes()
    contents = raw.decode("utf-8", errors="replace").splitlines()
    cases = dict(re.findall(r"^test ([\w:]+) \.\.\. (ok|FAILED|ignored)$", "\n".join(contents), re.M))
    if len(cases) != 6 or TEST_NAME not in cases:
        raise ValueError(f"incomplete case roster {cases}")
    failed = any(value != "ok" for value in cases.values())
    if failed != (int(code) != 0):
        raise ValueError("runner exit disagrees with test cases")
    report = {
        "lane": lane, "repeat": int(repeat), "bazel_exit": int(code), "cases": cases,
        "log_sha256": hashlib.sha256(raw).hexdigest(), "xml_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
        "stages": [line for line in contents if "WRESUME" in line],
        "summaries": [line for line in contents if line.startswith("test result:")],
    }
    shutil.copy2(log, dest / "test.log")
    shutil.copy2(xml, dest / "test.xml")
    (dest / "observation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    if sys.argv[1] == "instrument":
        instrument(TEST)
    elif sys.argv[1] == "collect":
        collect(*sys.argv[2:])
    else:
        raise ValueError("expected instrument or collect")
