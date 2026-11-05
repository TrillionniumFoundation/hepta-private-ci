# V7 原 CI 与发布迁移证据包

本包冻结旧 `5b6331250ff459033bd44d1a95daec70131277cc` 的原 main Windows 终态，以及发布到 `eed4d6bb61b789b19f60facc79f9e031765fa4c9` 前后的 API 原件。旧头截止 snapshot0078，新头截止 snapshot0004（2026-11-05 16:39:47–16:39:48 UTC）；各次查询和日志本身的观察时间独立保留。

共 139 份完整文件，78,260,373 字节。无损 gzip 压缩包为 30,597,514 字节，拆为 85 片严格 base64；每个片文件最多 479,997 字节。5 个完整 ZIP 共 141 个成员：四个 main Windows 分片 140 个成员，加 Clippy 的原执行日志成员。完整 ZIP、API、原日志、具名投影与审查源码均可恢复。

## 结果范围

四个 main Windows 分片的 V2 投影保留 8,841 个最终物理 libtest 结果行，并与每个原 harness 汇总逐一匹配。最终实际失败为 Memory 1 例与 Core 4 例；另有 2 个 Core 原例出现失败 attempt 后最终通过，全部 attempt 正文仍在包内。Core 原日志中的 26 个重复名字保留其物理多重性，未据此推断重试或删重。

B22 的 13 个 Windows 原例和 B13 的九例 Lease / Queue 原合同已有完整具名结果、固定源码与拒绝控制审查。包内两份独审保留各自冻结时的状态；根审后续正式接受 B13/B22 后的台账及收据独立承接，不改写早期原文。

main shard2 / Clippy / Windows release 的宏歧义编译失败仍是该旧头的真实失败；Core helper/managed deny-read/metadata/outside-root 的具体失败与 Memory expiry 失败也没有被整体目标统计覆盖。cargo-deny 原日志尚未取得，Transport closed 与不受支持的 bounded API 响应已保留，原因仍未知。

## 发布迁移

PRE snapshot0077 保留旧头 86 jobs；POST snapshot0078 保留旧头 92 jobs。24 个原 queued jobs 在新发布后的窗口变为 cancelled，另有六个新实例化的 Rust children；旧头此前已有的两次取消不倒推归因。没有手工 cancel、rerun 或 dispatch。

新头与合成 merge 的真实 Git 对象都已读取：新头 tree 为 `ca1c4671ef6b2773280d01b5d76c6166252f5856`，merge `3476a8c535f7090c4c868ac85148491b3fdfd983` 的父对象为固定 base `63652be658ebed8d3052eb789b951793384fd5e4` 与新头，tree 完全相同。API 的当前 PR head 可以是新头，而一页 workflow 的过滤 head 仍是旧头，原 envelope 明确保留两者。

新头 snapshot0004 的成功 job 只按 API 状态记录，包内不推导这些新运行的具名用例资格。随后取得的原日志应追加为新的不可变增量。顶层 workflow queued 也不表示其内部没有已经运行或完成的 job。

## 验证与读取

将 [transport manifest](../../generated-evidence/v7-main-windows-publication-cut0004/transport-manifest.json) 所列的 85 个片文件、两个 manifest 与 [verify_archive.py](../../generated-evidence/v7-main-windows-publication-cut0004/verify_archive.py) 保存在同一个本地目录，再执行：

```sh
python3 verify_archive.py
```

验证器严格检查每片长度/SHA256/Git blob 身份和有序 offset，消费完整 gzip trailer/CRC，并逐项检查 TAR 的 139 个安全相对路径、文件长度与 hash。它不执行项目代码，也不提取任意路径。八份本次新增 main job.log 还逐字对照各自原 API content，CRLF 未被换行导出改写。

所有输入身份见 [original-files-manifest.json](../../generated-evidence/v7-main-windows-publication-cut0004/original-files-manifest.json)，ZIP 成员见 [complete-zip-member-manifest.json](../../generated-evidence/v7-main-windows-publication-cut0004/complete-zip-member-manifest.json)，时点及范围见 [scope-summary.json](../../generated-evidence/v7-main-windows-publication-cut0004/scope-summary.json)，实际校验见 [verification-receipt.json](../../generated-evidence/v7-main-windows-publication-cut0004/verification-receipt.json)。派生逐名 JSON 只在完整无损包内保存，避免以超限大 blob 再次提交。
