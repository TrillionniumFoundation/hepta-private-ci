# 第四轮审计最终附录：证据保全与发布身份

本包保存固定时间窗的 10 份项目原 API、其有界解释、PR #4930 的完整只读增量、C4 preparer 的指定验证历史，以及 root 完成的 840e8b5 格式后继发布原件。原报告预读只保存当时固定草稿，不纳最终 C4 报告、index、config、plan，不形成循环引用。

PR #4930 增量提供固定真实材料的机械执行进展；所有 authority 仍 DENY_ALL，B16/B18 原状态和退出条件不变。main → 840 compare 为 ahead 512 / behind 0，但只返回 300 项文件和 1 项 commit，本包不称已审阅该整体全部源码差异。

preparer 快照 Git 35b9f129e6a2b582e41c83f5db62b49ae688bb66 为 components.validation-06 的原执行版本；validation-05 的 schema 配置不匹配失败和其后 PASS 均保留。包不执行该大 preparer，不重跑其外部全部证据输入。

## 恢复与窄范围核验

```bash
python -B restore_packet.py /path/to/packet /path/to/new-empty-restore
```

恢复程序逐分片、完整 ZIP、全部成员检查字节数 / Git blob / SHA256，并检查原元数据分母、PR4930冻结身份、历史验证回执和实际新发布 commit/tree/parent/ref/merge/PR body 读回。它只执行标准库 JSON/hash 检查，不执行模型、资格代码、Rust、CI、原大 preparer 或原生测试。

Windows formatter 原日志、候选和独审由独立包保留；本包只含 root 的发布原件，不重复打包其作者/独审内容。新后继源的资格仍需其原自动 CI，已有发布身份与格式修正源码审阅不能代替该原生门。

所有 ZIP 分片为最多 400,000 字节的 base64 文本。实际 registry 分别记录物化方式、完整 GET 比较和不可变对象身份；任何只在本地计算的文件摘要不会冒充已登记对象。无 ref/PR 写入或手动 CI 操作。
