# 残余 npm 依赖修复与完整审计证据

源码为 PR #7072 的 `e4f2cfa6f4f6bbc356ae20200eda3cd78ab92dd1`，父提交为 `356877c2d1d5225e97e0417683a5e5a7f8e2c1fc`。仅变更 `package.json` 与 `pnpm-lock.yaml`，补齐 Babel、Hono 和 HumanFS 的三个精确 resolution。

冻结 v1 包含 9 份原始锁文件、157 条原始告警、完整范围比对程序与输入、独立补丁审查、生成及安装记录、首次 SDK 47 项测试的 18 次通过与 29 次失败、缺失夹具恢复、格式检查和源码发布回读。全部 81 个负载成员与清单逐项校验，离线比对可复算。

指定快照在 #6799 父提交剩余 4 条 npm 匹配；候选 npm 锁文件匹配 0/114。Rust/Python 锁文件继承父提交，未在此补丁重新迁移。此记录不是新的服务端扫描、默认分支告警关闭、漏洞可利用性证明或合并批准。

原生 SDK 构建及完整 Jest 在冻结时仍进行中。v1 保留 pending，终态另行追加；父提交通过的 CI 不替代候选及其托管合并树。

## 恢复完整原始归档

在证据分支的完整 checkout 中运行以下命令；输出目录必须尚不存在：

```bash
python qualification/hcsn_evidence_transport_20261125/reassemble.py \
  --repo-root /absolute/repo \
  --index /absolute/repo/qualification/hcsn_dependency_followup_20261125/INDEX.json \
  --output-root /absolute/new-dependency-evidence
```

恢复后的原始归档为 `qualification/hcsn_dependency_followup_20261125/raw/dependency-evidence-v1.tar.gz`。解包后参照其 `README_ZH.md` 执行离线审计。`ARCHIVE_MEMBERS_V1.json` 给出全成员清单，`TRANSPORT_VERIFICATION.json` 记录独立字节校验。

每个传输部分均为真实、单成员 gzip，解码上限 479,000 字节，编码上限 480,000 字节。恢复过程在创建输出前检查全部部分及整体 SHA-256 与 Git blob 身份；原归档没有重写。


## 原生 SDK 终态追加（2026-11-25）

原始 v1 冻结包保持不变。`terminal_v1/` 保存最终原生构建、完整 SDK 测试和本地重复构建取消证据；`mcp_scope_v1/` 保存 MCP 内层报告、原回归基线及离线复核程序。两个归档可直接用 tar 解包，每个成员均有 SHA-256，根代理独立校验见 `terminal_v1/ROOT_VERIFICATION.json`。

候选源码 **e4f2cfa6f4f6bbc356ae20200eda3cd78ab92dd1** 的原托管 SDK job **138957422954** 成功：原 Bazel 目标构建完成，共 25,041 个 actions；原始 Jest **47/47 测试、5/5 suites 通过，0 跳过**。Job 从03:30:41到03:39:33 UTC，共532秒。工作流明确检出 PR source 并检查 HEAD 等于 SOURCE_SHA，因此本结论绑定该 source。完整日志727,947字节，SHA-256 `1c0da88f9f80581c85d0b04d8d51f6606d56decd8b0c56f09276c6c23fe242fd`。Python SDK、cargo-deny 两个候选 jobs 也成功。托管环境未发布可执行文件校验和、CPU 或峰值内存，相关值保留空值。

既有 SDK 回归门禁通过不等于全部 MCP 协议检查通过。原 conformance 报告 **1119 PASS / 28 FAIL / 7 SKIP**，review 报告 **162 PASS / 24 FAIL / 0 SKIP**；两个 overall success 都为 false，既有 regressionGate 则都为 true，新增失败、缺项和配置错误为空。这些已知失败继续诊断，未扩大 baseline，未将 skip 算作 pass。

确认精确候选托管结果后，本地重复冷构建通过所属 PTY 正常取消，独立 Bazel shutdown 成功；分类为 `CANCELLED_AS_REDUNDANT_AFTER_EXACT_HOSTED_PASS`，不算本地原生通过。实测 driver wall2550.8485秒；取消前采样 CPU1368.6931秒、MemoryPeak8,589,934,592字节仅为已观测值，未推断完整清理 CPU。原始中断及显示异常完整保留。

本追加关闭本候选“缺精确源码原生 SDK 验证”的阻塞；不代表默认分支157个告警已关闭、其他分支通过、MCP全协议通过或整个PR可以合并。
