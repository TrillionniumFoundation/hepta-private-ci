#!/usr/bin/env python3
"""Package the two explicitly authorized frozen read-only evidence cuts."""
import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def load(path):
    return json.loads(path.read_bytes())


def dump(path, data):
    assert not path.exists(), str(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def main(root, kind):
    if kind == "main67":
        source_dir = "hepta-audit-fifth/main67-ci-cut-20261106T0104"
        output_name = "main67-ci-cut-20261106T0104-custody"
        prefix = "current-head-ci/main67-20261106T0104/"
        verifier = source_dir + "/verify_cut.py"
        arguments = []
        frozen_stdout = source_dir + "/VERIFICATION.json"
        proof = load(root / frozen_stdout)
        authority = {key: proof[key] for key in ("head", "observation_start", "observation_end", "run_count", "job_count", "job_states")}
        extra = []
        scope = "Frozen current-head metadata and two complete V8 original logs only; not a new native/product/artifact qualification."
        title = "main67 CI 01:04 状态切点：完整只读原件包"
        detail = "本切点含 19 个 run、53 个 job 和完整 20 次 API 原响应。状态为 19 success、23 queued、9 cancelled、2 skipped。23 个 queued job 无 runner、无步骤，两个额外 pending run 的 job 数为零。两个新终态 V8 job 的 raw log 与完整 MCP 解码内容相同，保留 CR 字节。ARM 取消原因未确定：elapsed 时间及取消消息都不能证明超时或操作者；不可用 check-run 的 400 原响应也完整保留。"
    else:
        source_dir = "research-audit/b11-strict-boundary-independent-20261106"
        output_name = "b11-strict-boundary-custody-20261106"
        prefix = "reviews/b11-strict-boundary-independent-20261106/"
        verifier = source_dir + "/verify_evidence.py"
        arguments = ["{root}"]
        frozen_stdout = source_dir + "/replay-01.stdout.json"
        proof = load(root / frozen_stdout)
        authority = proof["source_authority"]
        v3 = root / "architecture-audit/b11-host-neither-observation-candidate-20261105/v3"
        old = root / "architecture-audit/b11-delete-boundary-20261105"
        tree_path = v3 / "evidence/published-intended-full-tree.json"
        tree = load(tree_path)
        leaves = {entry["path"]: entry["sha"] for entry in tree["tree"] if entry["type"] == "blob"}
        source_map = load(v3 / "source-map.json")
        assert len(source_map["original_sources"]) == 14
        extra = [tree_path, v3 / "source-map.json"]
        extra += [v3 / "source" / row["repository_path"] for row in source_map["original_sources"]]
        old_manifest = load(old / "source-manifest.json")
        unchanged = [row for row in old_manifest["source_files"] if leaves.get(row["path"]) == row["git_blob"]]
        assert len(unchanged) == 11
        extra += [old / "source-manifest.json"] + [root / row["local_path"] for row in unchanged]
        extra += [old / "source/codex-rs/windows-sandbox-rs/src/token.rs",
                  root / "architecture-audit/b11-full-restricting-caller-20261105/source/codex-rs/windows-sandbox-rs/src/elevated/ipc_framed.rs"]
        terminal = root / "architecture-audit/b11-pr4884-ci-20261105/terminal"
        for probe in ["probe-127584591851", "probe-127606676952"]:
            logs = list((terminal / probe / "members/bazel-execution-logs/failed-test-logs").glob("invocation-*/targets/0000/test.log"))
            assert len(logs) == 1
            extra += [logs[0], logs[0].with_suffix(".xml")]
        root_replay = root / "hepta-audit-fifth/b11-strict-mechanism-root-replay.json"
        assert root_replay.read_bytes() == (root / frozen_stdout).read_bytes()
        extra.append(root_replay)
        scope = "Frozen static strict-boundary mechanism review with existing native10/native11 originals; no native12/native13, new execution, or qualified product repair."
        title = "B11 严格边界独立机制审阅：完整只读原件包"
        detail = "完整保留六份原独审文件及原 verifier 精确引用的依赖：v3 source-map、published 完整树、14 份 actual source；旧 boundary source-manifest、其中 11 份在 9cb 树仍 unchanged 的原件和旧 token；elevated/ipc_framed；native10/11 完整 test.log 与 XML；root 独立重放完整 stdout。未纳入 native12/13。原交错 JSON 保留原文，不补拼、修复或推断缺失值。finite explicit-read 控制不证明 ambient-read、loader、IPC 或后代产品合同；host privilege-set 干预不单归因某个 privilege，也不修复本来就 DISABLE_MAX_PRIVILEGE 的 strict token。"
    source = root / source_dir
    selected = {path for path in source.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    selected.update(root / path if isinstance(path, str) else path for path in extra)
    assert all(path.is_file() and not path.is_symlink() for path in selected)
    originals = {path: path.read_bytes() for path in sorted(selected, key=lambda p: p.relative_to(root).as_posix())}
    out = root / "research-audit" / output_name
    assert not out.exists(), str(out)
    out.mkdir(parents=True)
    members = []
    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path, data in originals.items():
            name = "root/" + path.relative_to(root).as_posix()
            mode = path.stat().st_mode & 0o777
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), mode, 0
            entry.uid = entry.gid = 0
            entry.uname = entry.gname = ""
            tar.addfile(entry, io.BytesIO(data))
            members.append({"path": name, "mode": mode, **identity(data)})
    archive = gzip.compress(raw_tar.getvalue(), compresslevel=9, mtime=0)
    (out / "evidence.tar.gz").write_bytes(archive)
    encoded = base64.b64encode(archive)
    parts = []
    for start in range(0, len(encoded), 400_000):
        body = encoded[start:start + 400_000]
        file = out / f"archive.b64.part-{len(parts):03}.txt"
        file.write_bytes(body)
        parts.append({"path": file.name, **identity(body)})
    dump(out / "member-manifest.json", {"schema": "hepta-readonly-evidence-members-v1", "kind": kind,
         "authority": authority, "count": len(members), "total_bytes": sum(row["bytes"] for row in members),
         "selection": {"complete_frozen_directory": source_dir,
                       "extra_portable_dependencies": [path.relative_to(root).as_posix() for path in sorted(selected - set(source.rglob('*')))],
                       "excluded": "__pycache__ and .pyc only; no source/evidence normalization"}, "members": members})
    dump(out / "archive-transport.json", {"format": "gzip(tar(PAX)), concatenated standard base64 parts",
         "archive": identity(archive), "encoded_bytes": len(encoded), "parts": parts})
    dump(out / "replay-spec.json", {"kind": kind, "authority": authority, "scope": scope,
         "verifier": verifier, "arguments": arguments, "frozen_stdout": frozen_stdout})
    for name in ["restore_readonly_evidence.py", "build_readonly_evidence_package.py"]:
        (out / name).write_bytes((Path(__file__).resolve().parent / name).read_bytes())
    readme = f"""# {title}

{detail}

## 归档与重放

本包 {len(members)} 份完整原件保留 `root/` 下的 workspace 相对层级。`member-manifest.json` 逐份列出原字节数、SHA-256、Git blob SHA；`archive-transport.json` 绑定无损 gzip/tar 和全部 base64 分片。相同依赖可能曾由另一证据包登记，本包仍实际包含全部所需原件，不依赖工作目录之外的历史包。

在 Python 3 环境运行：

```sh
python restore_readonly_evidence.py
```

程序验证完整分片及每份成员，将所有原字节保存于新临时目录后执行未修改的原只读 verifier。实际 stdout 必须与归档内原冻结 stdout 完整 `bytes ==`；每一成员在恢复前后也做直接完整字节比较，且不得产生额外文件。不会重新查询 API、dispatch/rerun/cancel、查询 native 容量、编译或运行原生测试。

`offline-roundtrip.stdout.json` 与 `.execution.json` 记录此次离线恢复的实际回执。Git 实际登记采用 `create_tree(content)`、实际递归 tree 对照、每个 blob 的完整 full GET 字节比较；不更新任何 ref。最终实际清单见 `registry.actual.json` 和独立 self receipt。

## 结论范围

{scope}

证据封存和静态重放不改变原 blocker 状态，不替代 AGENTS 所要求的项目 test/fix/fmt；这些命令在本封包中保持 NOT_RUN。
"""
    (out / "README.zh-CN.md").write_text(readme)
    start = datetime.now(timezone.utc).isoformat()
    run = subprocess.run([sys.executable, str(out / "restore_readonly_evidence.py")], capture_output=True, timeout=60)
    (out / "offline-roundtrip.stdout.json").write_bytes(run.stdout)
    (out / "offline-roundtrip.stderr.txt").write_bytes(run.stderr)
    dump(out / "offline-roundtrip.execution.json", {"started_utc": start,
         "completed_utc": datetime.now(timezone.utc).isoformat(), "command": ["python", "restore_readonly_evidence.py"],
         "exit_code": run.returncode, "stdout": identity(run.stdout), "stderr": identity(run.stderr),
         "new_native_or_network_or_ref_actions": False})
    assert run.returncode == 0 and run.stderr == b"", (run.returncode, run.stderr.decode(errors="replace"))
    assert all(path.read_bytes() == data for path, data in originals.items())
    standalone = ["README.zh-CN.md", "restore_readonly_evidence.py", "build_readonly_evidence_package.py",
                  "member-manifest.json", "archive-transport.json", "replay-spec.json",
                  "offline-roundtrip.stdout.json", "offline-roundtrip.stderr.txt", "offline-roundtrip.execution.json"]
    standalone += [part["path"] for part in parts]
    objects = []
    for name in standalone:
        file = out / name
        raw = file.read_bytes()
        raw.decode("utf-8")
        objects.append({"local_path": str(file), "repository_path": prefix + name, **identity(raw)})
    dump(out / "registration-plan.json", {"repository": "TrillionniumFoundation/hepta-private-ci", "prefix": prefix, "objects": objects})
    print(json.dumps({"directory": str(out), "members": len(members), "member_bytes": sum(row["bytes"] for row in members),
                      "archive_bytes": len(archive), "base64_parts": len(parts), "pending_actual_objects": len(objects),
                      "offline_replay_exit": run.returncode, "all_direct_bytes_equal": True, "scope": scope}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["main67", "strict"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    main(args.root.resolve(), args.kind)
