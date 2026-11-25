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
