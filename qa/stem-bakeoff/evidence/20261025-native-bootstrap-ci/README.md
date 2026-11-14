# Native memory: bootstrap-repair independent CI evidence

## 结果与精确范围

独立 [run 40152367005 / attempt 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40152367005)、[job 121046374239](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40152367005/job/121046374239) 已完成并 success，所有命名步骤 success。实际源码为 [`a47190bb84714cb1262fcd85ebb723081fdb0581`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a47190bb84714cb1262fcd85ebb723081fdb0581)，tree `b4150dc0e76e216792a36b8478580dfed3270af2`。GitHub commit API、checkout、两份执行 archive 和运行前后 source inventory 相互绑定；每份 archive 保存 345 个选定源码文件。

本次独立验证覆盖首次初始化权限修复、两类真实 abrupt-child 恢复、原配方的全新 96-update 训练、实际 v1 原生控制路径和受控 v2 tick。一般证据 **60/60**、崩溃恢复 **90/90**、完整 v2 tick/frame **598/598** 核对通过，三份原始审计与方法均保留。审计数量是数据与算术比较数量，不是新增任务样本。

六 crate 的真实结果是 **653 run / 653 passed / 0 failed / 13 skipped**。653 在完成前已经按旧同命令 651 加两个新增测试规定，实际结果与预期相符。最终 fix/fmt 的实际 patch、stat、worktree status 均为 **0 B**。新阶段与[旧 33c CI 证据](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/25b553f3feec0e99ef2f049822e9f1842b41f97c/qa/stem-bakeoff/evidence/20261025-native-final-ci/README.md) 分开保存，旧成功没有转作此次修复的证据。

这里关闭的是已有本地失败/修复对照所针对的受控工程缺口，并补齐修复后精确最终源码的独立 CI。八个研究 blocker 的 `full_closure` 仍全部为 **false**；future task 数为 **0**，future accuracy 与 parameter success gate 为 **null**，生产资格为 **false**。

## 首次权限缺口的实际恢复证据

之前的 [本地 red/green 与 scoped qualification 档案](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7bd4641572b73e75ac004d0fb8da3f886d399d3d/qa/stem-bakeoff/evidence/20261025-native-bootstrap-recovery/README.md) 保留了旧 initializer 的真实失败、同一测试下的最小修复和最终源码桥接。本 CI 重新从最终源码执行，上传了 `bootstrap-crash-tests/` 全部 **41 文件 / 3,477,006 B**，未只保留 PASS 行。

| case | parent PID | writer PID / exit | recovery PID / exit | 原 WAL 布局 | 实际 attempts |
| --- | ---: | --- | --- | --- | ---: |
| initial-generation-pnxtNz | 33006 | 33008 / **73** | 33051 / **0** | 1,030,032 B，250 frame slots | 1 |
| recovered-generation-rxQLr8 | 33078 | 33080 / **73** | 33119 / **0** | 8,272 B，2 frame slots | 1 |

四个 child 都从自身 `/proc/self/status` 记录了 **0022** umask；这不是审计时假定的值。每个 writer 在保留 live store/pool 的情况下调用 `process::exit(73)`，没有运行 Rust Drop。新的 recovery child 使用实际保留的完整 cut，恢复后在不同 generation DB 上执行新写入，再在该 recovery child 内 close/reopen 并验证写入后的完整 cut 持久化。

每个 case 的 `source-before.json` 与 `source-after.json` 完全相同：包含 bytes、SHA、0600 mode、device、inode、links、mtime 和 ctime。原 ZIP 内 DB/WAL/SHM 的实际字节逐项与 runner 原始记录一致；新 generation DB 原文件也保留。handoff 的完整 profile/owner/schema/state cut 与恢复初始观察相同；新增写入改变 state cut，profile/owner/schema 保持一致。两条 named PASS 均在 scoped 原始日志中，无 retry / flaky 行，原始目录也只有各一次 attempt。

独立 crash reader 直接读取已验证 ZIP，不打开 SQLite、不重新执行测试。它使用 runner 捕获的 JSON 权限与元数据，绝不把 ZIP 解包后的本机权限或 inode 当作 runner 原值。完整 SQL 表状态没有由审计器重新查询；完整 cut 的语义由固定源码上的实际恢复、新写入和 close/reopen 执行支撑。

此证明针对 **committed WAL 存在时的进程退出恢复**。WAL 有 frames 不等于证明数据只在 WAL 中或 WAL replay 必不可少；`process::exit` 不等于物理断电。后续 reopen 在 recovery child 内完成，不是第三个验证进程。authority 仍为受控测试 authority，不扩展为生产授权资格。

## 全新训练、原生读取与对照

本次实际新训练 **96 updates / 96 forwards**，rank 8、seed 24031、learning rate 0.01、`completion_ce`、frozen-base 初始化及固定 schedule 未改变。没有复用旧 33c CI 或本地的训练成本。v2 复用的是**本次 CI** checkpoint，新增训练为 0。

| arm | 原始文本 | 生成 tokens | 对唯一已见案例的 exact match |
| --- | --- | ---: | ---: |
| v1 fixed adapter | `order`，IDs `[2559, 2]` | 2 | 1/1 |
| adapter disabled | ``The `asymmetric` keyword in C++ is used to indicate that a`` | 16 | 0/1 |
| shuffled adapter | `The repair for AssertionError: "asymmetric" does not match "un` | 16 | 0/1 |
| v2 fresh worker | `order`，IDs `[2559, 2]` | 2 | 1/1 |

实际为 5 个模型子进程：training 1、v1 worker 1、base 1、shuffled 1、v2 worker 1。四个 decoder query 共 296 prompt tokens / 36 generated tokens，另有两次显式 feature forward。query 数不能当作生成内部 Transformer forward 总数，后者未单独计数。崩溃测试的四个 Rust child 也不计作模型子进程。

v1 通过实际 Agentd 控制 socket → `NeuronModelPort` → Python worker；返回文本与实际 worker 原始执行 JSON 对应，不把 source answer 字段计作模型输出。来源写入、纠正、撤回为 revision **1 → 2 → 3**，8 项原有拒绝条件成立，native backend dispatch 仅 1 次。

v2 真实路径为 `AgentdNativeMemoryCell::shadow_owner` → `NeuronRuntime::tick_shadow` → `NativeMemoryModelPort` → Python v2 → journal/witness → delivery。provider 明确为 `controlled-qualification-context-v1`，实际取 context 9 次，callback / decoder query / feature forward 各 1。v1 width 4 到受控 shadow width 5 的观察头变化与 profile 摘要被显式记录，没有额外训练或 decoder 配方调整。

完整 v2 审计从问题重建 512 个 integer features，重算全部 source/query/tick/model/runtime/profile/namespace 绑定、Q24 ties-to-even 的第一次 sparse transition、canonical checkpoint 和整个 journal signal/frame/witness。598 项包括 345 source pins、57 个原 ZIP 成员和 196 项其他比较；比旧审计增加一个源码文件与两个 raw text/token 比较，适配记录与首次执行回执保留。

- 独立 checkpoint：`46ef708f9df4713caf0b5e650544e1127c9d9c9580eb2174be9270e5a8147bc9`。
- 完整 520 B journal SHA：`fec215059de3d2132a85419b67ec358d171e99f7291901fad5f37d023fbd547f`；其 384 B frame 逐字节重建。
- 完整 224 B witness SHA：`79c5684d5393cf659e78efd6ebd3d430827b0b3b130c663b77da8f4970818a18`。

相同 nonce 精确以 `Source(Replay)` 拒绝。新的 Recover owner 在真实 tombstone 前成功 delivery；tombstone 后在 writer authority 仍有效时，以 `Source(Invalid("current source revision or typed identity"))` 拒绝。callback 始终为 1，journal/witness anchor 不变。受控 v2 的两个 Recover owner 同属一进程，不能与另两项 SQLite fresh-process crash tests 混称为 v2 跨进程恢复资格。

v2 保持 **abstain / DENY_ALL / calibration=null**，没有生产 Objective/NDU authority、默认 daemon 安装、v2 control socket、独立 witness 运营信任、跨主机恢复或物理参数遗忘资格。每个回答仍来自同一个已见开发案例，没有新的自然领域未来任务修复执行。

## 测试、源码清洁与完整成本

| 项目 | 实际记录 |
| --- | ---: |
| evidence driver 回归 / tick wire 回归 | 3 passed / 4 passed；1.024 s / 0.007 s |
| 六 crate selected tests | 653/653 passed，13 skipped；测试阶段 91.982 s |
| 完整 job wall | **1,737 s**；01:53:44Z → 02:22:41Z，API 精度 1 s |
| fresh v1 / shadow driver | 64.370485260 / 10.706649680 s |
| 两 driver 合计 | **75.077134940 s** |
| training command / function / loop | 34.652411628 / 30.715446165 / 28.788669306 s |
| base acquisition | 4.742766199 s；6 文件 / 271,170,520 B |
| training tokens | 7,296 input / 192 supervised |
| adapter | 460,800 参数；1,843,200 B payload；1,858,776 B safetensors |
| 梯度 / optimizer tensors | 1,843,200 / 3,686,880 B |
| 每个推理 worker 参数驻留 | 539,903,232 B，不含 allocator |
| v1 / v2 推理 worker peak RSS | 1,142,935,552 / 1,143,173,120 B |
| 完整 v1 / v2 run 文件 | 5,628 / 57 个；93,468,377 / 6,092,954 B |
| crash case 文件 | 41 个 / 3,477,006 B |
| 完整 artifact 文件 | 5,745 个 / 104,219,945 B |

训练、下载与 function/loop 时间相互嵌套，均不重复加到 driver 或 job wall；完整 child CPU / wall 回执保留。推理 worker RSS 不是整个 CI 或训练的峰值。这里没有把不同 runner 的速度差异当作设计收益。

最后 scoped fix/fmt success，lint warnings 原样保留；formatter stdout、proposed patch、stat、worktree status 都实际为 0 B。没有在最终工具之后重跑测试。由空 patch/stat/status 确认最终工具未改变已测试、已执行模型的源码；“源码清洁”不表示没有 warnings。

base、Python executable 和两个 native binary 的原文件不在 workflow 上传范围内；身份由 acquisition / inspection / lineage / worker pins、build 与 invocation 摘要对应，不能宣称已对缺失原文件重新独立 hash。完整源码身份由 commit/tree 绑定，执行 archive 保存的是选定文件。约 93 MB 的 v1 private home 插件资源被完整计入，未删掉后只报 adapter。仓库 / build cache / 全部依赖 / 持续并发 / 网络费用仍未全量计价；没有相同支持质量下的净压缩证明。

## 八个研究 blocker

| Blocker | 本次 delta 与仍缺证据 | full_closure |
| --- | --- | --- |
| 长期纠正与保留准确性 | 增加独立短生命周期与 crash recovery 资格；没有新的冻结长期保留流，先前三 seed 负结果未被覆盖 | false |
| 真实来源与查询绑定 | 重现 v1/v2 源、问题、参数及拒绝绑定，修复初代 sidecar 权限；外部来源原生授权和生产 NDU owner attachment 尚缺 | false |
| 未来任务优于强检索 | 同一已见案例，future=0、accuracy=null，没有未见任务组与强检索比较 | false |
| 相同总预算下的分裂收益 | 没有新增共同预算的继续训练 / 扩容 / 检索 / 数据或随机分裂实验 | false |
| 学习连边与自治生长 | 没有新增连边消融、自治分裂 / 合并 / 回滚收益证据 | false |
| 多物理节点与数据本地性 | 增加单 CI runner 内两个真实恢复子进程；没有跨主机权限、分区与 authority 故障资格 | false |
| 净压缩和规模成本 | 补充此轮完整 artifact 与局部 runtime 成本；没有相同质量的完整系统计价和持续负载 | false |
| 原生生产集成 | 修复后精确 head 的 scoped tests、v1 原生控制路径、受控 v2 与 crash case 独立通过；默认 daemon、生产 NDU/context、校准仍缺 | false |

前序研究结论参照[冻结总报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f92ddcacbe21267514f5040c1df6c380a96f0643/qa/stem-bakeoff/evidence/20261025-memory-program-status/README.md)。本包不修改旧快照、旧方法、旧原始 ZIP、训练配方或评测门槛。

## 原始档案与重组

GitHub artifact **12584240824** 的原 ZIP 为 **62,069,755 B**，SHA-256 **`d3ad050d06cafe321e9bf4bbd024140973a252d2cc41355e7dc1e1c5e8acf144`**，下载字节数和摘要与 API 一致。12 个分片每片不超过 5 MiB，没有重新压缩，分片与流式重组摘要均核对。`manifest.json` 给出拼接顺序与全部摘要；原 ZIP 内所有 5,745 文件均保留并逐字节检查。

`native-bootstrap-ci-supplement.tar.xz` 包含完整 API、完整 decoded job log、6 次定期监控快照、下载 / 解包 / 分片回执、三个实际审计的结果 / 方法 / 执行凭证与原始 preparation 记录。历史 pending 记录保留其当时状态，actual 结果另存，没有回填改写。`summary.json` 给出机器可读资格、来源、计数和成本。

本轮审计新增模型调用、训练、测试、Rust 执行、SQLite 打开及 GitHub 写入均为 0；只有证据读取和本地新档案写入。源 ZIP、实际运行目录及 primary repository 不变。原 ZIP 不独立证明 runner 活文件权限；crash 权限结论只依赖具体 case 中的原始 captured metadata。
