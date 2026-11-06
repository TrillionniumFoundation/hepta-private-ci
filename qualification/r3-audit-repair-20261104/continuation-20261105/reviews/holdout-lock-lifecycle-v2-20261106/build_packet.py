#!/usr/bin/env python3
"""Package exact frozen author bytes; no network, source mutation, or execution."""
import base64
import hashlib
import json
from pathlib import Path
import re
import zipfile


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    packet = Path(__file__).resolve().parent
    author = packet.parent / "holdout-lock-lifecycle-v2-20261106"
    freeze_data = (author / "freeze-manifest.json").read_bytes()
    freeze = json.loads(freeze_data)
    assert len(freeze["files"]) == freeze["members"] == 141
    members = list(freeze["files"]) + [{"path": "freeze-manifest.json", **identity(freeze_data)}]
    members.sort(key=lambda x: x["path"])
    archive = packet / "candidate.original.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for entry in members:
            data = (author / entry["path"]).read_bytes()
            assert identity(data) == {k: entry[k] for k in ["bytes", "git_blob", "sha256"]}
            item = zipfile.ZipInfo(entry["path"], (2026, 11, 6, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            z.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    data = archive.read_bytes()
    encoded = base64.b64encode(data)
    parts = []
    for offset in range(0, len(encoded), 400000):
        path = f"candidate.zip.part-{len(parts) + 1:04d}.b64"
        chunk = encoded[offset:offset + 400000]
        (packet / path).write_bytes(chunk)
        parts.append({"path": path, **identity(chunk)})
    manifest = {
        "schema": "hepta-holdout-lock-lifecycle-v2-portable-packet-v1",
        "decision": "NARROW_COMMENT_REVISION_READY_FOR_REVIEW",
        "source_head": "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed",
        "candidate_actual_tree": "605720504e547296dca1c78914fee5ed6d29844d",
        "archive": {"path": archive.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "parts": parts,
        "members": members,
        "original_author_freeze": identity(freeze_data),
        "expected_verifier_stdout": identity((author / "static-v2.stdout.json").read_bytes()),
        "qualification": {"original_mac_cause_proven": False, "project_tests_compilation_fmt_executed": False, "new_OS_mechanism_execution": False, "refs_or_CI_modified": False},
    }
    (packet / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    assessment = (author / "README.zh-CN.md").read_text()
    # The complete original README remains in the archive. Public derived copy
    # renders archive-only paths as text, rather than creating broken repo links.
    assessment = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: m.group(0) if re.match(r"https?://", m.group(2)) else f"{m.group(1)}（恢复包内 `{m.group(2)}`）", assessment)
    (packet / "ASSESSMENT.zh-CN.md").write_text("本页从冻结 README 派生，仅将包内相对链接改为恢复路径文字；原字节 README 完整保存在无损包中。\n\n" + assessment)
    (packet / "README.md").write_text("""# B15 v2: three parameter comments, immutable evidence package

[完整评估](ASSESSMENT.zh-CN.md)记录固定源、原 Mac ARM 114P1F、受控 Linux 机制实验和两路径候选的资格边界。原 Mac 具体持锁者仍未知；Rust/项目测试/rustfmt 未执行。

将本目录全部分片与 manifest、restore_packet.py 放在同一目录，运行：

```sh
python restore_packet.py --output /new/empty/holdout-review --replay
```

恢复器拒绝覆盖现有目录，验证所有分片、ZIP、142 个成员与作者 freeze，再重放静态 proof。它不会运行 Rust、OS 机制实验或 CI。完整两份候选源码、原断言、原件与 primary 均在恢复包中；审阅状态以冻结时点为准，后续独审/根审另行绑定。
""")
    print(json.dumps({"members": len(members), "archive": manifest["archive"], "parts": len(parts), "freeze": manifest["original_author_freeze"]}, indent=2))


if __name__ == "__main__":
    main()
