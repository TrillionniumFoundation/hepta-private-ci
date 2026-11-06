# B21 原 Intel PTY 工作流：已发布源码证据包

本冻结切点只证明工作流源码、完整树、实际 Git 出版与独立审阅对应。B21 在此原件中仍为 OPEN；后续原生终态另行封存，不并入本包。

## 固定身份

- Source commit: `cc65856cc0b20d03db506c19495d53d61162102d`
- Source tree: `eaded1870d080eaa55efae6208354729140e784c`
- Parent: `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`
- PR: `4902`
- 实际 PR merge commit: `f0355601e362e2ad4947b40d51215e5c4d075fc3`

## 完整原件与恢复

`member-manifest.json` 列出 28 份冻结原件、每份完整字节数、SHA-256 与 Git blob SHA。归档完整保留 `root/` 下的 workspace 相对目录，包括隐藏的 `.github` 文件。只排除 Python 缓存；不重新取出版 API，不覆盖冻结源码和收据。`archive-transport.json` 绑定全部 base64 分片以及无损 gzip/tar 原件。分片是标准 base64 的连续片段，按清单顺序连接后解码。

在拥有 Python 3、Git、Bash 的环境运行：

```sh
python restore_and_verify.py
```

B21 原 verifier 还需要 PyYAML。Windows 出版 verifier 只运行离线字节/Merkle/补丁验证及候选静态 verifier。脚本先验证完整 archive 与每个成员，再只在全新临时恢复目录执行冻结 verifier，比较它写出的全部 proof/tree 原件与冻结原字节，并核对 stdout、stderr、全部其他原件未变、无意外新文件。原始目录不执行会重写证明的 verifier。

`expected-verifier.stdout.json` 按冻结 root proof 的对应字段及冻结 print 语句的字段顺序和编码重建；它不是旧执行 stdout 捕获。`offline-roundtrip.stdout.json` 才是此次恢复执行的真实输出，执行元数据另见 `offline-roundtrip.execution.json`。完整冻结 proof/tree 的比较独立于重建 stdout。

## 实际登记

所有分片、清单、恢复脚本、stdout 与说明随后通过 GitHub `create_tree(content)` 创建不可变无引用对象，逐一 full GET 比较完整 UTF-8 字节；不是 `create_blob` 调用，也不写任何 ref。`registry.actual.json` 与其 self receipt 记录最终实际对象 SHA 和验证结果。登记前本说明不预先声称登记成功。

源码测试、原生执行、编译和格式化均未由本包执行。AGENTS 原文随源码原件完整保留；本包的离线 custody 成功不替代项目要求的 test/fix/fmt，也不构成 blocker 闭合。
