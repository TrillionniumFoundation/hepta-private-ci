# #4855 拒绝 COMMIT 后 pool 复用：现有原始证据独立复核

本轮已取得并核验作者正文指向的两个既有 x230 任务及其完整原件，可以复用 donor 的 SQLx 复用缺陷红绿证据。我们的 B16 候选具有两种独立构造器、原生连接 custody 和更精确的物理断言，这些差异仍需在自己的固定源上验收。没有启动新进程、构建或测试，也没有修改产品、原账本退出条件或 refs。

完整结构化结果见 [独立复核](../../generated-evidence/pr4855-refused-commit-reuse-20261105/independent-review.json)；原始日志与 API 封套按 [无损归档清单](../../generated-evidence/pr4855-refused-commit-reuse-20261105/archive-manifest.json) 保存。

## 固定来源与原件

2026-11-05 16:58:28 UTC 的 fresh GitHub API 仍为 Draft #4855：

- head `3a39c799a3f776b0aeedfce350341d865d3cc1c4`，tree `f83f9dfc55bda251e05746d1c60a4d26f157e752`，base `732e934ba496d90fbe042b8d41d479ef901643e5`。
- 历史失败源为 `3466a3074ab2df88bfae3519f453aa4672c536e5` / tree `5ba499258fd738f0a848bf289c68ba67f76102bf`；通过源为其直接子提交 `f7a57e6f40e3e8220233f0d27b8cfbdf1f721c55` / tree `1f3d38ee52320bba1f345da2f2c54b23a36832ee`。
- 当前 head 的 State 实现 `ec847b1c29b46ce74e7043fab8bac1c00eb8dbda`、State 回归 `20fe71be06d34c6b962d07450d21dcaf72cbbb96`、Memory gate 测试 `ccdc29095b9a4cdc280ddcc1bda643b301891b71` 均与历史通过源逐字相等；已完整读取当前 12,202 项 Git tree，未截断。

首次 GitHub 树和讨论检查仍未发现这份原件。随后按正文的明确 host/job 身份，只读查询 `1a1aafb05fe-fc05-4936` 与 `1a1ab20eb00-fc05-4aba`，得到 authoritative succeeded / exit 0 / complete / durable。两份 stdout 分别为 19,066 B、5,429 B，按独立字节游标取尽，与终态 seen/stored 总长相等。

第二份 stdout 给出了四个已经存在的导出分片及其长度、SHA256。本轮只读取这四个地址，重建 142,236 B ZIP，SHA256 为 `d73aa340816844d4e1fbf619fd0020b9655dea00aa89e1aff0e94f1132465e99`。全部 20 个成员 CRC/字节身份通过；18 份原始流与两份原 manifest 的 SHA256 全部一致。归档没有 JUnit XML，以下逐例证据来自完整原始 Nextest 日志与 catalog。

## 实际测试端点

| 范围 | 原始结果 | 可证明的内容 |
| --- | --- | --- |
| State，失败源 3466 | 1 个 case，两个原尝试分别 0.019s、0.018s，均在 sqlite_pool_tests.rs:45:10 以 InvalidSavePointStatement 失败；recipe exit 100；216 未选中 | 已到达原“拒绝 COMMIT 后仍能开启读事务”的断言，属于实际行为失败 |
| State，通过源 f7a | 完全相同 argv、同 Nextest local profile；同一 case 0.023s PASS，summary 0.034s；216 未选中，exit 0 | 共享构造器在 owner callback 前丢弃 SQLx tracked depth 非零的连接后，原回归通过 |
| f7a 原九包 | catalog 1,312 个独立身份；原日志逐名精确匹配 1,288 PASS / 24 原 ignored，17 个 binary suite；exit 0 | 包含 State 回归 0.019s PASS，以及原 Memory cancelled_checkpoint_fences_a_writer_already_waiting_for_sqlite 0.689s PASS |

两个 State 尝试不是两个独立测试。日志的 final-status 重复打印也未重复计数。九包的 feature union 结果没有代替单包、同筛选条件的红绿控制。原九包中两个 binary suite 的 catalog 为空；没有将它们算成额外行为覆盖。

负例真正执行了 COMMIT 及随后 BEGIN IMMEDIATE，测试源码保留四个占用连接、空结果断言、再次 INSERT 拒绝和 guard 仍为 false。Memory 原 case 保留真实 SQLite writer 等待、取消后 fence、CREATE TABLE 提交拒绝、表不存在、recovery anchor 不变及 writer clone 再拒绝。它使用进程内 checkpoint fixture，没有成为独立 Root 或真实服务接受。

## 与当前 B16 候选的关系

| 比较项 | donor Stage 25 | 我们冻结的候选 |
| --- | --- | --- |
| 入口结构 | guarded 方法委托同一个 coordinated 构造器 | commit-guarded 与 coordinated 是两个独立构造器 |
| 修复判定 | before_acquire 中 is_in_transaction() 为真即返回 Ok(false)，先于 owner callback | 同一判定/顺序分别用于两个实际入口 |
| 连接身份 | 占住其余四个 slot，要求后续读仍可用 | 额外用 TEMP marker 证明第五条物理连接已经替换 |
| 拒绝精度 | COMMIT 与 INSERT 要求 is_err() | 两次都要求真实 SQLite 531 |
| 状态观察 | 原 InvalidSavePointStatement 与固定 SQLx 源相互支持 | 还要求原 SQLite autocommit 与 SQLx tracked depth 同时观测 |
| 新连接 callback | 共享实现保留原 callback | coordinated 控制还核实际 checkout 次数 |
| 生命周期与 owner | donor 原 commit-hook 闭包 | 另有 native lifetime token、collation anchor 与原 owner custody |
| 默认 pool | 默认 durable API 也经共享 guarded 路径 | 普通默认入口保持原独立范围 |

因此可以直接复用“固定 SQLx 0.9.0 下的 stale-depth 缺陷、discard 修复方向及 donor 对应回归”的已存在证据，无需再创造同一 donor 实验。我们的两个已冻结控制继续保留；不新增镜像测试，也不拿 donor 的宽泛错误断言代替它们的 531、物理连接替换或 custody 断言。

## 资格边界

源码、锁、binary 哈希和 unchanged 标记来自原任务 manifest；本轮逐一验证 raw 流、source Git blob、锁字节哈希和 catalog 路径对应，但没有再次读取或哈希历史 binary 实体。匹配单包与九包的 State binary 哈希确实不同，原件明确保留，不混为同一个程序。两次 matched 命令及 local profile 相同，完整环境字节相同并未被本轮独立证明。

这份证据限定在历史 3466/f7a 源和其记录的 Linux x230 / Rust 1.96 执行。三个相关源文件在当前 #4855 未变化，不等于当前 Stage 50 已重新执行，更不等于我们的 eed 产品、其他平台、完整 Memory 恢复、Current / issuer / FinalUse 或 B16 整项闭合。先前 RAW_NOT_RETRIEVED 回执保持原样；本轮是通过新的只读证据入口补足原件，另行登记。
