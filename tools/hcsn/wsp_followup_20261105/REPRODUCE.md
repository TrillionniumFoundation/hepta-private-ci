# 独立验收与重执行

本文件把“核验已发布证据”与“重新运行模型/原生程序”分开。已发布的协议、失败记录、候选、场景和结果均保持原样；重执行使用新目录。计时可以不同，不能以计时变化替换科学结果或输入身份检查。

## 1. 核验已发布证据

从研究仓库的本 PR 精确提交开始，保持工作树干净。研究父提交为
`2d0120e208ed81515837a7530c9f6943af03e87f`，其中旧研究子树身份是
`3c44695c6b004328716e85b192e308d4a9c239c0`。

```sh
python3 -B tools/hcsn/wsp_followup_20261105/verify_package.py
python3 -B tools/hcsn/wsp_followup_20261105/verify_native_records.py
python3 -B tools/hcsn/wsp_followup_20261105/ndu_policy/verify_records.py \
  tools/hcsn/wsp_followup_20261105/ndu_policy/execution_r1/run \
  tools/hcsn/wsp_followup_20261105/ndu_policy/PROTOCOL_FROZEN.json \
  --history tools/hcsn/wsp_20261104
```

前两条是标准库的库存/记录检查；第三条另需 NumPy，核验数值证据但不重新评分轨迹。没有任何一条启动新的训练或 Runtime。

新 TRAIN 不可行证书另有只读入口：

```sh
( cd tools/hcsn/wsp_followup_20261105/train_margin_certificate && \
  bash RECORDS_ONLY_COMMAND.txt )
```

它核对 81 文件库存、原 C 模型身份，并重新执行五个 Fraction 证书的精确代数；不运行 hidden、Bellman 或策略，也不产生新候选。只读入口需要标准库与 NumPy；完整诊断另使用该组件记录的 NumPy/SciPy 环境。根审阅者已实际执行通过，收据为 [ROOT_TRAIN_CERTIFICATE_VERIFICATION.json](ROOT_TRAIN_CERTIFICATE_VERIFICATION.json)。全量 TRAIN 重建及 21,458 见证状态重执行的命令与成本另见 [train_margin_certificate/README.md](train_margin_certificate/README.md)；不要把只读代数核验当成全量重建。

末次 pocket4 快照也有记录核验入口，不接触主机：

```sh
python3 -B tools/hcsn/wsp_followup_20261105/pocket4/session_end_snapshot/verify_records.py
```

在 HeptaRuntime 精确提交
`990f85e46bedb8f49c0e6d0029ea6f9afbf6eac7` 的完整 checkout 中：

```sh
python3 -B experiments/weight/native_bellman_20261105/verify_records.py --repo .
python3 -B experiments/weight/native_guard_journal_20261105/verify_records.py --repo .
```

这两条核验原生记录、14 个相关源码及 Cargo.lock，不执行 MCP 或新科学实验。完整官方 CI 是另一项资格，由固定 head 的工作流记录证明。

## 2. 重执行完整科学比较

为重执行另建工作树或独立工作副本，避免把新增输出混入原始归档的严格库存检查。不要覆盖任何已发布目录。依照
[ndu_policy/README.md](ndu_policy/README.md) 的完整命令：

1. 从固定公开归档恢复五个原模型与原 TRAIN 数据，核对所有成员和输入哈希。
2. 运行 `run_bounded.py`，保持全部五个 fit、固定种子、20 个求解结果、所有候选、160 个验证和 320 个 TEST 场景。
3. 运行 `verify_records.py`；再用 [compare_replay.py](independent_replay/compare_replay.py) 与发布记录比较。

已执行的独立重放及其 77 项精确比较在
[independent_replay](independent_replay/README.md)。比较器只排除协议明确列出的资源计时字段，不忽略失败模型、gate 或策略收益差异。

Python 环境、固定 NumPy/SciPy 版本和 POSIX 资源要求在组件 README 与运行收据中说明。完整重执行重复既有实现和已暴露场景，不能当作第二次独立统计确认。

## 3. 重执行原生 corpus

原生资格和 corpus 执行使用 **Linux**，Python 必须提供 `resource.prlimit`；科学比较的 POSIX 支持范围不能直接推及这套原生驱动。先在独立 Runtime checkout 中通过 rustup 准备仓库锁定的 Rust 工具链，包含 rustfmt / Clippy；脚本使用 `~/.cargo/bin/cargo` 和 `~/.cargo/bin/rustc`。资格脚本以 `--offline --locked` 编译，因此依赖必须已缓存；一次新的依赖获取及其成本应另行记录。例如先完成 `cargo fetch --locked`，随后运行：

```sh
python3 -B experiments/weight/native_bellman_20261105/run_local_qualification.py \
  --root . \
  --target ../wsp_runtime_target_reproduction \
  --output ../wsp_runtime_qualification_reproduction \
  --attempt 1

python3 -B experiments/weight/native_bellman_20261105/prepare_execution_protocol.py \
  --qualification ../wsp_runtime_qualification_reproduction/qualification.json \
  --requests experiments/weight/native_bellman_20261105/fixtures/requests \
  --output ../wsp_runtime_freeze_reproduction/EXECUTION_PROTOCOL.json
```

输出目录必须不存在。资格脚本记录实际 checkout、构建二进制和源身份；新的二进制哈希不必与本次机器的哈希相同，但必须先冻结并由自己的完整验收链绑定。六个局部命令全部成功后才可进入 corpus 执行。它们是 focused 软件门，不代替完整仓库 CI。

在研究工作副本中，按
[native_bellman_replay/README.md](native_bellman_replay/README.md) 创建新的 sibling 脚本目录。先在该新目录运行 `check_verifier.py` 生成新的 `VERIFIER_TOY_CHECK.json`，再用新的 native execution protocol、已发布且完整保存的 `export_r1/run` 和固定验收协议冻结新的 `VERIFIER_FREEZE.json`。Freeze 必须位于这个新脚本目录内，验证器按自己的文件位置读取它。随后才启动 Runtime 的 `supervise_native_corpus.py`。

本节选择原图重放路线，因此组件 README 中 `freeze_verifier.py` 和 `run_stage.py replay` 的两处 `--exported` 均应填写 `../native_bellman_replay/export_r1/run`，不要照抄新导图示例的 `independent_export/run`。`--native` 应指向 supervisor 生成的 `<new-attempt>/corpus`，不是 attempt 根目录。新 corpus 再交给 `run_stage.py replay` 做全量 Q、mask、action 和 320 条 J 期望轨迹比较。

Corpus 完成后，在 Runtime checkout 另外执行协议要求的完整源码/二进制复核；driver 内部的副本身份检查不替代这一步：

```sh
python3 -B experiments/weight/native_bellman_20261105/verify_source_health.py \
  --root . \
  --binary ../wsp_runtime_target_reproduction/debug/hepta-runtime \
  --qualification ../wsp_runtime_qualification_reproduction/qualification.json \
  --phase bellman_corpus \
  --output ../wsp_runtime_qualification_reproduction/post-bellman-corpus-source-health.json
```

完整保留这条收据及前述 corpus、比较和轨迹记录。输出采用 create-only；失败时保留原目录，不能覆盖失败后重试。接口参数和其余输出布局分别由两个组件 README 提供。

### 原始图重放与重新导图的身份区别

提交中的 `prepare_execution_protocol.py` 有意绑定**已发布的**
`REQUEST_HANDOFF.json`（SHA `a895f3045db4b2e5d124f67448602782a1aa189904d04f5a1d02ef9fb68d6792`）。它包含原始导图进程收据的身份。因此上述命令使用 Runtime 包中的已发布请求，以及研究包中与它配对的已发布导出/参考记录。

如果另行重新导图，新的进程收据和 handoff 哈希会变化，即使十个请求组的内容完全相同。不要把新 handoff 塞给这个固定身份的 preparer，也不要修改旧 handoff 或让旧收据冒充新运行。可以独立核对重新生成的十组请求与发布版逐字节一致，然后继续使用发布版配对记录进行已知 corpus 重放。若要让新的导出收据参与一条全新的端到端身份链，需另外冻结一个明确接受该新 handoff 身份的工程协议/准备程序，原有冻结协议不变；本次没有把那条尚未执行的新身份链算作成功。

## 4. 成功与失败的验收标准

科学收益仍采用原四项 primary 比较、五个 fit 为单位及固定 0.005 门槛。候选失败必须保留并恢复 incumbent，不能换种子、丢失 world、降低 fit 数或事后放宽门槛。

原生迁移要求所有 320 个 world、246,160 个 node 和 928,200 个合法 Q 都参加核验；动作必须精确一致，近似平局不豁免。普通有限误差 Q 门是原协议的一部分，本次实际误差为零。真实 packet、生产模型、实际交易收益、能源和完整经济净值不在这些命令的资格范围。
