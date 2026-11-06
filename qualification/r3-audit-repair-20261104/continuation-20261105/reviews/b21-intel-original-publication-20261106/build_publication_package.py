#!/usr/bin/env python3
"""Freeze approved publication files without touching any original or Git ref."""
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


def dump(path, obj):
    assert not path.exists(), str(path)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def main(workspace, kind):
    common = ["hepta-audit-fifth/verify_main_format_retention_publication.py",
              "hepta-audit-fifth/verify_b11_launcher_publication.py"]
    if kind == "b21":
        name = "b21-intel-original-publication-20261106"
        directory = "hepta-audit-fifth/b21-intel-original-gate"
        selected_dirs = [directory, "ci-audit/b21-intel-original-independent-20261106"]
        selected_files = common + ["hepta-audit-fifth/main-format-retention/intended-full-tree.json",
                                   "hepta-audit-fifth/main-format-retention/commit-ref-actual.json"]
        publication = json.loads((workspace / directory / "commit-ref-actual.json").read_bytes())
        proof = json.loads((workspace / directory / "static-verification.json").read_bytes())
        authority = {"source_commit": publication["commit"], "source_tree": publication["tree"],
                     "parent": publication["parent"], "PR": 4902,
                     "merge_commit": proof["actual_source_publication"]["actual_PR_merge"]}
        workflow = proof["new_workflow"]
        expected = {"expected_tree": publication["tree"],
                    "workflow": {k: workflow[k] for k in ("bytes", "sha256", "git_blob")},
                    "unchanged_leaves": proof["unchanged_existing_leaves"], "B21": "OPEN"}
        verifier = directory + "/verify_candidate.py"
        arguments = []
        generated = [directory + "/intended-full-tree.json", directory + "/static-verification.json"]
        title = "B21 原 Intel PTY 工作流：已发布源码证据包"
        boundary = "本冻结切点只证明工作流源码、完整树、实际 Git 出版与独立审阅对应。B21 在此原件中仍为 OPEN；后续原生终态另行封存，不并入本包。"
    else:
        name = "b11-acl-control-v2-publication-20261106"
        directory = "hepta-audit-fifth/b11-acl-control-v2-publication"
        selected_dirs = [directory,
                         "architecture-audit/b11-nonprivileged-acl-control-candidate-20261106/v2",
                         "ci-audit/b11-acl-control-v2-independent-20261106"]
        selected_files = common + ["hepta-audit-fifth/verify_b11_acl_control_v2_publication.py",
                                   "hepta-audit-fifth/b11-observation-launcher-v3-publication/intended-full-tree.json"]
        publication = json.loads((workspace / directory / "commit-ref-actual.json").read_bytes())
        proof = json.loads((workspace / directory / "root-tree-proof.json").read_bytes())
        authority = {"source_commit": publication["commit"], "source_tree": publication["tree"],
                     "parent": publication["parent"], "PR": 4884,
                     "merge_commit": proof["actual_publication"]["merge"]}
        expected = {"tree": publication["tree"], "changed_paths": sorted(proof["changed_paths"]),
                    "leaves": proof["candidate_tree_proof"]["leaves"],
                    "actual_tree_bound": proof["actual_tree_root_bound"], "B11": "OPEN"}
        verifier = "hepta-audit-fifth/verify_b11_acl_control_v2_publication.py"
        arguments = ["--root", "{root}"]
        generated = [directory + "/intended-full-tree.json", directory + "/root-tree-proof.json",
                     directory + "/candidate-static-root-replay.json"]
        title = "B11 普通 ACL 控制前提 v2：已发布源码证据包"
        boundary = "本包仅封存四路径测试前提修正的源码与出版证据。原生产 token/desktop、原断言、原严格测试后半部与测试名册不变；不把 donor native12 或后续 native13 当作本冻结出版包的新资格。B11 仍为 OPEN。"
    out = workspace / "research-audit" / name
    assert not out.exists(), str(out)
    paths = set(workspace / item for item in selected_files)
    for directory_name in selected_dirs:
        assert (workspace / directory_name).is_dir()
        paths.update(p for p in (workspace / directory_name).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    assert paths and all(p.is_file() and not p.is_symlink() for p in paths)
    ordered = sorted(paths, key=lambda p: p.relative_to(workspace).as_posix())
    originals = {p: p.read_bytes() for p in ordered}
    out.mkdir(parents=True)
    members = []
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in ordered:
            body = originals[path]
            member_name = "root/" + path.relative_to(workspace).as_posix()
            mode = path.stat().st_mode & 0o777
            entry = tarfile.TarInfo(member_name)
            entry.size, entry.mode, entry.mtime = len(body), mode, 0
            entry.uid = entry.gid = 0
            entry.uname = entry.gname = ""
            tar.addfile(entry, io.BytesIO(body))
            members.append({"path": member_name, "mode": mode, **identity(body)})
    archive = gzip.compress(tar_bytes.getvalue(), compresslevel=9, mtime=0)
    (out / "evidence.tar.gz").write_bytes(archive)
    encoded = base64.b64encode(archive)
    parts = []
    for offset in range(0, len(encoded), 400_000):
        body = encoded[offset:offset + 400_000]
        part = out / f"archive.b64.part-{len(parts):03d}.txt"
        part.write_bytes(body)
        parts.append({"path": part.name, **identity(body)})
    dump(out / "member-manifest.json", {"schema": "hepta-publication-members-v1", "kind": kind,
         "authority": authority, "count": len(members), "total_bytes": sum(row["bytes"] for row in members),
         "selection": {"directories_complete_except_pycache": selected_dirs, "additional_files": selected_files,
                       "original_workspace_relative_paths_preserved_under": "root/"}, "members": members})
    dump(out / "archive-transport.json", {"format": "gzip(tar(PAX)) encoded as concatenated standard base64 text parts",
         "archive": identity(archive), "encoded_bytes": len(encoded), "parts": parts})
    expected_bytes = (json.dumps(expected) + "\n").encode()
    (out / "expected-verifier.stdout.json").write_bytes(expected_bytes)
    dump(out / "replay-spec.json", {"kind": kind, "authority": authority, "verifier": verifier,
         "arguments": arguments, "verifier_written_frozen_files": generated,
         "expected_stdout_file": "expected-verifier.stdout.json", "expected_stdout": identity(expected_bytes),
         "expected_stdout_provenance": "Reconstructed from the corresponding frozen root proof fields in the exact order/encoding of the frozen verifier print statement; not a historical stdout capture.",
         "scope": "offline source-publication custody only; native/compile/fmt NOT_RUN"})
    for filename in ["restore_and_verify.py", "build_publication_package.py"]:
        (out / filename).write_bytes((Path(__file__).resolve().parent / filename).read_bytes())
    readme = f"""# {title}

{boundary}

## 固定身份

- Source commit: `{authority['source_commit']}`
- Source tree: `{authority['source_tree']}`
- Parent: `{authority['parent']}`
- PR: `{authority['PR']}`
- 实际 PR merge commit: `{authority['merge_commit']}`

## 完整原件与恢复

`member-manifest.json` 列出 {len(members)} 份冻结原件、每份完整字节数、SHA-256 与 Git blob SHA。归档完整保留 `root/` 下的 workspace 相对目录，包括隐藏的 `.github` 文件。只排除 Python 缓存；不重新取出版 API，不覆盖冻结源码和收据。`archive-transport.json` 绑定全部 base64 分片以及无损 gzip/tar 原件。分片是标准 base64 的连续片段，按清单顺序连接后解码。

在拥有 Python 3、Git、Bash 的环境运行：

```sh
python restore_and_verify.py
```

B21 原 verifier 还需要 PyYAML。Windows 出版 verifier 只运行离线字节/Merkle/补丁验证及候选静态 verifier。脚本先验证完整 archive 与每个成员，再只在全新临时恢复目录执行冻结 verifier，比较它写出的全部 proof/tree 原件与冻结原字节，并核对 stdout、stderr、全部其他原件未变、无意外新文件。原始目录不执行会重写证明的 verifier。

`expected-verifier.stdout.json` 按冻结 root proof 的对应字段及冻结 print 语句的字段顺序和编码重建；它不是旧执行 stdout 捕获。`offline-roundtrip.stdout.json` 才是此次恢复执行的真实输出，执行元数据另见 `offline-roundtrip.execution.json`。完整冻结 proof/tree 的比较独立于重建 stdout。

## 实际登记

所有分片、清单、恢复脚本、stdout 与说明随后通过 GitHub `create_tree(content)` 创建不可变无引用对象，逐一 full GET 比较完整 UTF-8 字节；不是 `create_blob` 调用，也不写任何 ref。`registry.actual.json` 与其 self receipt 记录最终实际对象 SHA 和验证结果。登记前本说明不预先声称登记成功。

源码测试、原生执行、编译和格式化均未由本包执行。AGENTS 原文随源码原件完整保留；本包的离线 custody 成功不替代项目要求的 test/fix/fmt，也不构成 blocker 闭合。
"""
    (out / "README.zh-CN.md").write_text(readme)
    start = datetime.now(timezone.utc).isoformat()
    run = subprocess.run([sys.executable, str(out / "restore_and_verify.py")],
                         capture_output=True, timeout=60)
    (out / "offline-roundtrip.stdout.json").write_bytes(run.stdout)
    (out / "offline-roundtrip.stderr.txt").write_bytes(run.stderr)
    dump(out / "offline-roundtrip.execution.json", {"started_utc": start,
         "completed_utc": datetime.now(timezone.utc).isoformat(), "command": ["python", "restore_and_verify.py"],
         "exit_code": run.returncode, "stdout": identity(run.stdout), "stderr": identity(run.stderr),
         "native_or_product_tests": False, "compiler": False, "formatter": False, "ref_mutation": False})
    assert run.returncode == 0 and run.stderr == b"", (run.returncode, run.stderr.decode(errors="replace"))
    assert all(p.read_bytes() == body for p, body in originals.items())
    standalone = ["README.zh-CN.md", "build_publication_package.py", "restore_and_verify.py",
                  "member-manifest.json", "archive-transport.json", "replay-spec.json",
                  "expected-verifier.stdout.json", "offline-roundtrip.stdout.json",
                  "offline-roundtrip.stderr.txt", "offline-roundtrip.execution.json"]
    standalone += [part["path"] for part in parts]
    prefix = "reviews/" + name + "/"
    objects = []
    for filename in standalone:
        file = out / filename
        body = file.read_bytes()
        body.decode("utf-8")
        objects.append({"local_path": str(file), "repository_path": prefix + filename, **identity(body)})
    dump(out / "registration-plan.json", {"repository": "TrillionniumFoundation/hepta-private-ci",
         "prefix": prefix, "objects": objects})
    print(json.dumps({"directory": str(out), "members": len(members),
                      "member_bytes": sum(row["bytes"] for row in members), "archive_bytes": len(archive),
                      "base64_parts": len(parts), "actual_objects_pending": len(objects),
                      "offline_replay": "exit 0; stdout and every frozen regenerated file equal complete bytes",
                      "authority": authority}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["b21", "b11"])
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    main(arguments.workspace.resolve(), arguments.kind)
