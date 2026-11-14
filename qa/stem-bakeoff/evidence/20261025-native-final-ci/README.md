# Native memory: independent final-source CI evidence

## 本次确认的结果

独立 GitHub Actions run [40149732280 / attempt 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40149732280)、job [121038539566](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40149732280/job/121038539566) 已完成并成功。精确源码为 [`33c741cb0abe5faac1d92abe5d0ac90bee4abb51`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/33c741cb0abe5faac1d92abe5d0ac90bee4abb51)，tree `02d11c75658c23b498ba2e7f8b6f082d76ec33b3`。源码身份同时与 GitHub commit API、实际 checkout 记录、两份执行源码 archive 和运行前后 inventory 对应。

本次 CI 全新下载固定 base，并完成原配方的 **96 次新训练更新 / 96 次训练前向**。随后真实执行 v1 的 3 次 decoder query / 1 次显式 feature forward，以及复用本次 CI checkpoint 的 v2 的 1 次 decoder query / 1 次 feature forward。共 5 个有 bootstrap、PID、父进程和退出回执的模型子进程；没有模型自动重试，也没有对结果调配方。原始材料及独立只读审计在下述档案中完整保留。

这是同一个已见开发案例的工程资格验证。独立 future task 数仍为 **0**，future accuracy 为 **null**，参数任务成功门槛仍为 **null**，八个研究 blocker 的 `full_closure` 全部为 **false**。

## 原始材料与审计

- GitHub artifact ID `12581984329`，名称 `native-memory-40149732280-1`，原 ZIP 大小 **61,902,851 B**，SHA-256 `b2553066177240e7c8af4304c7c9c69520a4bdd905d4f2830bbaf2527b03b8f2`。下载大小和摘要与 GitHub API 一致。
- ZIP 中 **5,704 个文件 / 100,734,907 B** 全部解包、逐文件重读与摘要核对；未裁剪 private home、日志、SQLite/WAL、checkpoint 或失败对照。
- `native-final-ci-supplement.tar.xz` 保存完整 final API JSON、原样保存的 connector decoded job log、下载/解包回执、60 项原始证据核对及方法、独立 v2 tick/frame 核对及方法。记录具体范围与摘要的 `manifest.json` 是重组依据。
- 一般证据核对 **60/60 通过**，未执行模型、训练、测试、formatter 或项目代码。其 immutable audit 明确将完整 tick/frame 重算留给另一份独立审计；该边界不会通过回填旧审计改变。
- 独立 v2 tick/frame 审计 **595/595 通过**：从原始问题重新生成 512 个 integer features，重算完整 tick、来源 / query / model / runtime / profile / namespace 绑定、Q24 ties-to-even 的第一次 sparse transition 和 canonical checkpoint，并逐字节重建 journal / witness。checkpoint 为 `c1cfa71f0fb4ce18007c46c169ec3884c7c999408d02b2c81683141b44efba6d`。方法和证明边界完整保留；未运行模型 / Rust / 测试，也未打开 SQLite。
- 两份执行源码 archive 各保存 **344 个选定源码文件**，其 inventory、Git archive comment 与该精确 head 对应；完整仓库身份由 commit/tree 绑定。产物不是整个 Git checkout 的副本。
- ZIP 不独立证明 GitHub runner 当时的活文件权限。临时下载 URL 未保存。原始 ZIP 未重新压缩；分片重组摘要已经核对。

上述 60 / 595 项是只读数据一致性与算术核对，不能当作新的任务样本或模型实验。

## 真实路径、输出和来源生命周期

v1 通过实际 Agentd 控制 socket、`NeuronModelPort` 和 Python worker 读取参数。控制端返回的文本、执行 JSON、请求摘要、源绑定和原始 worker stdout 对应；没有把来源中的答案字段计作模型输出。真实来源经历写入、纠正、撤回，revision 为 **1 → 2 → 3**。未知 key、错误角色、伪造来源 receipt、nonce replay、撤回 authority、纠正后的 cached result / 旧 adapter 和已撤回来源共 8 项拒绝均保留；native backend 只 dispatch 1 次。

v2 通过 `AgentdNativeMemoryCell::shadow_owner`、`NeuronRuntime::tick_shadow`、`NativeMemoryModelPort`、Python v2、journal/witness 和 delivery。其 context provider 明确命名为 `controlled-qualification-context-v1`，实际取 context 9 次、callback 1 次。v1 的 output width 4 显式改为受控 shadow profile 的 5；固定 decoder / 96-update 配方和已训练权重保持不变，shadow 新训练为 0。

| arm | 原始文本 | 生成 token 数 | 对该已见案例的 exact match |
| --- | --- | ---: | ---: |
| v1 fixed adapter | `order`，token IDs `[2559, 2]` | 2 | 1/1 |
| adapter disabled | ``The `asymmetric` keyword in C++ is used to indicate that a`` | 16 | 0/1 |
| shuffled adapter | `The repair for AssertionError: "asymmetric" does not match "un` | 16 | 0/1 |
| v2 fresh worker | `order`，token IDs `[2559, 2]` | 2 | 1/1 |

每个 arm 使用同一 74-token 问题。共 296 decoder prompt tokens、36 generated tokens；两次显式 feature forward 各输入 74 tokens。这里的 decoder query 是请求次数，生成内部的 Transformer forward 次数没有独立计数，不能将两者等同。

v2 第一次 read 后拒绝相同 nonce，拒绝类型为 `Source(Replay)`，callback 保持 1。先在新的 Recover owner 上成功 delivery，再实际 tombstone 来源，随后精确以 `Source(Invalid("current source revision or typed identity"))` 拒绝 delivery。writer authority 仍有效，不能把撤销 writer 导致的统一拒绝冒充来源撤回成功。该 source revision 为 1 → 2；journal / witness anchor 保持 sequence 1，分别保存 520 B / 224 B，拒绝后无额外 callback 或 anchor 变化。

Recover 在同一进程内使用真实共享 monotonic clock，实际创建两个 recovered owner。此材料未验证跨进程恢复、跨主机 clock epoch、独立运营 witness 的可信性或物理参数遗忘。受控 provider 保持 **abstain、deny-all、calibration=null**；v2 control socket、默认 daemon 安装、生产 NDU owner attachment 与生产资格均未通过本次验证。

## 测试与最终源码资格

| 检查 | 实际结果 |
| --- | --- |
| evidence driver 的失败 / timeout 回归 | 3 passed；1.033 s |
| native tick wire 回归 | 4 passed；0.007 s |
| 六 crate scoped tests | **651 run / 651 passed / 0 failed / 13 skipped**；测试阶段 93.119 s |
| v1 与 v2 example build | 两个独立步骤 success，binary SHA 保存于 invocation |
| scoped `just fix` 和最终 `just fmt` | success，完整 lint warnings 保留 |
| 最终 proposed patch / stat / worktree status | **0 B / 0 B / 0 B** |
| formatter stdout | 0 B，符合该 formatter 的输出设计 |

测试按项目默认入口执行，最终 fix/fmt 后没有重新测试。CI success 不单独替代源码清洁检查：上述三个原始文件确实为空，因此本次已测试与执行模型的精确源码未被最后的自动修复或格式化改变。`git` 清洁不表示 lint 没有 warnings。

## 完整成本范围

| 项目 | 原始测量 |
| --- | ---: |
| API job wall，含安装 / 编译 / 测试 / lint / 上传 | 1,660 s；API 时钟精度 1 s |
| fresh v1 driver | 77.965997166 s |
| shadow driver | 9.843380775 s |
| 两 driver 总 wall | 87.809377941 s |
| 训练 command / function / loop | 43.076700994 / 39.344697989 / 37.704592712 s |
| base acquisition | 5.689061708 s；6 文件 / 271,170,520 B |
| 训练 tokens | 7,296 input / 192 supervised |
| adapter | 460,800 参数；1,843,200 B tensor payload；1,858,776 B safetensors 文件 |
| 训练梯度 / optimizer tensors | 1,843,200 / 3,686,880 B |
| 每个推理 worker 的模型参数驻留 | 539,903,232 B；不包含 allocator |
| v1 / v2 推理 worker peak RSS | 1,143,246,848 / 1,143,152,640 B |
| 完整 v1 run 目录 | 5,628 文件 / 93,464,527 B |
| 完整 v2 run 目录 | 57 文件 / 6,089,062 B |
| 完整 artifact 解包文件 | 5,704 文件 / 100,734,907 B |

训练 / acquisition 时间包含在 v1 driver 中，command / function / loop 也相互嵌套，不重复累加。两个 driver 包含在 job wall 中。RSS 是两个推理 worker 的记录，不能代替整个 CI 或训练峰值。完整 command 的 child CPU / wall 原始回执也已保留。

base 目录和两个可执行 binary 位于 workflow 上传范围之外，ZIP 不保留它们的原文件。base 身份通过 acquisition、运行时 inspection、lineage 与实际 worker pins 交叉绑定；binary SHA 与 build / invocation 对应。没有使用先前本地权重来冒充 CI runner 的原文件。完整仓库、build cache、依赖占用、网络费用、所有进程峰值和持续负载未被全量计价。

产物中约 93 MB 的 v1 目录包含真实 App Server private home 的插件资源；未删除这类成本后只报 adapter 大小。以上测量也不是相同支持质量下的净压缩结论，ZIP 压缩率不是 memory system 的压缩收益。

## 八个 blocker 的本次 delta

| Blocker | 本次新增证据与未关闭范围 | full_closure |
| --- | --- | --- |
| 长期纠正与保留准确性 | 独立 CI 重现短来源纠正 / 撤回链；没有新的冻结长期任务流，先前三 seed 负结果没有被覆盖 | false |
| 真实来源与查询绑定 | 真实 v1 / v2 请求、来源、参数 / profile 与生命周期通过受控资格；外部原生来源授权和生产 NDU owner attachment 尚缺 | false |
| 未来任务优于强检索 | 仍是 1 个已见开发案例；future=0、accuracy=null，没有未见任务组或强检索比较 | false |
| 相同总预算下的分裂收益 | 本次没有共同预算的继续训练 / 扩容 / 检索 / 数据或随机分裂实验 | false |
| 学习连边与自治生长 | 本次没有学习连边的可比消融，也没有新的自治分裂 / 合并 / 回滚收益证据 | false |
| 多物理节点与数据本地性 | 本次为一个独立 CI runner；没有新的多主机边界、分区 / authority 故障恢复资格 | false |
| 净压缩和规模成本 | 补齐该运行的真实存储和局部运行成本；没有相同支持质量的完整系统计价与持续并发负载 | false |
| 原生生产集成 | 精确最终源码的 v1 原生控制路径与受控 v2 tick 在独立 CI 成功；默认 daemon、生产 NDU / context、校准与生产验收仍缺 | false |

前序研究结论继续参照 [冻结八 blocker 报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f92ddcacbe21267514f5040c1df6c380a96f0643/qa/stem-bakeoff/evidence/20261025-memory-program-status/README.md)。本次补充不修改该旧快照。原本地训练 head `8a47cdd…`、本地续跑 / shadow head `3a1431c…` 与本次 fresh CI head `33c741c…` 分别保留，训练成本不混称。

后来发现的 bootstrap WAL 首次权限缺口及其修复、abrupt-child 测试属于另一个源码阶段，不包含在本 run。此次 CI 的真实成功不能当作该后续修复已经验证。

## 档案重组

按 `manifest.json` 的 12 个分片顺序拼接，得到原始 `native-memory-40149732280-1.zip`；每片先验证 SHA-256，再验证完整 ZIP 的大小和摘要。原始 ZIP 大小 61,902,851 B，最大分片为 5 MiB。补充档案单独校验和解包，内容不代替原始 ZIP。

`summary.json` 是机器可读资格与成本 delta；`manifest.json` 列出档案成员、大小、摘要及审计身份。本次准备过程没有新的模型调用、训练或测试，没有修改 primary repository 或任何原始运行目录。
