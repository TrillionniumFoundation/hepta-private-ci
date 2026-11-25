# 真实 A→B 与原生 adopted-update：第二次接入封装

这次工作补上了可执行的私有输入契约、固定二进制的原生声明适配器，以及一个新的原生冷恢复后撤销组合检查。**真实 A→独立 B→再次使用的闭环仍未成立。** 没有重新运行 E1–E6 或旧六组科学实验，没有重新训练历史候选，也没有把工程身份改名为真人。

## 核实到的入口和来源

`SOURCE_AUDIT.json` 保留本次读取的 Git 源版本和实际状态。下列五个 PR 在本次读取时都为 open、Draft、未合并，作者为 `ProfHepta`，没有 requested reviewer。PR 作者身份不等于学习数据的授权主体。

| PR | 固定 head | 当前提供的能力 |
| --- | --- | --- |
| Hepta #7076 | `86a86bdca886b950066b07e095412551aa777d7c` | 统计去重、候选冻结和传输绑定；不证明真人或诚实数据 |
| Hepta #7077 | `d4e1547824a40ccc9324f6ae016bd5c9c5fc0123` | 已声明依赖字节的 runtime identity v2 |
| Hepta #7078 | `fe249567feae227a362d354c1df3499a2995af40` | Hepta 与 Chain 身份互读；13 项既有工程检查 |
| Trillionnium-Chain #992 | `11d4bbe356331ef533d662ef4080a096ed20c8b1` | `prepare-bound` / `execute` / `verify` 的 request/delivery v3 |
| Trillionnium-Chain #993 | `2f0c7bf637cdae4b3a429b29118e2f16b09c42c9` | 失败尝试的原始成本、单一执行意图、禁止降级 |

真实历史 A 的可用位置是 `qualification/public-historical-a-qwen2-052-20261123/run`。本次重新读取了其来源元数据、冻结、父子模型清单和原有冷输出。保留结果为：父模型未通过 A、候选通过 A；父子均通过那个已冻结的旧能力条目。冻结为 `447ace5cc8bc031cc772e63ccb90380f16fc81404003bc04057ec4f8b7470ef6`。没有执行旧模型来重复这些结果。

来源为 OpenHands 公共反馈发布的第 52 行。发布方数据卡声明 MIT、公开选择、可用于改善编码助手；源版本与 Parquet 指纹保留于审计 JSON。本次没有重新下载原始轨迹，没有发布其原文或个人信息。它能支持保留的历史任务拟合结论；记录本身明确缺少稳定真人身份、该次动作的独立用户接受、前瞻 B 任务。许可证和 session 正面反馈不能补齐这些缺口。

原始数据卡：[OpenHands publisher card](https://huggingface.co/datasets/OpenHands/openhands-feedback/blob/main/README.md)。历史保留记录：[pinned source metadata](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fe249567feae227a362d354c1df3499a2995af40/qualification/public-historical-a-qwen2-052-20261123/run/source.json)。上述历史判定依据是保留记录，本次未独立重读原 Parquet 行。

## 原始授权的实际阻塞

在 `fe249567`，`paired_intake.install/admit/release/verify_live`、消费者和来源训练入口均要求 `engineering_fixture`。原生 `hepta-paired-consent` 只支持 `--help`、`--print-statement`。旧的 `ROOT_PID SQLITE_HOME ROUTE_JSON` 验证在读取 stdin、调用方路径或继承能力前就拒绝，错误为 `ORIGINAL_TURN_VERIFIER_REQUIRED`。

因此，旧 ELF、已确认的 SQLite 消息、两个账户、两把工程角色密钥、事后补填的 enrollment 字段均不能恢复真实授权。旧 README 中的 `--scope owner_intake` 示例描述历史接口，当前代码不会接受它。新封装没有修改这道拒绝，也没有引入关闭它的 flag 或回调。

`native_adapter.py` 用独立 SHA-256 固定 Linux ELF，通过持有的文件描述符运行它，只允许已存在的两个声明操作，并检查运行期间二进制是否改变。声明原文仅输出给调用它的私有站点。`authorize_owner()` 明确拒绝当前不支持的授权动作；JSON 中的布尔值不能成为授权证据。

```sh
python3 native_adapter.py /trusted/hepta-paired-consent EXPECTED_ELF_SHA256
python3 native_adapter.py /trusted/hepta-paired-consent EXPECTED_ELF_SHA256 \
  --statement /private/site/scope.json
```

这里的 binary 和 scope 均由原站点指定。没有捆绑或自动选择一个历史二进制；来源 commit 和二进制散列也不是同一个身份。

`native_interface_probe.py` 是这个适配器的独立接入检查：对精确 head 中的当前 CLI 编译结果，实际执行 help 和四种声明 scope，核对 study 与全部 scope 绑定均出现在原生渲染中。所有输入是明确的工程散列，没有真人授权。可在固定隔离 checkout 中构建，再传入实际 ELF 的散列：

```sh
# 在固定 head 的 codex-rs 下运行；保留原 Cargo.lock。
cargo build --locked -p codex-hepta-agentd --bin hepta-paired-consent

python3 native_interface_probe.py --repo /isolated/native-worktree \
  --native /isolated/cargo-target/debug/hepta-paired-consent \
  --native-sha256 EXPECTED_ELF_SHA256 --output /private/new-statement-receipt.json
```

这次当前 CLI 已用原 Cargo.lock 实际构建成功，适配器也退出 0；四类 scope 的全部绑定均通过。原生 ELF SHA-256 为 `82721b3fd39251249779754f46d5923def35556e3420e89701bbb9fb70ec7817`，原件收据为 `receipts/NATIVE_CLI_BUILD_RESULT.json`、`receipts/NATIVE_STATEMENT_INTERFACE.json` 和 `receipts/NATIVE_STATEMENT_TERMINAL.json`。真实原 turn 授权仍由该原生 help 和适配器共同报告为不可用；生成授权文字本身不是授权事件。

## 已准备好的私有输入契约

`PRIVATE_INPUT_CONTRACT.schema.json` 是结构契约，`intake_contract.py` 补充跨字段、时序、非零散列和文件检查。它输出准备状态，不发行授权或训练许可。

契约可按真实到达过程前进：先仅固定 A、keep 和候选（`frozen_waiting_b`，B 人级引用和 `pins.loop` 为 null），再加入 B 的登记/授权/新任务，之后逐次加入第一次、第二次使用。上游 loop identity 绑定 B 的已发布 paired request，因此只能在 B admission 时首次填写，之后不可改变。`--previous` 要求一次只前进一个阶段，已存在的其余 pins、原件和来源序列必须逐项不变；不能在看到 B 后更换候选或改写 keep。第一阶段不需要提前知道 B 的任务。完整十角色包只是最后阶段，不是前瞻工作的前提。

| 字段组 | 需要的实际原件 |
| --- | --- |
| `pins` | 先固定 study、parent、candidate、freeze、runtime_artifacts；B admission 时首次绑定 loop |
| `a_failure` / `a_success` | 同一任务的失败与后续成功记录，含原执行及语义验证依据 |
| `a_train_consent` / `a_enrollment` | 对精确训练材料的原始授权、原站点的人级登记 |
| `b_evaluate_consent` / `b_enrollment` | B 对冻结后任务的仅评估授权，以及同一登记机构的人级登记 |
| `b_future` / `keep` | 未曝光新任务和冻结旧能力条目；答案留在授权评估侧 |
| `b_use_first` / `b_use_again` | 同一不可变候选的两次不同后续任务，分别保留原交付及结果 |
| `sequence` | 原来源的成功、授权、freeze、B 首次任务到达、评估、第一次和第二次使用序列 |

每个对象以原字节 SHA-256 为文件名，附字节数；原字节散列不能混用成上游 canonical JSON 的 record/manifest digest。私有对象目录必须由执行 UID 所有且权限 0700，文件为私有普通文件，拒绝符号链接、硬链接、内容替换和观察到的写入变化。人级引用应由原登记机构跨账户稳定确定；结构验证不证明这些声明是真的。

这里的去重只拒绝完全相同的原字节。改写文本、重新编码或同义任务仍需上游已冻结 tokenizer、来源关系与评估协议检查；不同 SHA-256 不能证明两个任务或两个人彼此独立。

```sh
# 检查闭合字段、时序与重复，不读取私有对象内容。
python3 intake_contract.py /private/site/intake.json

# 新 B 到达后核对原先冻结的前缀；此命令仍不授予生产权限。
python3 intake_contract.py /private/site/b-arrived.json \
  --previous /private/site/frozen-before-b.json

# 只允许显式 engineering_fixture 的原件散列检查。
python3 intake_contract.py /private/site/engineering-intake.json \
  --engineering-objects /private/site/objects

# 新封装的输入、重放、权限与优化模式控制。
python3 -m unittest -v test_contract
```

`protected_original_owner` 会在打开私有对象目录前拒绝。两个不同 person hash 的包仍返回 `distinct_people_authenticated=false`。公开输出省略个人引用及逐任务散列，只保留包承诺、候选身份和计数；原件始终留在站点。

## 原生 adopted-update 的接入位置

固定源中已存在 `AgentdGenerationUpdateRuntimeV1`，采用入口为 `prepare_agentd_generation_update_v1`，冷恢复为 `recover_agentd_generation_update_v1`。`read_learning_updated_selection` 和 `read_learning_updated_next_use` 从原 CURRENT、实际 grant、witness、journal 和模型清单导出已发生的观察；调用方不能仅提供一个成功布尔值来替代它们。

真实产品学习通道为 `RootLearningHandoffV1` → `AgentdRootLearningInputsV1`：它需要同一个原始 Root 的密封 bootstrap、匹配进程/注册身份、原 socket 和预持有 pidfd，并重读原 CURRENT。公开 profile 字节不能创建这个 owner。这些通道的存在仍未补上前述原始 Core turn 授权验证。

固定源中的 `qualification/ordinary-daemon-learning-20261109/README.md` 还明确登记：普通运行时已有 opt-in 组合，但 main/CLI 尚不构造真实 host stage-owner、Circuit providers 和 Root lane，普通 descriptor 仍为 `Unpublished`。因此缺口同时涉及原始授权与真实产品装配，不能靠填写一个 private manifest 关闭。

恢复有两个必须区分的边界：

1. 普通冷恢复可以重读原来已发布、仍有效的采用，不再次消耗 grant 或重复推理。
2. `prepare_agentd_generation_forward_recovery_v1` 只接受仍为 `Prepared` 的未发布意图。已 `Published` 的更新只允许只读恢复。撤销之后不能恢复旧文件、回退撤销 frontier 或重新使用已消费 grant；重新授权与再次使用需要原发行者提供新的合法前进绑定。

现有 external-trained-artifact 演示是 Unix `cfg(test)`、单一操作者的研究角色、固定小任务。它的实际学习证明、工程 issuer 和产品原始授权范围必须分开。此封装不会重跑其训练预算，也不把它当作 A/B 的独立用户。

该研究 owner 创建时调用 `require_unstarted`，并将原始 genesis、owner、模型目录和证据目录同时锚定；后续还重验原训练与评估材料。不能只复制一个旧候选模型、填入新的 operation 后继承其采用资格。恢复必须保留原 owner 的完整材料。

实际可发现的 `h_rea_model_session_*` 接口提供同一认证 owner 和当前 policy 下的不可变模型快照。此次只读枚举没有返回任何 retained session。`h_hia_adopt` 管理 HIA Core/native 程序优化候选及 generation/epoch，要求服务器保留的验证、测量和执行权限；其存在不补齐神经权重训练或两位真人授权。此次没有调用 adopt 或 rollback。

HIA 的 manifest descriptor 可被发现，但本次读取其内容的原操作最终退出 127，原因是已配置的解释器不存在。已观察该同一操作的终态，没有重新提交、修改全局配置或把 descriptor 的可见性写成可执行状态；脱敏收据为 `receipts/NATIVE_INTERFACE_DISCOVERY.json`。

## 新的原生组合检查

`native_probe.rs` 接入固定 head 的原测试支持，但实际调用原 Agentd owner/runtime：完成一次工程采用及交付、丢弃 actor 后冷重开、重读原输出和重复原请求，再提升实时撤销 frontier，检查依赖当前授权的读回与第二次冷恢复被拒绝。journal 仍可能返回完全相同的旧请求收据；检查将其记录为只读历史回放，并要求没有第二次 control dispatch、没有第二次 nonce 消费、原 journal/witness/current 字节不被恢复操作改写。

其控制输出、训练/evaluation 证据和授权角色都是工程 fixture。即使成功，它也会记录 `actual_model_inference=false`、`independent_human_participants=0`、`new_task_repeated_use_observed=false`、`closure_complete=false`。**原请求的重复读取不算第二项任务使用。** 该检查不能证明物理模型执行、B 收益、恢复后新授权或生产部署。

`run_native_probe.py` 只接受新隔离 worktree、精确 `fe249567` 和已审计支持文件 Git blob。它拒绝无关本地改动，在该隔离 checkout 注入一个 test-only 子模块，调用仓库的 `just test`，保存原 stdout/stderr 与收据；零测试过滤即使 exit 0 也不会被记成通过。最后按仓库规则运行 `just fmt`，格式化后不重复测试。

```sh
python3 run_native_probe.py --repo /isolated/native-worktree \
  --output /private/new-probe-receipt \
  --tool-bin /isolated/tools/bin --target-dir /isolated/cargo-target
```

原生第四次尝试实际通过：`just test --locked -p codex-hepta-agentd --lib -E test(cold_revocation_blocks_existing_checkpoint_adoption_v2) --no-capture` 选择 1 项、通过 1 项，867 项其他测试被过滤。原始收据为 `receipts/NATIVE_v4_RESULT.json`，`just fmt` 也退出 0。实际观察到 1 次 control dispatch、1 次最终使用 nonce 消费；冷重开前后输出相同，实时撤销后读回、旧请求和再次冷恢复均拒绝。这个结果仍为工程角色和工程模型控制，不包含真实模型推理或真人。

前置尝试均保留：第一次缺少 `cargo-nextest`；第二次稀疏检出未物化原模块目录；第三次还缺少原 proposal worker，并暴露新测试中的宏导入歧义。这三次均未执行测试。只补齐了同一 head 中的资源，明确导入原 `pretty_assertions::assert_eq`；仓库 Cargo.lock 与依赖 revision 未变。第四次启动 RPC 超时后，经原 request/job 取回成功终态，没有换 key 重启。各次执行与格式化收据、精确历史源码包均位于 `receipts/`。

当前 `native_probe.rs` 为仓库格式化后的原字节；收据同时保留实际执行前源 SHA 和格式化后源 SHA。格式化后没有重复该测试。运行器安装在任务独占目录，不修改共享 checkout。

## SmallHCSN v2 的独立只读审计

`audit_hcsn_artifacts.py` 核对正式 `FORMAL_PROTOCOL_v2.json`、Git 封存的 168 项候选和测试开放顺序。五份科学源码、25 份物理源文件、provenance，以及每项候选的训练 RESULT、HISTORY、candidate.pt 和预测文件，共 672 份条目原件均符合已封存散列。测试数据文件也符合评估收据。旧 `FORMAL_PROTOCOL.json` 是未执行的 v1 保留记录；本次正式执行绑定 v2，审计没有覆盖旧版。

`audit_hcsn_archives.py` 另外流式读回全部 190 个 tar.xz 和 981 个成员，逐一核对索引散列及原留存文件；合计 19,180,320 字节，最大单包 228,124 字节，低于仓库的 512,000 字节限制。没有将压缩包展开到文件系统，也没有重新加载模型、生成测试数据或训练。这些字节和顺序检查不增加真实用户迁移或生产采用资格。

## 接通真实闭环还需交付的具体材料

原站点需要提供能绑定原 Core turn、当前队列/checkpoint、精确 scope 和撤销状态的原生 verifier，以及登记机构的 A/B 两位不同真人原件。已有研究候选还需独立 B 的真实新任务、keep 对照、两次不同任务的原交付与接受证据。发生撤销后，还需原 issuer 的新授权绑定和前进状态；本封装不会代签或重写旧身份。

这些输入到达后，先固定输入、候选和 runtime，再经原 owner 读回授权，才开放私有对象给隔离评估；原 native 更新负责采用、撤销和恢复，Chain 继续消费相同的已绑定身份和成本。当前仍分别保留 missing-original-turn、missing-independent-B、missing-authorized-recovery/reuse，而不是合并为一个工程 PASS。
