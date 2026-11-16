#!/usr/bin/env python3
"""Read retained runtime evidence only; execute no model, native image or runtime."""

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import tarfile

CANDIDATE = "2a8e8759c7e1941f184fde2463a13a9d39dfa9edcf00c8a5ae475ad81dd3b469"
CONFIG = "96eaab9f5b76aef9ac5fcac6b32ca1be663e7a0d55e999dad89899c35317f9e5"
BUILD = "90f73f4c611f177e2fc94227f8845b5308df9370502ffc1896b65c939207389d"
COMMIT = "5f7f03a1f22905789371ce0e181a1a0f013beca9"
TREE = "7e5e3864aa303a8bc7c3a8d2262a46c76efa6e4a"
BINARY = "a8cfa33fe6c69175a9653197fb7094a572d623fe2b934e7926da28e35301f2bf"
CELL_COMMIT = "12cd0514c7936955e090af88a35ee1237def2b7c"
HARNESS = "9b1e122e8b1e5487f891db904093954176d654afe50bba6c2c1480f36ec39e0e"
HELPERS = {
    "runtime_process_bridge.py": "25ec3fcec67af03ebc19f3e6b500c9f0cd8f6feb1c260f54f40b3b8e128131f4",
    "runtime_process_contract.py": "05a8d5fae86d20810df4dda5dd64ffa63645a30e723fe16b96fc469e1714a542",
    "runtime_stdio.py": "cccbd3796b59ba6b89b4030dbcb16a626f378ec477520765a859e040c3ebcfda",
}
ARCHIVES = {
    "controller": "1fbe62e63c22efd220fee2b62e5a8306e578f706bff201350f185eee89d52252",
    "worker": "a1dec072ac89676af62b6e37b676b3ff5958a806793e0c239a59d264292c374a",
}
PATTERNS = {
    "private_key_pem": rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    "pgp_private_key": rb"-----BEGIN PGP PRIVATE KEY BLOCK-----",
    "putty_private_key": rb"PuTTY-User-Key-File-[23]:[\s\S]{0,8192}Private-Lines:",
    "github_token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{20,255})\b",
    "aws_access_key_id": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "slack_token": rb"\bxox[baprs]-[A-Za-z0-9-]{10,200}\b",
    "stripe_secret": rb"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,200}\b",
    "openai_token": rb"\bsk-(?:(?:proj|svcacct)-)?[A-Za-z0-9_-]{20,200}\b",
    "google_api_key": rb"\bAIza[A-Za-z0-9_-]{35}\b",
    "sendgrid_api_key": rb"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b",
    "jwt_candidate": rb"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{16,}\b",
    "quoted_secret_assignment": rb"""(?i)["']?(?:token|secret|bearer[_-]?token|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|authorization|client[_-]?secret|private[_-]?key|password|passwd|secret[_-]?key)["']?\s*[:=]\s*["']([^"'\r\n]{8,300})["']""",
    "bare_secret_assignment": rb"(?im)^\s*(?:token|secret|bearer[_-]?token|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|secret[_-]?key)\s*[:=]\s*(?:Bearer\s+)?[A-Za-z0-9._~+/-]{16,}=*\s*$",
    "authorization_header": rb"(?i)(?:Authorization|Proxy-Authorization)\s*:\s*(?:Bearer|token|Basic)\s+[A-Za-z0-9._~+/-]{12,}=*",
    "url_credential_parameter": rb"(?i)[?&](?:access_token|token|api_key|signature|sig|X-Amz-Signature)=[A-Za-z0-9%+/_=.-]{16,}",
}


def need(condition, label):
    if not condition:
        raise ValueError(label)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def raw(path):
    need(path.is_file() and not path.is_symlink(), "nonregular evidence: " + path.name)
    need(path.stat().st_size <= 64 * 1024 * 1024, "evidence file exceeds bound")
    return path.read_bytes()


def document(path):
    return parse(raw(path))


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        need(not path.is_symlink(), "symlink in evidence")
        if path.is_file():
            data = raw(path)
            result[str(path.relative_to(root))] = {
                "sha256": sha(data),
                "size": len(data),
            }
    return result


def archive_review(root):
    findings, archives = [], []
    for side, expected in ARCHIVES.items():
        path = root.parent / ("actual-runtime-v4-" + side + "-evidence.tar.gz")
        need(sha(raw(path)) == expected, "archive digest: " + side)
        members, total = set(), 0
        with tarfile.open(path) as archive:
            for member in archive:
                need(
                    member.isfile() and member.name not in members,
                    "archive member type or duplicate",
                )
                location = (root / member.name).resolve(strict=True)
                need(
                    location.is_relative_to(root)
                    and member.name.startswith(side + "/"),
                    "archive member path",
                )
                data = archive.extractfile(member).read()
                need(
                    data == raw(location),
                    "archive/extracted bytes differ: " + member.name,
                )
                members.add(member.name)
                total += len(data)
                for kind, pattern in PATTERNS.items():
                    count = 0
                    for match in re.finditer(pattern, data):
                        if kind == "jwt_candidate":
                            try:
                                parts = match.group().split(b".")
                                header = parse(
                                    base64.urlsafe_b64decode(
                                        parts[0] + b"=" * (-len(parts[0]) % 4)
                                    )
                                )
                                parse(
                                    base64.urlsafe_b64decode(
                                        parts[1] + b"=" * (-len(parts[1]) % 4)
                                    )
                                )
                                if not isinstance(header, dict) or "alg" not in header:
                                    continue
                            except (ValueError, UnicodeError):
                                continue
                        count += 1
                    if count:
                        findings.append(
                            {"type": kind, "path": member.name, "count": count}
                        )
        index_name = "actual-runtime-v4-" + side + "-index.json"
        index = document(root / side / index_name)
        actual = inventory(root / side)
        actual.pop(index_name)
        need(actual == index["files"], "archive source index: " + side)
        need(
            members == {side + "/" + p for p in [index_name, *actual]},
            "archive member inventory",
        )
        archives.append(
            {
                "side": side,
                "sha256": expected,
                "files": len(members),
                "uncompressed_bytes": total,
            }
        )
    return {
        "archives": archives,
        "patterns": sorted(PATTERNS),
        "findings": findings,
        "scope": "Known byte patterns only; no credential use or secret values printed.",
    }


def identity_review(root, source_receipts):
    lane = root / "controller/lane-v4"
    candidate_bytes = raw(root / "controller/candidate-v4-bound.json")
    need(sha(candidate_bytes) == CANDIDATE, "candidate anchor")
    candidate, result = parse(candidate_bytes), document(lane / "RESULT.json")
    pins = document(root / "controller/runtime-pins-v2.json")
    need(
        pins
        == document(root / "worker/runtime-pins-v2.json")
        == candidate["runtime_identity"]
        == result["runtime_identity"],
        "runtime pins binding",
    )
    need(
        (
            pins["source_commit"],
            pins["source_tree"],
            pins["binary_sha256"],
            pins["config_sha256"],
        )
        == (COMMIT, TREE, BINARY, CONFIG),
        "runtime identity anchors",
    )
    need(
        sha(raw(root / "controller/runtime-config-v2.json")) == CONFIG, "config anchor"
    )
    need(
        result["status"] == "PASS" and result["candidate_sha256"] == CANDIDATE,
        "lane result binding",
    )
    need(result["actual_runtime_transport"] is True, "retained runtime transport claim")
    for name in (
        "ordinary_daemon_qualification",
        "independent_real_task_benefit",
        "final_use_capability_boundary_qualified",
    ):
        need(result[name] is False, "scope boundary: " + name)
    build_bytes = raw(root / "controller/build-receipt-v4.json")
    need(
        sha(build_bytes) == BUILD == result["build_receipt_sha256"],
        "build receipt anchor",
    )
    build = parse(build_bytes)
    need(
        build["status"] == "PASS" and build["source_status"] == "",
        "build status/clean source",
    )
    need(
        (build["source_commit"], build["head"], build["tree"], build["binary_sha256"])
        == (COMMIT, COMMIT, TREE, BINARY),
        "build identity",
    )
    commands = []
    for command in build["commands"]:
        label = command["label"]
        need(
            command["exit_code"] == 0 and command["timed_out"] is False,
            "build command terminal: " + label,
        )
        for stream in ("stdout", "stderr"):
            need(
                sha(raw(root / "controller" / ("v4-" + label + "." + stream)))
                == command[stream + "_sha256"],
                "build command stream: " + label,
            )
        commands.append(label)
    need(len(commands) == len(set(commands)) == 10, "build command population")
    for label, expected in (("git-head", COMMIT), ("git-tree", TREE)):
        need(
            raw(root / "controller" / ("v4-" + label + ".stdout")).decode().strip()
            == expected,
            "git identity output",
        )
    for label in ("git-clean-before", "git-status"):
        need(
            raw(root / "controller" / ("v4-" + label + ".stdout")) == b"",
            "clean source output",
        )
    receipts = document(source_receipts)
    need(
        receipts["commit"] == CELL_COMMIT
        and receipts["tree"] == "8dd179d3c462a7aeb4b5d6bc653ea699d8dd71eb",
        "fixed helper source commit/tree",
    )
    need(result["helpers"] == HELPERS, "helper result pins")
    files = {
        (item["root"], item["path"]): item["sha256"] for item in candidate["files"]
    }
    need(len(files) == len(candidate["files"]), "duplicate candidate file record")
    helper_root = root / "controller/controller-bundle-v4/portable-v4/cells"
    need(len(receipts["files"]) == len(HELPERS), "helper source receipt population")
    for item in receipts["files"]:
        name, data = Path(item["path"]).name, raw(helper_root / item["path"])
        need(
            item["sha256"]
            == sha(data)
            == HELPERS[name]
            == files[("cells", item["path"])],
            "helper source bytes: " + name,
        )
        need(len(data) == item["bytes"], "helper source size")
        need(
            hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            == item["git_blob_sha1"],
            "helper real Git blob",
        )
    need(
        sha(raw(helper_root / "scripts/run_configured_cell_lane.py"))
        == HARNESS
        == result["harness_sha256"],
        "retained harness anchor",
    )
    return (
        candidate,
        result,
        pins,
        {
            "candidate_sha256": CANDIDATE,
            "runtime_commit": COMMIT,
            "runtime_tree": TREE,
            "runtime_binary_receipted_sha256": BINARY,
            "runtime_config_sha256": CONFIG,
            "build_receipt_sha256": BUILD,
            "build_commands_verified": commands,
            "helper_source_commit": CELL_COMMIT,
            "helpers": HELPERS,
            "harness_sha256": HARNESS,
            "source_receipts_sha256": sha(raw(source_receipts)),
            "binary_scope": "Runtime executable is not in these archives; its digest/build binding is retained-receipt evidence.",
        },
    )


def terminal(status, job):
    need(
        status["job_id"] == job
        and status["state"] == "succeeded"
        and status["exit_code"] == 0,
        "successful original terminal",
    )
    need(status["terminal_publication_protocol"] == 1, "terminal publication protocol")
    for key in ("terminal_publication_confirmed", "output_complete", "output_durable"):
        need(status[key] is True, "terminal publication field: " + key)
    need(
        status["timed_out"] is False and status["cancelled"] is False,
        "terminal outcome flags",
    )
    need(
        re.fullmatch(r"[0-9a-f]{32}", status["launch_nonce"]) is not None,
        "terminal nonce",
    )
    counts = {}
    for name in ("stdout", "stderr"):
        counts[name] = status["log_bytes"][name]["stored"]
        need(
            status["log_bytes"][name]["seen"] == counts[name] >= 0,
            "complete stream count",
        )
        need(
            status["log_synced"][name] is True
            and status["log_truncated"][name] is False
            and status["log_errors"][name] is None,
            "durable complete stream",
        )
    return {
        key: status[key] for key in ("state", "exit_code", "launch_nonce", "at_unix_ms")
    } | {"counts": counts}

