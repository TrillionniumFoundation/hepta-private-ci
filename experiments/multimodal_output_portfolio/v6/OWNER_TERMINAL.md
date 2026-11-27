# 真实生成记录经 terminal learning owner 执行

这个切片把已完成 v6 实验中的一个固定输入、模型和预算下的七策略组，
送入现有的 authenticated learning ledger、dataset freeze 和 terminal-cell fitter，
再通过现有 artifact store 保存、加载并执行预测。它验证 owner 调用链和证据绑定。
它不重新训练 Python 神经网络，不增加科学样本，也不签发生产认证。

## 输入和信任范围

`terminal_fixture.py` 只接受 `status.state == completed` 的运行目录。
默认组在解析结果之前由 protocol 的首个 seed、training、future case、budget 选定。
导出端核验完成状态、summary 和 protocol 的 canonical SHA 绑定、完整记录数，
并要求所选组恰有七种不同的注册策略。

同一组必须共享原始公开观察、模型、预算、源图像、损坏类型和评分模型身份。
这里的策略是**从编码之前开始的完整宏动作**；allocation-only 的不同初始 plan
是其宏动作的一部分，因此不能把七条记录称为相同的初始 latent。

导出内容包含原始 row receipt、原始日志行的哈希、未修复的 UTF-8 caption 和
PNG 字节，以及对应模型、forecast、audit observer 和源文件的 byte pins。
源目录在导出前后都必须保持原样；fixture 创建在另一个目录，禁止覆盖既有文件。
fixture 上限为 1 MiB，Rust 导入端再次核验同一身份链和原始文件。

Rust fixture 明确使用本地研究 root 和确定性的测试签名密钥。
generator、observer、evaluator 的角色、controller 和 credential 身份不同，
但它们位于同一台主机，不代表组织独立性或外部生产授权。
签名时间描述当前对旧记录的核验和导入，不冒充旧实验的执行时间。
所有产物保留 `deny_all` authority。

## 原生候选集合与真实支持集合

原始七条记录由实验循环分别强制执行，selected propensity 都是 `1`。
这里不存在随机抽取七种策略的 `1/7` behavior policy，也不构成 OPE 数据集。

原生 `LedgerWriter` 要求完整候选集合包含保留动作 `abstain`。
因此 import macro grammar 包含原七种策略以及该保留动作，共八个候选；
只有原七种策略有实际执行结果。没有伪造第八个 outcome，也没有给 abstain 补零。
原始实验没有执行或评估第八种生成策略。

`TerminalSupportedCellProfileV1` 显式区分完整 `candidate_ids` 和
`cells.action_ids` 中需要拟合的动作。新入口
`freeze_supported_terminal_cells_from_owner_v1` 要求：

- 拟合动作是完整候选集合中非空、无重复的子集。
- 每条 owner decision 的完整候选集合都与注册语法相同。
- 每条已观察 decision 的 selected action 都必须属于拟合集合；不能丢掉已观察的负结果。
- 每个拟合 cell 都有达到预定最低数量的真实 owner outcome。
- 新 profile digest 同时绑定完整候选集合、拟合动作、状态、单位和最低支持数量。

原来的 `freeze_terminal_cell_from_owner_v1` 保留精确全覆盖约束和原 digest 路径。
新入口仍调用既有 `fit_terminal_cell_from_owner_v1`，由 owner 当前记录派生 target。
加载后的模型对未拟合的 abstain 返回 unsupported，不产生推测值。

## 实际调用链

1. 核验外部保留的 fixture SHA、原始文件及当前 import executable 字节。
2. 经真实 `activate_learning_trust` 激活明确的本地 fixture trust。
3. `LedgerWriter::append_decision` / `append_outcome` 依次接收七对签名记录，共 14 条。
4. evaluator 对实际 owner snapshot 签名，再由 `freeze_dataset` 冻结精确数据集。
5. 受检子集入口冻结七个受支持 cell，既有 fitter 从 authenticated owner records 计算终值。
6. 使用既有 `ArtifactRegistry`、create-only payload/registry 文件和独立保留的 pin 保存产物。
7. `load_pinned_candidate` 与 `LoadedTabularOperatorV1` 重新加载，并逐一执行七个预测。
8. 从 durable ledger/witness 与保留的 acknowledged anchor 恢复 owner，重新拟合应完全相同。
9. 再核验所有原始源文件和 import executable 未变，写出工程 evidence。

Q32 转换使用原始 JSON binary64 值乘以 `2^32` 后 ties-even 舍入。
Python `round` 与 Rust `round_ties_even` 使用相同语义，覆盖半格值及相邻浮点数回归。

## 复现

可以从任一已完成、包含七种策略的真实 v6 运行导出，CI 也可以使用自己的已完成 smoke。
从仓库根目录执行：

```bash
python3 -m experiments.multimodal_output_portfolio.v6.terminal_fixture \
  /absolute/path/to/completed-run /absolute/path/to/terminal-fixture.json
```

保留命令返回的 SHA256，作为随后执行时独立提供的 fixture pin。
固定首轮历史记录时可追加 `--fixed-full-001`，它要求四个已登记的原始元数据文件哈希。
不要从未完成目录或正式运行尚在写入的行日志导出。

在 `codex-rs` 目录运行真实工程切片：

```bash
HEPTA_TERMINAL_OWNER_FIXTURE=/absolute/path/to/terminal-fixture.json \
HEPTA_TERMINAL_OWNER_FIXTURE_SHA256=<retained-export-sha256> \
CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 \
CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 \
just test -p codex-hepta-agentd --test generation_terminal_owner \
  --run-ignored all --retries 0 --success-output immediate
```

该真实 test 默认 ignored，显式执行需要完整的已完成源目录及保留的 SHA。
普通边界测试不依赖 MNIST、模型下载或历史运行：

```bash
python3 -m unittest experiments.multimodal_output_portfolio.v6.terminal_fixture_tests
just test -p codex-hepta-agentd --test terminal_cell_subset
```

Python 命令从仓库根执行，Rust 命令从 `codex-rs` 执行。
不需要新增依赖。测试把 ledger、witness、payload、registry 和 `evidence.json`
保存在 fixture 旁的独立目录，并打印 evidence 路径及 SHA；应保留完整目录和日志。

## 本次工程证据

固定组为 full-001 的 `seed=17, training=supervised, case=future-0000, budget=64`。
旧 holdout 数据此次仅作为后验工程 fixture，原科学记录没有改变。

- fixture SHA256：`61397d33cc8e06893ba6a7cbe0f72449f8ac1602a342369bd50d1bc88f429147`。
- 实际 owner evidence SHA256：`e35f4ecb9ab815b4fcc8efb71c93ebbf4cc052600c841695058896948ba1ecd6`。
- 七个 loaded predictions 与七个原始 Q32 target 一致；恢复后 owner fit 完全相同。
- raw 输出篡改、错误单位、遗漏已观察动作、错误签名角色和重用 record ID 的冲突均被拒绝。
- 初次导入发现的 fixture 大小上限与缺少保留 abstain 两次失败日志也保留。

这是一状态、每动作一个样本的终值 cell 模型。精确重现这些样本不能证明
对新输入泛化、在线策略改进、全局 NDU 最优性、神经网络梯度被原生 plasticity 接管，
或生产 daemon 已获得写入许可。Python 神经训练、真实输出 plan-gate 训练、
本工程 terminal-cell fit 是三个不同且分别记录的过程。
