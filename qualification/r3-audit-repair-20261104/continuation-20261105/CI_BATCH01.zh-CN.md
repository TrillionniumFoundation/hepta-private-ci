# 第四批发布源的首批原 CI 原件归档

本包绑定 PR #4797 的已发布头 `0e139b599f0fe451f80fb7db4b2913bb9c679dce`，产品树 `091e659e0da6602299fd14cfa93889191405edd8`。普通合成检出为 `e93aefbbb33438f6ec67e995adcfe88657158487`，其树与发布树相同。所收运行均为原始 `run_attempt=1`；未触发重跑、取消或新作业。

API 截止时间为 **2026-11-05 06:56:34.030 UTC**。首批包含明确列出的十个终态作业：九个选择范围通过的作业，以及一个真实 musl 平台解析失败作业。完整原件共 **201 件、20,678,953 字节**；压缩包 8,453,934 字节，分成 43 个严格 base64 文本块。每块均实际写入 Git blob 并读取核对；这不等于每个原成员单独上传。重建后的压缩包与所有成员长度、SHA-256 和 Git blob 身份均须吻合。

| 已收范围 | 原件所支持的结论 | 不能外推的范围 |
| --- | --- | --- |
| Windows Core lifecycle | 完整 8 分片实际列出 2,343 个不同测试标签：2,340 通过、3 忽略；其中 7 个 `should panic` 标签保留规范化映射 | 不包含 Core 集成测试；不能替代 cold-root、CodeMode 或全平台资格 |
| Windows retained/private state | 原 XML 532 通过；原命令另有 7 个筛选跳过；两项私有目录拒绝用例实际通过 | 不计为未合入 B16 提案执行；不隐藏筛选跳过 |
| Windows ordinary business | 三目标原正文实际 78、19、21 项通过 | 不等于真实外部 Bao、Chain、HIA 或 operator 接受 |
| Operator Intel/Windows/ARM 四作业 | 各自真实签名夹具范围与 XML/原日志保留；Intel 33、Windows 40、ARM 33/33 | 是仓库夹具资格，不能当真实 operator 执行回执 |
| Exec Linux source、Mac ARM merge | 各 13 项 resume 通过；rollout 125；server 379/383；筛选跳过 62/76 保留 | 不继承为 Windows；独立 scope 通过不解释先前 full 的 proxy 偶发失败 |
| 真正 musl product smoke | 原 cquery 返回两条相同 canonical label，解析器按行数唯一而失败 | 构建、ELF 和实际 binary 执行均未到达，不是产品构建通过 |

后续 Intel PTY 真实失败、其他取消或新增终态另作增量；本包不回写旧快照，也不改变原 23 个 blocker 的退出条件与闭合状态。

## 复核入口

从本仓库归档目录运行：

```sh
python3 generated-evidence/batch-01/verify_archive.py generated-evidence/batch-01
```

该命令只核验归档身份，不执行产品或测试。完整成员清单、压缩传输说明及上传回读收据分别保存在 [原件清单](generated-evidence/batch-01/original-files-manifest.json)、[传输清单](generated-evidence/batch-01/transport-manifest.json) 与 [Git 回读收据](generated-evidence/batch-01/blob-upload-receipts.json)。取消原因只有原 API 和日志明确证据才作判断，本包不补推测。
