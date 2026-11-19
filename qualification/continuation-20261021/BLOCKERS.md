# 未闭合事项与下一条可执行动作

本轮完成了真实修复、提交、推送、限定范围的 native/Python 验证及证据复核。
**尚未达到用户定义的“全部 blockers 闭合”。** 所有研究继续
SHADOW_ONLY / DENY_ALL / NO_GO；没有生产 promotion 或设备 effect。

## 已有修复且完成局部验证

| 问题 | 本轮处理与提交 | 尚须完成的资格 |
| --- | --- | --- |
| Git replace、隐藏 index flags/fsmonitor 可误报执行身份 | #2968 f740/0cb，最终保留于 b114；真实负控与54项回归通过 | 新 source 的远端完整架构与平台门禁；不是任意 hostile Git 配置下的 hermetic 执行保证 |
| Memory 测试 SQLite/expect Clippy | canonical durable test pool 与等价 cfg 拆分；最终包 strict Clippy通过 | Windows/macOS/Bazel 全矩阵 |
| manifest-only Bazel 未声明可选 binary 导致 panic | 保留现有 NotFound error、declared-path 校验与 Cargo fallback；实际锁定 package 2/2通过 | Windows Bazel 原始失败 job 的新 head 重验 |
| migration 15 fixture 仍只期待1..14 | 原样复用 #2743 两行修复，所有安全断言保留；最终 Memory 272通过、7原有ignored | ignored资格/stress/crash probes及各原生平台不在本轮验收范围 |
| 三项 TLS patch advisories | b114 中真实 Cargo/Bazel 双锁升级，生成稳定/原check通过，deny7→4 | 新 exact head 安全与平台CI；9条Windows resolver边仍需原生验证 |
| parent 更新导致旧 event base 与实际 merge ref 不符 | b114 同时保留0cb与98b两个祖先；tree独立一致 | 新架构 source-head/current-base merge 作业终态 |
| Reader receipt context/checkpoint/digest alias 未严格绑定 | Draft #2969 ca276；125项全套、独立负控/兼容检查通过 | 该source完整CI、模型/统计/成本/来源资格仍独立要求 |

## 仍阻塞的工作

| ID / 状态 | owner 与已证根因 | 下一步与闭合条件 |
| --- | --- | --- |
| DEP-01 / OPEN_SOURCE | basic-toml0.1.10停维护；当前路径codex-secrets→age0.11.5→i18n-embed-fl0.9.4→i18n-config0.4.8；现有owner #2961 c210d263 | 读取该owner60-file diff，隔离复用经checksum核验的i18n-config backport；保留本轮TLS与并行改变，实际重生两锁。该PR没有MODULE.bazel.lock不能直接当完整解法；新树deny、相关包、跨平台及required全通过才闭合 |
| DEP-02 / OPEN_SEMANTIC_MIGRATION | 当前keyring4.2.0→zbus-secret-service-keyring-store1.0.1→zbus5.19.0引入zbus_names4.3.4/zvariant5.15.0/zvariant_derive5.15.0；三个维护advisories仍失败 | 与现有backend owner核对认证、持久性、DBus交互与权限行为，评估维护版本或同语义后端迁移；#2917旧keyring3/zbus4修复不直接覆盖。必须保留真实secret-service语义、双锁和原安全测试，不能删feature/ignore求绿 |
| CI-01 / QUEUED_PENDING | #2968 b114 的blocking、Architecture、UI和原生作业新建 | 查run39528171977/39528172005/39528171904及当前SHA全部checks；下载真实失败log聚类，source与实际base同验。CI required与Architecture required均完成success，所有必需平台scope成功后才可能合并 |
| CI-02 / OPEN_NATIVE | 父owner98b修复Windows runfiles/handles，但原始Git-wrapper、RPC/metrics、sandbox/helper、guardian等失败未全部新head复验 | 在Windows runner逐一对原job118912167995/118912168129/118912241314的新对应scope验证。Linux local pass与源码patch不等于全部Windows关闭 |
| CI-03 / BLOCKED_EXTERNAL_VISIBILITY | 组织runner online/busy、groups、配额和完整protection API不可访问；queued记录本身不提供原因 | 取得相应只读runner/protection端点或管理员导出，按labels/并发group/queue age/利用率定位后再调整。解锁前不宣称runner未打满，也不擅自取消覆盖 |
| CI-04 / OPEN_REVALIDATION | 历史native/macOS ENOSPC与V8上游503有真实失败日志；部分V8仅metadata成功 | 在有足够磁盘且上游可用的原target重新跑；保留失败证据与全部source build。无需把它们归咎于本轮新源码，也不能标success |
| AUD-01 / INCOMPLETE_AUDIT | metadata全量、14 ancestry比较、35非草稿门禁完整；2,967PR逐源语义/review/完整policy未完成 | 优先处理已定位owner和冲突根；逐项比较功能/安全/性能/回归再关重复/临时PR。#1504/#2937深分叉、#1468/#1508大量差异，不能按时间/编号覆盖；现无已认证merge候选 |
| SCI-01 / BLOCKED_RESOURCE_AND_EVIDENCE | 历史Memory40+72已重验但非新holdout；本轮新Memory调用0；最终本地free约1.8GB，原Qwen权重6.18GB且缺runtime/GPU | 在可实际访问的合格资源上冻结新数据/模型/runtime后执行40+72；逐调用保留原答案/来源/引用/成本。远端64 Reader不替代该目标；当前资源观察不是永久硬件结论 |
| SCI-02 / NO_GO | 新Reader64来自16个仓库诊断cases；温度clamp、confidence未校准，缺完整向量/权重逐文件清单及全成本 | 补独立heldout/未来窗口、counterbalanced presentation、完整checkpoint/resource/calibration join与独立语义引用审核。完整上下文16/16并不证明生产泛化 |
| SCI-03 / SHADOW_ONLY | SharedStem/Memory/NDU当前契约与确定性建议器存在；没有本轮真实训练收益/多模态/负迁移/FBSDE最优性证据 | 按RESEARCH_NEXT_PROTOCOL预登记baseline/ablation/holdout及Pareto口径，记录真实预算，不把配置value_gain或接口一次driver调用当质量证明 |
| OS-01 / BLOCKED_OWNER_INTEGRATION | broker有Linux同UID transport认证，缺A05应用身份和A07原owner effect/Final-use/耐久K-D回执；SubmitEffect/CancelEffect仍deny | 在既有owner下添加内置认证adapter、签名/代际/撤销与即时Final-use；UI不可写owner账本或自证confirmed_by_owner；再做崩溃/重放/未知结果回收 |
| OS-02 / OPEN_SOURCE_FINDING | #210/#218相同broker blob的sessions无实用数量/peer配额/TTL，只有显式close回收；handle丢弃不回收 | 在该owner child加有界admission、失败不耗ID、close释放与跨peer配额测试；本轮只源码审查和UNEXECUTED诊断，不声称已部署远程DoS或实际攻击验证 |
| OS-03 / BLOCKED_NATIVE_DEVICE | #224/#225再次更新到49e5582d/9476f50e，01:54:37各6 success、1 exact-kernel-ktest in_progress；没有本轮physical desktop/mobile证据 | 对每个新combined head检查完整kernel artifacts；分别认证Windows/macOS/Linux/mobile peer、pairing、权限申请、撤销、断线、收据和真实设备性能，未知effect一律deny |

发布前增量：Reader ca276的Windows Bazel分片1/4、2/4、3/4也已失败，
job118977201830/118977201936/118977201768；该新状态纳入CI-02。随后取得真实日志，确认Git wrapper readiness、helper路径、
RPC错误码、matrixd socket等签名及其他权限/断言失败；尚未完成每个目标的实现根因分析。
#2968的Windows private-state专项成功不覆盖其他Windows Bazel测试。详见
[PUBLICATION_DELTA.md](PUBLICATION_DELTA.md)。

## 继续执行的精确入口

先在新、完整 checkout 中固定已推送源码；不要使用带skip-worktree的稀疏工作树
产生“clean qualification”receipt。本轮root稀疏checkout仅用于审阅与提交。

```sh
git fetch origin b11459f46519e814ab9036c34a0cd7d3c3028e2b
git worktree add --detach ../hepta-next-b114 b11459f46519e814ab9036c34a0cd7d3c3028e2b
git -C ../hepta-next-b114 sparse-checkout disable
cd ../hepta-next-b114/codex-rs
just test -p codex-hepta-memory --lib --locked
just test -p codex-utils-cargo-bin --locked
just clippy -p codex-hepta-memory -p codex-utils-cargo-bin --locked -- -D clippy::correctness -D clippy::await_holding_lock -D clippy::await_holding_invalid_type -D clippy::expect_used -D clippy::unwrap_used
```

这些是下一轮复现命令，不虚构它们已在新b114 commit身份下再次运行。
需要Rust1.95、仓库just/nextest和真实系统依赖；完整native环境参数保留在
[research/native/final-validation-summary.json](research/native/final-validation-summary.json)。
本轮测试后的fmt没有改变源文件；不因格式或报告更新重复昂贵测试。

依赖owner比较入口：

```sh
git fetch origin c210d26350ac57e527b4ff59663e5c8d518ff95a
git diff --stat b11459f46519e814ab9036c34a0cd7d3c3028e2b c210d26350ac57e527b4ff59663e5c8d518ff95a
```

完整diff用于甄别，不是cherry-pick整个60-file候选的授权证明。后续任何依赖修改
仍执行真实 `just bazel-lock-update`、稳定性和原 `just bazel-lock-check`，再运行
原有 `cargo deny --locked --all-features check`；没有维护ignore例外。

GitHub实时读取入口为当前commit的check-runs和上述run/jobs。先检查head/base是否又
变化，再读取日志与artifact；不要把旧SHA的结果迁移到新SHA。全部source/review/
required gates未齐前不合并，研究门禁不因Draft标志变化自动解锁。

## 本轮停止点的性质

当前回合的本地修复、测试、远端推送与证据封存已完成。剩余跨平台作业仍未终态，
组织/专属工作机可见性缺失，独立新模型实验及大规模语义审查尚未完成。
已留下可执行下一步及原始输入摘要，不声明所有blocker闭合，也不声称会在本轮回复后
继续自动监控。checkpoint是接续入口，不是生产就绪证明。
