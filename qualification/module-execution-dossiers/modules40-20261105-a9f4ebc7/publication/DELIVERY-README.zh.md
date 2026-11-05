# 40 模块本轮交付与证据索引

本轮交付包含实际源码集成、原生回归、40 模块源码导航校验及逐模块发展情况报告。报告和原始回执共同保留已通过范围与未关闭门槛。

## 阅读入口

- [40 模块完整中文报告](../module_matrix/HEPTA-40-MODULE-DEVELOPMENT-FACTS.zh.md)：逐项列出职责、固定源码根、owner、caller/writer 状态、操作数、本轮变化及下一步。
- [源码 PR #4869](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4869)：保留为 draft。
- [原生执行独立审计](../product_recovery/native_audit/independent-native-run-audit.md)：两轮原始运行、59 项关键用例和源码身份。
- [C1 原检查汇总](native-evidence/qualification-c1-summary.json)：全部真实命令、退出码、源码身份和原日志哈希。
- [最终平台状态](github-final-gates.json)：GitHub 合并状态与 CI 的独立快照。

## 固定版本

| 用途 | Commit | Tree |
| --- | --- | --- |
| 两轮四包原生测试实际运行版本 C58 | `58c81ccdd25002ae0f481d434af067a56fa7ddb8` | `57809be09ef01c02389ef37a817f1447d13d167b` |
| 40 模块导航与严格校验版本 C1 | `5e917b9f5fb3e841dbcaefcd5bbbf59b32f20411` | `5f02eb87cce34d40d6ddf21722305192b4fa00d7` |

C1 仅增加 26 张 Map 的当前导航更新和一份旧记录账本，唯一 parent 为 C58。全仓除固定 Map/账本外的 10,795 个 tracked entries 完全相同；[原生等价收据](native-evidence/navigation-execution-input-equivalence.result.json)明确记录未在 C1 重新执行 Rust 测试。

## 实际结果

| 检查 | 结果 |
| --- | --- |
| Run1，原始四包完整套件 | 697 执行，696 通过、1 失败、66 跳过，exit 100；原长临时目录触发 Unix socket `SUN_LEN`。首次及一次原 retry 都失败，未生成 JUnit。 |
| Run2，同 C58、短临时目录及仅报告输出配置 | 697 执行，697 通过、66 跳过，exit 0；1 项慢测试，0 flaky/retried。 |
| 59 项关键用例审计 | 原 49 项加 e65 的原 10 项，全部恰好执行一次且通过；没有过滤原套件。 |
| 原 Map qualification | 40/40 通过，原严格 profile 与 expected SHA/tree 保留。 |
| 原模块文档 qualification | 40 份技术文档、40 个源码绑定通过。 |
| 原 registry/status 检查 | 40 个模块、51 个 Hepta crates 登记一致；2 项状态事实测试通过。 |
| 导航再次预览 | 40 张检查，0 改动，未生成第二份账本。 |

## 可复核性

原始 Run1 日志和失败收据、Run2 日志与原生 XML、固定执行 manifest、未修改的 JUnit checker、独立审查及导航前像均保留。Run2 的 Cargo metadata 以原字节的 gzip 保存；解压后的 SHA-256 为 `46c44dc18560eee9f3ecc3ab72a4b7389b61a637b4c9b924210c377f61e3f988`，可与实际执行收据交叉核对。源码测试与导航资格分别绑定各自的真实版本，没有把较早执行记录改写成较新版本执行。

## 仍需完成

真实 authority/provider、配额和硬件/model grant、完整 Control lifecycle 与路由 CAS、独立 custody/批准链、默认 Decision/Outcome 和学习环、真实 Memory 上下文组合、Matrix/Servo/UI 外部验收及 Windows hostile inherited ACL 资格均保留为独立门槛。ConPTY 改动只涉及编译兼容。

快照时 GitHub 的目标分支确为 C1 的祖先，compare 为 ahead 19 / behind 0，但 PR API 仍报告 `mergeable=false / dirty`；C1 没有 check-runs，提交状态接口为 pending 且无 status 记录。本交付没有把这些平台门槛、全部模块生产资格或 activation/release 标记为通过。
