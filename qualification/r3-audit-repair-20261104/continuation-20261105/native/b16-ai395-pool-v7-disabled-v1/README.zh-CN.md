# B16 pool 阶段：冻结输入复核与 disabled 执行模板

本包只准备原冻结 `epoch-pool` 的接续模板。**没有启动 pool，也没有把 driver 的两次 provider 工具超时当作执行或产品失败。** driver 的真实终态、后树、生成锁与对应 metadata 尚未取得，所有相关输入均为 `null`；当前请求 `execute=false`，审批引用与外层执行 guard 均为空。

## 接续边界

launcher 保留 driver 版本的十个文件、工具及 OpenSSL/libcap/V8 守卫函数。它先验证真实 driver 的 `QUALIFIED` 终态、runner 与 launcher 双零退出及外部依赖 finally，再核对 driver 的 enabled binding、原 `epoch-entry`/`epoch-final` 两份完整源码守卫及 metadata 的原前后守卫。

driver 的初态来自已通过 foundation 的真实终态；这里没有把 driver 初态强制成 `final_A_tree=4a3374…`。driver 生成的 Cargo/MODULE 两锁可以与其初态不同：初态锁须与 foundation 终态相同，pool 的两锁则须与 driver 真实终态相同。所引用的 metadata 必须来自 driver 原成功的全工作区 `cargo metadata --format-version=1 --locked` 命令，前后守卫均处于 driver 的实际终态源码与锁。原 V7 随后仍会核完整依赖图。

当前实际八项工具、环境、两个 SDK、V8、普通 HEAD/index、P4 的 BUILD_ONLY 身份和 ROG 历史 A 测试原件保持原值。P4 的 `4a` 只用于原构建来源；ROG 的 `fb9` 仍是历史测试来源。两者均不能替代 driver 的实际后树。新增的 driver 原守卫引用只要求回收已有原件，不增加 native 探测或重跑命令。

## 精确执行范围

| 次序 | 原冻结动作 | 必须取得的结果 |
|---|---|---|
| 1 | `pool-binding` 四路径 | 原三份前像和一个不存在的新路径逐一匹配，应用固定后像 |
| 2 | `pool-patch` 一个源码变体 | 仅去掉 state 两个池构造处的 native lifetime token 绑定 |
| 3 | state 负控两例、Memory 负控一例 | 三例各自命中原物理断言；每例必须是普通 libtest 101，原 `just` 退出 100，不能接受超时、leak、skip 或其他失败 |
| 4 | `pool-restore` 一次 finally | 仅在仍拥有 exact 负控源码、普通 index 与锁未漂移时恢复；主错误和恢复错误分别保留 |
| 5 | 同三个原用例正向执行 | 三例全 PASS，0 retry；ignored 子进程入口只由原父控制显式调用，不另计 PASS |

两个 state 控制分别在真实 native open 和 initial PRAGMA 的回调内取消。父进程观察物理竞争锁后，还必须收到 `gate_status=0`，才能把原第 107 行锁断言失败计为有效反例。Memory 控制先证明连接可查询、竞争锁被拒，再移除 commit hook 和保留 collation，仍能查询后才在原第 20 行检验竞争锁。它不执行被移除 commit hook 后的写入，也不把 Arc 计数当物理关闭。

原 29 个安装输入、25 项 integrity、全部 source payload、case 名单、实际命令、物理 oracle、预算与 `negative_with_finally` 均逐字保留。本包没有新增测试或改动项目源码。`B16_pool_binding_*` 是 B16 内部阶段标签，不是原 23 项 blocker 的退出状态。

## 容量与启动条件

本模板保留已有保守启动门 **48,517,479,536 B**：原已核 396 文件 output family 18,517,479,536 B，加 Cargo 12 GB、Bazel 8 GB、证据 2 GB 与保留空间 8 GB。pool 本身不运行新的锁生成或 Bazel 阶段；这里仍保留该较保守额度，没有为了后续启动降低预算。启动前须读取 fresh free，原每命令 8 GB 门继续生效；这些数字是规划额度，不能证明编译峰值，也不授权删除任何 cache。

Root 只有在 driver 实际资格与后树收据齐全后，才能具体化此模板并另行启用。模板不包含预测的 driver tree、锁哈希、metadata 哈希、job ID 或通过状态。

## 本次完成的静态核验

已对八个相关固定 source body 复算 Git/SHA256/字节数；逐段核对两处真实 token 绑定、仅删除绑定的负控、三个物理控制及恢复。launcher 只做 Python AST 解析和源码身份比较；十个外部守卫函数、29 文件安装包、25 项 integrity、工具/环境/历史输入及容量参数均与已审 driver 版本一致。**没有执行 launcher、项目测试、额外 harness 测试或任何 native 命令。**

`manifest.json` 与 `pool-input-scope-oracle-review.json` 给出完整来源、精确用例和判据。`launch-request-DISABLED.json` 是大于 512 KB 的传输包，只提供本地完整原件及哈希；Git 映射保存小文件及其来源，安装包本身与既有 V7 完全相同。
