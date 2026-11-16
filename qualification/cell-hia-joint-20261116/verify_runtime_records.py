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


def lane_review(root, pins, result):
    lane, pairs, output = root / "controller/lane-v4", {}, []
    for label in ("observe", "predict", "campaign"):
        saved = []
        expected_profile = document(
            lane
            / (
                "campaign-profile.json"
                if label == "campaign"
                else "worker-profile.json"
            )
        )
        for cold in (False, True):
            data = document(lane / (label + ("-cold.json" if cold else "-first.json")))
            obs, profile = data["observation"], data["profile"]
            need(
                data["status"] == "PASS"
                and data["cold"] is cold
                and profile == expected_profile,
                "lane status/profile",
            )
            need(
                profile["candidate_sha256"]
                == CANDIDATE
                == data["domain"]["candidate_sha256"],
                "lane candidate",
            )
            need(
                obs["profile_sha256"]
                == sha(canonical({"profile": profile, "runtime": data["runtime"]})),
                "canonical profile digest",
            )
            for field in ("source_commit", "binary_sha256", "config_sha256"):
                need(
                    profile["runtime"][field]
                    == pins[field]
                    == data["runtime"]["runtime_" + field],
                    "lane runtime pin: " + field,
                )
            need(
                data["runtime"]["runtime_source_checkout_verified"] is True,
                "recorded source check",
            )
            need(
                obs["state"] == "TERMINAL"
                and obs["actual_runtime_transport"] is True
                and obs["automatic_replay"] is False,
                "observed original terminal",
            )
            need(obs["request_id"] == data["request"]["request_id"], "request identity")
            job, methods, tools = obs["job_id"], Counter(), Counter()
            statuses, reads, catalog, ids = [], [], [], set()
            for entry in data["protocol"]:
                request, response = entry["request"], entry["response"]
                need(
                    request["id"] == response["id"]
                    and request["id"] not in ids
                    and "error" not in response,
                    "RPC identity/error",
                )
                ids.add(request["id"])
                methods[request["method"]] += 1
                if request["method"] == "tools/list":
                    catalog.extend(response["result"]["tools"])
                if request["method"] != "tools/call":
                    continue
                name, args = request["params"]["name"], request["params"]["arguments"]
                tools[name] += 1
                need(
                    name in ("process_start", "process_status", "process_read"),
                    "unexpected runtime tool",
                )
                answer = response["result"]
                need(
                    answer["isError"] is False
                    and len(answer["content"]) == 1
                    and answer["content"][0]["type"] == "text",
                    "tool response envelope",
                )
                answer = parse(answer["content"][0]["text"])
                if name == "process_start":
                    need(
                        answer["job"]["id"] == job
                        and answer["reused"] is False
                        and answer["launch"]["ok"] is True,
                        "actual original job launch",
                    )
                    need(
                        parse(args["stdin"]) == data["request"],
                        "actual stdin/request binding",
                    )
                    need(
                        {
                            k: v
                            for k, v in args.items()
                            if k not in ("stdin", "idempotency_key")
                        }
                        == profile["process"],
                        "actual start/profile binding",
                    )
                else:
                    need(answer["job_id"] == job, "tool response original job")
                    need(
                        args["job_id"] == job and args["host"] == obs["host"],
                        "original job observation arguments",
                    )
                if name == "process_status":
                    statuses.append(answer)
                if name == "process_read":
                    reads.append((args, answer))
            need(
                methods["initialize"] == 1 and methods["tools/list"] >= 1,
                "fresh saved protocol initialization",
            )
            need(
                tools["process_start"] == (0 if cold else 1)
                and tools["process_status"] >= 2
                and tools["process_read"] >= 1,
                "start/status/read population",
            )
            need(
                sha(canonical(catalog)) == data["runtime"]["runtime_tools_sha256"],
                "actual tool catalog digest",
            )
            final = statuses[-1]
            proof = terminal(final, job)
            need(proof == obs["terminal_proof"], "whole terminal proof")
            completed = [item for item in statuses if item.get("state") == "succeeded"]
            need(
                len(completed) >= 2 and all(item == final for item in completed),
                "whole terminal status changed across read",
            )
            streams = {"stdout": bytearray(), "stderr": bytearray()}
            for args, answer in reads:
                for name in streams:
                    page, offset, size = (
                        answer[name],
                        len(streams[name]),
                        proof["counts"][name],
                    )
                    chunk = bytes.fromhex(page["bytes_hex"])
                    need(
                        args[name + "_offset"] == page["offset"] == offset,
                        "read byte cursor",
                    )
                    need(
                        page["size"] == size
                        and page["next_offset"] == offset + len(chunk) <= size,
                        "read byte extent",
                    )
                    need(page["eof"] is (offset + len(chunk) == size), "read eof")
                    streams[name].extend(chunk)
            for name, contents in streams.items():
                encoded = obs["streams"][name]
                need(
                    len(contents) == encoded["bytes"] == proof["counts"][name],
                    "observed stream count",
                )
                need(
                    bytes(contents) == bytes.fromhex(encoded["bytes_hex"])
                    and sha(contents) == encoded["sha256"],
                    "observed/protocol stream bytes",
                )
            need(
                parse(bytes(streams["stdout"])) == data["domain"],
                "domain is not exact stdout JSON",
            )
            saved.append((data, final, streams, dict(tools)))
        first, cold = saved
        need(
            first[0]["request"] == cold[0]["request"]
            and first[0]["profile"] == cold[0]["profile"]
            and first[0]["runtime"] == cold[0]["runtime"],
            "cold request/profile/runtime differs",
        )
        need(
            first[0]["observation"] == cold[0]["observation"]
            and first[1] == cold[1]
            and first[2] == cold[2],
            "cold whole terminal or exact stream differs",
        )
        need(first[0]["domain"] == cold[0]["domain"], "cold domain differs")
        pairs[label] = first[0]
        output.append(
            {
                "label": label,
                "job_id": first[0]["observation"]["job_id"],
                "first_tools": first[3],
                "cold_tools": cold[3],
                "whole_terminal_equal": True,
                "stream_bytes_equal": True,
                "domain_from_stdout": True,
            }
        )
    need(len({item["job_id"] for item in output}) == 3, "job population")
    need(len(result["completed_requests"]) == 3, "summary request population")
    for item in result["completed_requests"]:
        need(
            item["job_id"] == pairs[item["label"]]["observation"]["job_id"]
            and item["cold_runtime_reobserved"] is True
            and item["same_original_output"] is True
            and item["second_process_start"] is False,
            "summary cold-observation binding",
        )
    return pairs, output


def campaign_review(root, candidate, lane_result, pairs, pins):
    maintenance = root / "worker/lane-v4-state/maintenance"
    campaign = maintenance / "campaign"
    outer = raw(root / "controller/candidate-v4-bound.json")
    need(
        raw(maintenance / "OUTER_CANDIDATE.json")
        == outer
        == raw(root / "worker/worker-v4/portable-v4/candidate/candidate.json"),
        "outer candidate original bytes",
    )
    need(
        document(maintenance / "REQUEST.json") == pairs["campaign"]["request"],
        "campaign request original bytes",
    )
    original_bytes, relocated_bytes = (
        raw(maintenance / "ORIGINAL_BUILD.json"),
        raw(maintenance / "RELOCATED_BUILD.json"),
    )
    original, relocated = parse(original_bytes), parse(relocated_bytes)
    files = {(x["root"], x["path"]): x["sha256"] for x in candidate["files"]}
    need(
        sha(original_bytes)
        == files[("artifacts", "native/build.json")]
        == relocated["original_build_record_sha256"],
        "original build digest chain",
    )
    need(
        set(relocated) - set(original)
        == {"original_build_record_sha256", "relocation_scope"},
        "relocated build added fields",
    )
    need(
        {key for key in original if original[key] != relocated[key]}
        == {"hepta_root", "image_path"},
        "relocated build changed fields",
    )
    need(
        raw(campaign / "native/build.json") == relocated_bytes,
        "campaign uses exact derived build",
    )
    native_hashes = {
        name: sha(raw(campaign / "native" / name))
        for name in ("cell_bridge.so", "transport.py", "continuation.hepta")
    }
    need(
        native_hashes["cell_bridge.so"]
        == candidate["native"]["image_sha256"]
        == relocated["image_sha256"],
        "native image binding",
    )
    need(
        native_hashes["continuation.hepta"]
        == candidate["native"]["source_sha256"]
        == relocated["source_sha256"],
        "native source binding",
    )
    need(
        native_hashes["transport.py"] == files[("hia", "tools/cell_bridge_native.py")],
        "native transport binding",
    )
    result_bytes, plan_bytes = (
        raw(campaign / "RESULT.json"),
        raw(campaign / "PLAN.json"),
    )
    result, domain = parse(result_bytes), pairs["campaign"]["domain"]
    need(
        result == domain["campaign_result"] == lane_result["campaign_result"],
        "whole campaign RESULT",
    )
    need(
        sha(result_bytes)
        == domain["campaign_result_sha256"]
        == lane_result["campaign_result_sha256"],
        "campaign result digest",
    )
    report_path, receipt_path = (
        root / "worker/campaign-readonly-v4b.json",
        root / "worker/campaign-readonly-v4b-receipt.json",
    )
    report, receipt = document(report_path), document(receipt_path)
    manifest_path = root / "worker/campaign-review-image-v4-manifest.json"
    manifest = document(manifest_path)
    need(
        receipt["report_sha256"] == sha(raw(report_path))
        and receipt["review_image_manifest_sha256"] == sha(raw(manifest_path)),
        "review receipt digest chain",
    )
    need(
        report["result_sha256"] == sha(result_bytes)
        and report["plan_sha256"]
        == receipt["plan_sha256"]
        == result["plan_sha256"]
        == sha(plan_bytes),
        "review/result/plan binding",
    )
    need(
        receipt["status"] == "PASS"
        and receipt["exit_code"] == 0
        and report["status"] == "READ_ONLY_CONSISTENCY_PASS",
        "retained review status",
    )
    need(
        report["actual_runtime_transport_verified"] is False,
        "readonly report transport scope",
    )
    need(
        receipt["originals_changed"] is False
        and receipt["originals_unchanged"] is True
        and receipt["included_files_byte_identical"] is True,
        "retained snapshot assertions",
    )
    need(
        all(
            manifest[k] is True
            for k in (
                "originals_unchanged",
                "included_files_byte_identical_after_review",
                "no_model_or_native_execution",
            )
        ),
        "retained manifest assertions",
    )
    current = inventory(campaign)
    need(
        current == manifest["files"],
        "complete current campaign/snapshot manifest inventory",
    )
    omitted = ["memory/owner.sqlite-wal", "predictor/owner.sqlite-wal"]
    need(
        sorted(name for name in current if name.endswith("-wal"))
        == omitted
        == sorted(manifest["omitted_empty_wal"])
        == sorted(receipt["omitted_empty_wal"]),
        "exact two WAL omissions",
    )
    need(
        all(current[name] == {"sha256": sha(b""), "size": 0} for name in omitted),
        "omitted WAL must be empty",
    )
    source_map = {
        str(path.relative_to(campaign / "executed-source")): sha(raw(path))
        for path in (campaign / "executed-source").rglob("*.py")
    }
    need(
        len(source_map) == report["source_modules"] == receipt["source_modules"] == 17,
        "campaign source module population",
    )
    for name, fingerprint in source_map.items():
        need(
            files[("cells", "scripts/" + name)] == fingerprint,
            "executed-source/candidate binding",
        )
    runtime_bytes = raw(campaign / "RUNTIME_PINS.json")
    runtime_identity = parse(runtime_bytes)
    need(
        runtime_identity == {**pins, "origin_candidate_sha256": CANDIDATE}
        and runtime_bytes == raw(maintenance / "RUNTIME_PINS.json"),
        "campaign runtime/origin candidate binding",
    )
    versions = list((campaign / "versions").glob("*.json"))
    need(
        len(versions)
        == report["version_manifests"]
        == receipt["version_manifests"]
        == 6,
        "version manifest population",
    )
    for path in versions:
        data = raw(path)
        version = parse(data)
        need(
            path.stem == sha(data)
            and version["source_sha256"] == source_map
            and version["plan_sha256"] == sha(plan_bytes),
            "version manifest/source/plan identity",
        )
        need(
            version["native"]["build_record_sha256"] == sha(relocated_bytes),
            "version derived build identity",
        )
        for key, name in (
            ("image_sha256", "cell_bridge.so"),
            ("worker_sha256", "transport.py"),
            ("source_sha256", "continuation.hepta"),
        ):
            need(
                version["native"][key] == native_hashes[name],
                "version native artifact identity",
            )
        need(
            version["runtime_pins"]["identity"] == runtime_identity
            and version["runtime_pins"]["sha256"] == sha(runtime_bytes),
            "version runtime binding",
        )
    compile_rows = raw(campaign / "compile.jsonl").splitlines()
    need(
        len(compile_rows)
        == result["compile_calls"]
        == report["compile_calls"]
        == receipt["compile_calls"]
        == 208,
        "compile record population",
    )
    for row in compile_rows:
        parse(row)
    for cell in ("memory", "predictor"):
        for key, name in (
            ("decision", "DECISION.json"),
            ("training", "TRAINING.json"),
            ("cold", "COLD_RESULT.json"),
        ):
            need(
                result["cells"][cell][key] == document(campaign / cell / name),
                "campaign cell original: " + key,
            )
        need(report["cells"][cell]["decision"] == "NoUpdate", "recorded decision scope")
    need(
        lane_result["native_counts"]
        == domain["native_counts"]
        == {
            cell: {"completed": report["cells"][cell]["native_completed"]}
            for cell in ("memory", "predictor")
        },
        "reported native counts binding",
    )
    verifier = (
        root
        / "worker/worker-v4/portable-v4/cells/scripts/verify_hepta_maintenance_cycle.py"
    )
    need(
        sha(raw(verifier)) == report["verifier_sha256"] == receipt["verifier_sha256"],
        "original readonly verifier bytes",
    )
    return {
        "result_sha256": sha(result_bytes),
        "plan_sha256": sha(plan_bytes),
        "original_build_sha256": sha(original_bytes),
        "relocated_build_sha256": sha(relocated_bytes),
        "readonly_report_sha256": sha(raw(report_path)),
        "snapshot_manifest_sha256": sha(raw(manifest_path)),
        "original_files_verified": len(current),
        "exact_empty_wal_omissions": omitted,
        "other_files_verified": len(current) - 2,
        "version_manifests": len(versions),
        "source_modules": len(source_map),
        "compile_records": len(compile_rows),
        "reported_native_counts": lane_result["native_counts"],
        "snapshot_scope": "Original remote review_root copy was not archived. Current originals match all manifest bytes; earlier copy-after-review stability is a retained receipt assertion, not rerun here.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source-receipts",
        type=Path,
        default=Path(__file__).with_name("RUNTIME_HELPER_SOURCE_RECEIPTS.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    need(
        not output.is_relative_to(root) and not output.exists(),
        "review output must be new and outside original evidence",
    )
    report = {
        "schema": "hepta.actual-runtime-record-review.v1",
        "scope": "Independent read-only consistency review of retained runtime observations, not execution or expanded qualification.",
        "root": str(root),
        "verifier_sha256": sha(raw(Path(__file__))),
        "execution_counts": {
            "model": 0,
            "native": 0,
            "runtime": 0,
            "sqlite_connections": 0,
            "checkpoint": 0,
        },
    }
    try:
        before = inventory(root)
        report["archive_and_pattern_scan"] = archive_review(root)
        candidate, result, pins, identity = identity_review(root, args.source_receipts)
        pairs, lanes = lane_review(root, pins, result)
        report["identities"], report["lanes"] = identity, lanes
        report["campaign"] = campaign_review(root, candidate, result, pairs, pins)
        need(inventory(root) == before, "original evidence changed during this review")
        report.update(
            status="READ_ONLY_RECORD_REVIEW_PASS",
            original_files=len(before),
            original_inventory_sha256=sha(canonical(before)),
            originals_unchanged=True,
            private_key_or_token_pattern_hits=len(
                report["archive_and_pattern_scan"]["findings"]
            ),
        )
    except (KeyError, ValueError, OSError, TypeError) as error:
        report.update(status="HOLD", error_type=type(error).__name__, error=str(error))
    with output.open("x") as stream:
        stream.write(
            json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(output),
                "sha256": sha(raw(output)),
            }
        )
    )
    return 0 if report["status"] == "READ_ONLY_RECORD_REVIEW_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
