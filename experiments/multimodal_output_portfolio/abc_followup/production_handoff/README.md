# Agentd 的完整 neuron journal 链恢复补丁

该补丁把本轮真实 13 段 journal 的恢复能力接到 Agentd process bootstrap 的产品层。它针对固定 commit `f8c9419df6ddeb36ff8b522a50219981fb8d9345`，原始 `plasticity_process_bootstrap.rs` 的 Git blob 必须是 `f44c8858a55886c7997562a02ba87b9a7d359bf2`。

**补丁尚未合入或部署。** 已编译和执行的是新增恢复 helper 与独立 probe，依赖本轮原固定 `9595221c21f1fe0775295a9c8756a1ba4d69ea49` journal API；没有把较新整个 Agentd crate 编译成功作为既成事实。根信任、正式签名、Dataset owner receipt、独立候选接受和部署存储仍各自需要真实来源。

## 具体变化

原 loader 只接收一个 `neuron.journal_path`，直接调用 `SparseJournal::open_anchored`。新增 `neuron_chain_recovery.rs` 通过原 `SparseJournal::open`、`start_successor` 和 `recover_successor` 按顺序恢复完整链，不改变 journal 格式、稀疏动力学或资格门。

原 descriptor 的 `neuron.journal_path` 与 `neuron.max_records` 保持兼容。新的 chain 表示使用 `neuron.segment_chain`，其每项必须同时包含绝对 `journal_path` 和该段 `max_records`；顺序是 root、successor 1、successor 2，直到承载独立最终 acknowledged anchor 的段。chain 形式必须省略旧的两个字段，旧形式必须省略 `segment_chain`。同时给出两种形式，即使 chain 为空，也会拒绝。

这里的“省略”也包括 Serde `Option` 的等价 JSON `null`。两个非空表示仍拒绝，空数组 `[]` 属于真实存在的 chain，不能与旧字段并用；详见新增的精确声明解析验证。

本轮对应顺序是 `neuron-0000.journal` 至 `neuron-0012.journal`，每段容量 128，最终独立 anchor sequence 为 1,600。容量是每段上限，不能把 1,600 当作单段容量来伪装恢复。

恢复前检查每个路径存在、非空、普通文件且非 symlink；拒绝重复规范路径和 Unix 上的 inode alias。补丁也把所有 chain 路径纳入原 loader 的全局检查，防止它们与 ledger、proposal registry 或独立 anchor store 重用同一文件。它不创建缺失段，不把空文件初始化成新历史。

中间段必须达到各自容量，后继段的原生 header 必须绑定前段真实最终 checkpoint。最后一段走 anchored recovery，链返回时再比对**最终 sequence 与 checkpoint digest 精确相等**；最终 anchor 后还有完整 suffix 的 chain 会拒绝，需独立 witness reconciliation。旧单文件分支继续使用原 `open_anchored` 的语义。

原 journal API 的恢复可能修复不完整尾帧；中间段恢复发生在最终全链 anchor 检查之前。因此不承诺所有失败输入的字节都绝不变化。验证只操作副本，并另行确认原 13 段文件未改变；正式恢复仍需原契约要求的私有 owner 存储和独立 witness。

## 实际验证

`CHAIN_RECOVERY_VALIDATION.json` 保留源代码、编译器、依赖 rlib、packet、实际结果和原 13 段文件的 SHA，以及每项验证结果。

- 用已经执行完成的 future stream 的 13 段副本恢复到 sequence 1,600；最终 anchor 和 33 维 eligibility 与实际保留 context 完全相同。
- 用实际 root 段验证旧单文件 descriptor，在 sequence 128 正常恢复。
- 19 项拒绝检查覆盖混合 descriptor、空 chain、重复或缺失路径、缺失中间段、错序、错容量、错 generation、scope、objective、最终 digest、缺少最终记录、ack 后 suffix、硬链接、symlink 及空段；共 21 项全部通过。
- 原 13 个文件逐一比对 SHA，未改变；没有新增 native tick、独立样本、角色签名、信任激活或模型更新。

本验证使用已冻结实验的状态作为恢复输入。它证明新增产品 helper 能通过原接口恢复真实链，不能替代完整较新 Agentd 的集成测试或正式部署接受。

另用 exact-base 补丁中的三个真实 serde declaration 与原 helper，实际通过 **15 项 JSON 解析／表示选择检查**，覆盖旧单文件、新 chain、null、冲突、缺字段、unknown 字段及错误类型。这项检查没有替换原 loader/runtime/error，也没有调用完整 loader。[DESCRIPTOR_SERDE_VALIDATION.json](DESCRIPTOR_SERDE_VALIDATION.json) 和 [实际集成可行性审计](INTEGRATION_FEASIBILITY.md) 分别给出可复核结果与当前完整 workspace/依赖缺口。

## 复现与目标源码应用

复现只需要原构建已产生的 release rlib，不修改原 workspace 或被冻结 native binaries。下面的路径对应本工作区；输出目录必须是新目录。

```bash
python3 -B experiments/multimodal_output_portfolio/abc_followup/production_handoff/run_probe.py \
  --rustc /workspace/scratch/2b3c256bef7d/task-tools/rust-1.95.0/bin/rustc \
  --dependencies /workspace/scratch/2b3c256bef7d/abc4-native-runs/target/release/deps \
  --packet /workspace/scratch/2b3c256bef7d/abc4-native-runs/future-packet-001/packet.json \
  --run /workspace/scratch/2b3c256bef7d/abc4-native-runs/future-native-001 \
  --output /workspace/scratch/2b3c256bef7d/abc4-native-runs/chain-recovery-next
```

runner 将自身及子进程固定到一个可用 CPU，使用独立新 binary 名称。它只在新输出目录创建 journal 副本。`prepare_bootstrap_patch.py` 校验原始 Git blob 后生成 `bootstrap-f8c9419.patch`，其中包含 loader 的最小改动和新增 helper。对 exact-base scratch tree 已实际执行 `git apply --check` 和 `git apply`；完整产品 checkout 应在应用前再次检查目标 blob。

若 helper 格式或内容改变，应重新生成 patch，使补丁内的新文件与可审阅源文件一致。正式落地还需在目标完整 Agentd workspace 验证编译、descriptor parsing 及 owner composition；这个隔离交付没有改动当前 core 或实验冻结文件。
