# 当前检查点：c1d6537 的 Linux 原生组件验证已通过

当前代码是 [PR #5896](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5896) 的 `c1d6537f7d979e1ad792eee796c6709d23a86697`，tree `e7762b742e6baff12e447a89f40ae1cfb68aa7e1`。两套 Linux job 已完成并成功；原执行记录与前后源码清单都绑定这个提交和 clean tree。机器可读入口是 [CURRENT_CHECKPOINT.json](CURRENT_CHECKPOINT.json)，完整新结果是 [native-c1d/RESULT.json](native-c1d/RESULT.json)。

| 实际执行 | 原始结果 | 证据 |
| --- | --- | --- |
| Daemon 普通库测试 | 1,158 passed，0 failed | [原记录](native-c1d/artifacts/daemon/ordinary.json) · [JUnit](native-c1d/artifacts/daemon/ordinary.xml) |
| 单独选择的 Root 组件 parent cases | 7 passed，0 failed；实际 fixture UID=0 | [原记录](native-c1d/artifacts/daemon/root.json) · [本次 Root JUnit](native-c1d/artifacts/daemon/root.xml) |
| Shared Cell framework 库测试 | 1,196 passed，0 failed | [原记录](native-c1d/artifacts/shared/tests.json) · [JUnit](native-c1d/artifacts/shared/junit.xml) |

Model 7 项、Original Evaluation receipt 5 项、Original Training receipt 6 项，在两套库测试中都逐名通过。[TARGET_OWNER_TESTS.json](native-c1d/TARGET_OWNER_TESTS.json) 保留这 18 个不同用例的首条实际 PASS 行及位置，重复打印不重复计数。两个 suite 有重叠，1,158 与 1,196 **不得相加**为独立用例或任务数；两次运行也不会变成 36 个不同目标用例。

Root 使用本次新生成的 7-case XML；旧普通 XML 被明确排除。它验证 Root 组件 parent cases，**不构成 daemon 与 Root 普通业务双进程退出、重启闭环的验收**。

原 CI 的格式检查、三包 scoped fix 和 bins-check 全部退出 0，维护 patch 与 postimages 为空。6 个源码快照均包含 14,415 个文件，解压后的完整 inventory 字节相同；[源码清单记录](native-c1d/SOURCE_INVENTORY_EQUALITY.json) 与 [artifact 索引](native-c1d/ARTIFACT_INDEX.json) 保留身份、字节数和 SHA-256。下载的两份原 ZIP 还分别匹配 GitHub 发布的 artifact digest。单个完整 inventory 压缩文件超过仓库 blob 上限，其原字节保留在原 artifact 与本地 ZIP，仓库收录摘要和校验记录，未拆分 blob 规避上限。

## 历史检查点和验收边界

原 [README.md](README.md) 与 [RESULT.json](RESULT.json) 是 03:03 状态快照，记载当时 `PENDING_HOSTED_LINUX`；49 个历史文件保持原样。这份新增检查点记录后来取得的真实 PASS。`30692d7` 的 56 项源码检查、225 边界全局扫描和原 E0659 编译失败仍归属原提交，没有改写成在 `c1d6537` 上重新执行。原本地资源失败也完整保留。

**普通完整链、正向采用链、NoUpdate/rollback 生产链，本次验收计数仍各为 0。** 独立普通 C FinalUse 与 daemon/Root 普通双进程重启未验收。原 owner / Dataset / B / Proposal / stage 装配的具体剩余输入见 [六段验收差异](acceptance-delta/ACCEPTANCE_DELTA.md)。组件测试和源清单通过不授予生产角色权力。

Core 的 `50c382e3` 仅发布了原断言锁作用域修复：[原记录](core-scope-repair/MANIFEST.json) · [远端绑定](core-scope-repair/PUBLISHED.json)。此前 `b5019ee9` 的同树 merge 完整 Core unit target PASS 与 Windows job 失败分别保留在 [原观察](core-b501-observation/OBSERVATION.json)，没有转移为新 Core 提交的 native PASS。其余 architecture / blocking CI 状态单独记录，不由本页两套成功的 Linux owner job 推定为全仓通过。

原 host inventory 的新增只读恢复观察保存在 [脱敏记录](host-access/h-background-inventory-recovery-20261111.json)。它确认原生后台 inventory operation 完成，仍未恢复原两个 shell job ID；没有启动新 shell，也没有形成普通任务或角色保管证据。
