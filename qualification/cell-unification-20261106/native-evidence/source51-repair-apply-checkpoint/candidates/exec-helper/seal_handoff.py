#!/usr/bin/env python3
"""Read closed diagnostic bytes and freeze this candidate. Never runs a probe."""

from __future__ import annotations

import json
from pathlib import Path

from build_static_readback import COMMIT, ROOT, TARGET, TREE, WORK, emit, pin, write_exact


def main() -> None:
    probe = WORK / "native-validation-results/source51-bwrap-comparison-closed"
    readback_bytes = (probe / "LOCAL-READBACK.json").read_bytes()
    assert pin(readback_bytes)["sha256"] == "8937cac7daac507e031c98e76a2b4e1c00fb059dcb716f2d86496ba0400495ff"
    local = json.loads(readback_bytes)
    assert len(local["files"]) == 29
    assert sorted(p.name for p in probe.iterdir() if p.is_file()) == sorted(
        [r["path"] for r in local["files"]] + ["LOCAL-READBACK.json"]
    )
    mappings = []
    for item in local["files"]:
        data = (probe / item["path"]).read_bytes()
        observed = pin(data)
        assert observed["bytes"] == item["bytes"] and observed["sha256"] == item["sha256"]
        destination = f"evidence/launcher-comparison/{item['path']}"
        write_exact(ROOT / destination, data)
        mappings.append({"source": f"native-validation-results/source51-bwrap-comparison-closed/{item['path']}", "destination": destination, **observed})
    write_exact(ROOT / "evidence/launcher-comparison/LOCAL-READBACK.json", readback_bytes)
    mappings.append({"source": "native-validation-results/source51-bwrap-comparison-closed/LOCAL-READBACK.json", "destination": "evidence/launcher-comparison/LOCAL-READBACK.json", **pin(readback_bytes)})

    load = lambda name: json.loads((probe / name).read_bytes())
    pre, complete = load("preconditions.json"), load("complete.json")
    terminal, launch, process_read = load("terminal-process-status.json"), load("original-launch.json"), load("terminal-process-read.json")
    assert pre["source_tree"] == complete["source_tree"] == TREE
    assert pre["source_commit"] == COMMIT
    assert pre["source_count"] == complete["source_count"] == 194
    assert pre["source_guard_pass"] and complete["source_guard_pass"]
    assert pre["locks_before"] == complete["locks_after"]
    assert pre["programs"] == complete["programs"]
    assert complete["same_probe_argv"] and complete["no_automatic_retry"]
    assert not complete["rust_execution"] and not complete["source_mutation"]
    assert not complete["full_fs_helper_or_test_suite_qualification"]
    assert pre["probe_argv"] == ["--unshare-user", "--unshare-net", "--ro-bind", "/", "/", "/bin/true"]
    assert pre["each_program_probe_count"] == 1
    assert pre["original_r24_per_test_cwd_observed"] is False
    assert terminal["exit_code"] == 0 and terminal["state"] == "succeeded"
    assert terminal["output_complete"] and terminal["output_durable"] and terminal["terminal_publication_confirmed"]
    assert not terminal["timed_out"] and not terminal["cancelled"] and not terminal["automatic_retry"]
    assert terminal["job_id"] == process_read["job_id"] == launch["job"]["id"] == "1a1b19909e1-fc05-79c4"
    assert launch["job"]["args"] == ["-c", (probe / "original-command.txt").read_text()]
    assert launch["launch"]["ok"]
    out = bytes.fromhex(process_read["stdout"]["bytes_hex"])
    err = bytes.fromhex(process_read["stderr"]["bytes_hex"])
    assert out.decode() == process_read["stdout"]["text"] and json.loads(out) == complete
    assert err == b"" and process_read["stderr"]["text"] == ""
    assert len(out) == terminal["log_bytes"]["stdout"]["stored"] == process_read["stdout"]["size"]
    assert process_read["stdout"]["eof"] and process_read["stderr"]["eof"]

    results = []
    for label in ("system", "repo"):
        for kind in ("version", "probe"):
            stem = f"{label}-{kind}"
            intent, raw, receipt = (load(f"{stem}-{suffix}.json") for suffix in ("intent", "raw-process-result", "receipt"))
            expected_command = [pre["programs"][label]["path"], *(pre["probe_argv"] if kind == "probe" else ["--version"])]
            assert intent["command"] == raw["command"] == receipt["command"] == expected_command
            assert intent["cwd"] == raw["cwd"] == pre["controlled_diagnostic_cwd"]
            assert intent["program_before"] == pre["programs"][label]
            assert raw["exit_code"] == receipt["exit_code"] == (1 if (label, kind) == ("repo", "probe") else 0)
            assert raw["elapsed_seconds"] == receipt["elapsed_seconds"] == raw["ended_unix"] - raw["started_unix"]
            for stream in ("stdout", "stderr"):
                stream_bytes = (probe / f"{stem}-{stream}.txt").read_bytes()
                assert pin(stream_bytes) == receipt[stream]
                assert stream_bytes.decode() == receipt[f"{stream}_text"]
            assert receipt in complete["results"]
            results.append(receipt)
    assert results == complete["results"]
    assert (probe / "system-version-stdout.txt").read_bytes() == b"bubblewrap 0.11.1\n"
    assert (probe / "repo-version-stdout.txt").read_bytes() == b"bubblewrap built for Codex\n"
    repo_error = (probe / "repo-probe-stderr.txt").read_bytes()
    assert repo_error == b"bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n"
    assert len(repo_error) == 61 and len(repo_error.removesuffix(b"\n")) == 60
    for name in ("failure-1.txt", "failure-2.txt"):
        assert repo_error.removesuffix(b"\n") in (ROOT / "evidence/r24" / name).read_bytes()
    for name, path in (("bwrap.rs.source.txt", "codex-rs/sandboxing/src/bwrap.rs"), ("fake_bwrap.rs.source.txt", TARGET)):
        assert (probe / name).read_bytes() == (ROOT / "original" / path).read_bytes()
    assert pin((probe / "repo-bwrap.d").read_bytes()) == {
        k: pre["repo_program_provenance"][k] for k in ("bytes", "sha256", "git_blob")
    }
    assert pre["repo_program_provenance"]["compiler_artifact_json_was_not_retained"]

    emit("PROBE-INDEPENDENT-READBACK.json", {
        "schema": "hepta.exec-server-bwrap-r24-probe-independent-readback.v1",
        "status": "CLOSED_DIAGNOSTIC_BYTES_AND_RESULTS_VERIFIED_NOT_RUST_QUALIFICATION",
        "script": {"path": "seal_handoff.py", **pin(Path(__file__).read_bytes())},
        "original_files_verified": 29, "native_transfer_readback_verified": True,
        "source_commit": COMMIT, "source_tree": TREE,
        "remote_full194_guard_and_dual_lock_records_verified": True,
        "full194_source_bytes_not_independently_rehashed_by_this_report": True,
        "two_exported_source_files_equal_fixed_git_originals": True,
        "program_identity_scope": "Native original guarded ELF stat/hash records; no ELF binary download or execution by this reviewer.",
        "original_command_matches_controller_launch": True,
        "raw_stdout_hex_text_and_complete_json_equal": True,
        "four_intent_raw_receipt_stream_bindings_pass": True,
        "outer_job": terminal["job_id"], "outer_natural_exit_code": 0,
        "same_probe_arguments": pre["probe_argv"],
        "system_probe_exit": 0, "repo_probe_exit": 1,
        "repo_60_byte_error_message_matches_both_original_failure_blocks": True,
        "line_ending_boundary": "Probe stderr is 61 bytes including LF. Production wait_for_helper_output trims captured stderr; the quoted capability failure block retains the identical 60-byte message, not the terminal LF. Original bytes are unchanged.",
        "programs": pre["programs"], "results": results,
        "controlled_cwd": pre["controlled_diagnostic_cwd"],
        "original_r24_per_test_cwd_observed": False,
        "repo_compiler_artifact_json_was_not_retained": True,
        "not_proven": ["Exact kernel netlink error or LSM cause", "All bwrap backends work", "Full fs helper behavior", "The repaired Rust tests pass"],
        "rust_executed_by_reviewer": False,
        "additional_probe_executed_by_reviewer": False,
        "copy_mapping": mappings,
    })

    candidate = json.loads((ROOT / "source-manifest.json").read_bytes())
    emit("repair-audit.json", {
        "schema": "hepta.exec-server-bwrap-r24-repair-audit.v1",
        "status": "FROZEN_ISOLATED_CANDIDATE_NATIVE_GATE_PENDING",
        "base": {"commit": COMMIT, "tree": TREE, "changed_file_count": 194},
        "candidate": candidate,
        "problem": "Two real restricted filesystem tests force the Cargo bwrap executable through their logging/fail-once shim even though product launcher discovery prefers a suitable system binary. Both fail before the original filesystem assertions, at loopback RTM_NEWADDR initialization.",
        "evidence_strength": {
            "observed_original_gate": "Original full four-package r24 exited 100. The two exact closed failure blocks contain the same loopback error; original assertions and error output are retained.",
            "observed_authorized_diagnostic": "On the recorded unchanged source50 host, the system and repository ELFs were each invoked once with identical existing restricted probe arguments. System exited 0; repository exited 1 with 61-byte stderr whose 60-byte message matches both original errors. Production trims the terminal LF before the quoted capability failure. Version commands, raw rc, output, ELF guards, source/lock guards, and controller natural exit are preserved.",
            "source_causal_inference": "The fixture forced a different launcher-discovery route from the product. Reusing the existing public discovery API before installing the shim restores that selection precedence without altering the sandbox arguments or runtime checks.",
            "unresolved_lower_level_cause": "No actual netlink error payload, credential transition, or LSM decision was traced. Repository network.c can return failure without assigning the netlink errno, so the printed EPERM cannot establish that cause.",
        },
        "change": {
            "path": TARGET,
            "description": "Resolve codex_sandboxing::find_system_bwrap_in_path() in the parent before writing the shim; use existing cargo_bin(\"bwrap\") only when discovery returns None.",
            "no_runtime_error_fallback": True,
            "public_api_and_existing_dependency": "The package already has codex-sandboxing; the function is publicly re-exported on Linux, where both affected callers are gated.",
            "recursion_boundary": "Both affected callers invoke write_fake_bwrap before prepending the fresh shim directory to a child-only PATH. The parent PATH is unchanged and the new shim does not yet exist when discovery runs.",
            "discovery_is_not_capability_acceptance": "The downstream original product help/capability eligibility checks still inspect the delegated executable. Discovery alone does not assert every system bwrap is supported.",
        },
        "unchanged": [
            "All original helper shell bytes after the resolved path binding, quoting, help and capability probe delegation",
            "All original namespace, user, network, bind, argv0 and inherited descriptor arguments",
            "Logging and forced fail-once behavior, command execution rc and stderr propagation",
            "Both full original test files, assertions, skip conditions, deadlines, retries and permission profiles",
            "All production Rust, PID1 and owner pidfd guards, Cargo/Bazel manifests and both lock files",
        ],
        "verification": {
            "static": "STATIC-READBACK.json",
            "closed_probe": "PROBE-INDEPENDENT-READBACK.json",
            "independent_static": "independent-review/CANDIDATE-STATIC-REVIEW.json",
            "independent_c_source": "independent-review/C-SOURCE-AUDIT.json",
            "full_native_strict_and_tests": "PENDING; original real tests remain the regression oracle",
        },
        "no_rust_or_native_source_write_by_author": True,
        "science_or_backend_qualification_claim": False,
    })
    readme = """# Exec-server bwrap 夹具修复候选（r24 后）

本候选只改 `codex-rs/exec-server/tests/common/fake_bwrap.rs` 的真实程序发现顺序：在创建 shim、组装子进程 PATH 之前，调用已有的系统 bwrap 发现函数；仅当函数返回 `None` 时才使用已有仓库二进制。**没有在运行失败后改换程序。候选尚未获得原生 Rust 门资格。**

## 原始问题与实测范围

r24 的完整四包门自然退出 100。两项 exec-server 测试在真实受限文件系统 helper 启动时收到同一条 `loopback: Failed RTM_NEWADDR` 错误。原始失败块、命令、raw rc、资源记录与源码后置 guard 均原样保存在 `evidence/r24/`。

单次授权对照对两个已固定身份的 ELF 使用相同原参数：

```text
--unshare-user --unshare-net --ro-bind / / /bin/true
```

系统 `/usr/bin/bwrap`（0.11.1）退出 0，stdout/stderr 均为空；仓库 `target/debug/bwrap` 退出 1，stderr 为61字节，其中不含末尾换行的60字节错误文本与两项原失败一致。生产 helper 对 stderr 调用 `.trim()`，第一项原失败的 Rust debug 字符串因此不保留末尾换行。完整原件在 `evidence/launcher-comparison/`，独立字节、回执、原输出和命令核验在 `PROBE-INDEPENDENT-READBACK.json`。

该结果证明本次两种选择的实际表现不同。它没有确定具体内核 netlink 错误或 LSM 原因，也没有验证完整 helper、全部 bwrap 后端或修复后的 Rust 测试。诊断使用了明确记录的 cwd；原 r24 每个测试的 cwd 没有单独记录。仓库程序身份来自现存 ELF 与其 depfile，原 compiler-artifact JSON 没有被保留。

## 修改为何保持原验收含义

生产 launcher 原本优先尝试 PATH 中的系统 bwrap，并保留自己的 help/capability 资格检查。候选复用现有公共发现 API；它不把路径发现等同于完整资格判定。两个调用方先创建 shim，随后才把其目录放入子进程 PATH，因此不会递归发现本次新 shim。原 shell 其余部分逐字不变：所有隔离参数、argv0、继承描述符、日志、fail-once、退出状态和 stderr 继续传递。两个原测试文件、断言、权限、时间预算均未修改；没有依赖或锁文件变化。

完整正逆改写与原件 pins 在 `source-manifest.json`、`source-input-pins.json`、`STATIC-READBACK.json`。独立静态与 C 初始化顺序审计在 `independent-review/`。`repair-audit.json` 区分原生观察、源码推断与尚未获得的资格。`HANDOFF-MANIFEST.json` 是本目录全部交付文件的最终清单。
"""
    write_exact(ROOT / "README.md", readme.encode())
    emit("CLOSURE-MAPPING.json", {
        "schema": "hepta.exec-server-bwrap-r24-closure-map.v1",
        "base_immutable_git_commit": COMMIT,
        "source_inputs": "source-input-pins.json",
        "candidate": "source-manifest.json",
        "original_r24_failure_and_receipt_mapping": "STATIC-READBACK.json#attachments",
        "original_authorized_probe_mapping": "PROBE-INDEPENDENT-READBACK.json#copy_mapping",
        "independent_reviews": ["independent-review/CANDIDATE-STATIC-REVIEW.json", "independent-review/C-SOURCE-AUDIT.json"],
        "full_r24_log": {"copied_here": False, "bytes": 232861, "sha256": "84a5a9053de8be11ad6c1cc0326f5deb3c84907a7255e7c8911034c52fb2f37d", "closure": "Original r24 archive owned by root; exact two raw spans and its native index are preserved here."},
        "runtime_qualification_of_candidate": "PENDING",
        "closure_gaps": ["Full native strict/tests on the eventual published candidate source are not yet executed."],
    })
    files = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and path.name != "HANDOFF-MANIFEST.json" and "__pycache__" not in path.parts:
            files.append({"path": path.relative_to(ROOT).as_posix(), **pin(path.read_bytes())})
    emit("HANDOFF-MANIFEST.json", {
        "schema": "hepta.exec-server-bwrap-r24-handoff.v1",
        "status": "FROZEN_CANDIDATE_AND_CLOSED_DIAGNOSTIC_NOT_NATIVE_QUALIFICATION",
        "source_commit": COMMIT, "source_tree": TREE,
        "candidate_source_files": [f"source/{TARGET}"],
        "file_count": len(files), "total_bytes": sum(r["bytes"] for r in files),
        "files": files,
    })
    print(json.dumps({"status": "FROZEN", "files": len(files), "bytes": sum(r["bytes"] for r in files), "reports": {name: pin((ROOT / name).read_bytes()) for name in ("repair-audit.json", "PROBE-INDEPENDENT-READBACK.json", "HANDOFF-MANIFEST.json")}}, indent=2))


if __name__ == "__main__":
    main()
