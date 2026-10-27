# V6 交付、证据恢复与复算

本分支交付可执行研究实现、native 合同、个人使用 CLI，以及正式实验的全部已保留证据。实际能力和未通过的验收以 [RESULTS.md](RESULTS.md) 为准；生产接入状态以 [native/INTEGRATION.md](native/INTEGRATION.md) 为准。

## 1. 三个身份不要混淆

| 身份 | 值／用途 |
|---|---|
| 正式运行源码 commit | `856c77f8f29e84e0fdcae43e1c2171aaaaac14ee`；formal runner 实际验证并执行的源码 |
| 原始 freeze SHA-256 | `a3dc02766d061d9d3031fda5117889de84d53e2a2843edfa324001ee9432d477`；源码、输入、参数与执行计划的封存身份 |
| 交付分支 | `research/memory-cell-v6-typed-network-20261027`；包含正式源码之后增加的审计器、说明和工件 |

最终交付提交晚于实验源码提交。后加的报告、source truth auditor、结构补读及打包工具不应反向算成正式执行时已有的代码。源代码树到发布树的映射保存在 [PUBLICATION_MAP.json](PUBLICATION_MAP.json)；发布时逐次检查 Git tree 相等，并用 expected predecessor 更新研究分支。

原始 freeze 里可能包含实验环境的绝对路径。这些字段保留为历史证据，不要为移动目录而修改它们。离线记录复算使用下述可移动入口；重新训练／评估则按 README 创建新的输出和 seal。

## 2. 恢复已保留证据

从仓库根目录执行。此步骤只需 Python 标准库，不需要下载 encoder、不训练模型、不再次打开 held 调参。

```sh
V6_ROOT=qualification/memory-cell-v6
V6_EVIDENCE=work/memory-v6-evidence

python "$V6_ROOT/tools/evidence_archive.py" unpack \
  --index "$V6_ROOT/evidence/ARCHIVE.json" \
  --output "$V6_EVIDENCE"
```

输出目录必须尚不存在。工具按 index 的顺序拼接分片，验证各分片及整包 SHA-256，拒绝绝对路径、路径穿越、链接、重复／缺失成员，再逐文件核验长度与摘要。恢复后的文件数为 **1,971**，文件逻辑字节合计 **156,471,571 B**。

标准 `tar.xz` 压缩流共 **23,993,596 B**，SHA-256：

`fd664ac8c417bff74ac805a3ab3e4b1e3624a126031239168a11c0524992cdf5`

Git 中按 500,000 B 分片保存，共 48 片，最后一片 493,596 B。无需 Git LFS，也没有放宽仓库 512,000 B 的单 blob 限制。完整文件及分片清单见 [evidence/ARCHIVE.json](evidence/ARCHIVE.json)。

| 解包位置 | 内容 |
|---|---|
| `router-formal/` | 五 seeds、全部 120 个 router 候选、selected 工件、特征缓存与训练成本 |
| `memory-run/` | 15 个 case 的 source／cell／artifact owner、封存、execution plan、25,920 条逐请求记录、部署与通信账本 |
| `extensions/` | 各 seed 的 learning、structure、transfer、lifecycle 工件、原始读回与成本 |
| `development/` | 实际保留的多轮 router、learning／CLI／transfer、lifecycle 开发产物和完整性说明 |
| `native-evidence/` | leaf qualification、Rust 测试、真实 bridge 和 revoked bridge 执行证据 |
| `logs/` | formal router、prepare、extensions、language 与 audit 的原始输出 |

公开 encoder 基座不重复放进包内；[download_encoder.py](download_encoder.py) 按已固定 revision、文件大小和摘要下载。不能从这些已保留开发记录推断早期缺失临时产物的成本；相关账本中明确标记的未知项仍然未知。

## 3. 在恢复目录上独立复算记录

以下命令只读取原始结果与源 SQLite，不运行模型预测，也不修改解包后的正式证据。复算结果写入单独目录：

```sh
mkdir -p work/memory-v6-audits

python "$V6_ROOT/audit_results.py" \
  "$V6_EVIDENCE/memory-run/evaluation/records.jsonl" \
  --held "$V6_ROOT/held" \
  --plan "$V6_EVIDENCE/memory-run/execution_plan.json" \
  --output work/memory-v6-audits/AUDIT.json

python "$V6_ROOT/auditors/audit_source_truth.py" \
  --run "$V6_EVIDENCE/memory-run" \
  --freeze "$V6_EVIDENCE/memory-run/FREEZE.json" \
  --freeze-sha256 a3dc02766d061d9d3031fda5117889de84d53e2a2843edfa324001ee9432d477 \
  --held "$V6_ROOT/held" \
  --output work/memory-v6-audits/SOURCE_AUDIT.json
```

预期主审计为 835,791 checks、0 failures；source audit 为 253,893 checks、0 failures。`primary_joint_gate` 仍为 false：正确覆盖率 66.67%，OOD 误接 13.54%。记录审计成功不能替代质量门槛。

source auditor 独立重算来源事实与成本，没有导入执行器或 grader；作者仍是同一实现团队成员，因此不称第三方审计。复算的是已记录模型输出及合成来源，不是再次测量原始 CPU／网络。

## 4. 同参数预算结构实验的补充证据

[supplement/structure-verification/](supplement/structure-verification/) 保留事后额外核验的 11 个文件。原始 formal 同参数上限结果缺少 winner／baseline 的全部逐地址 test predictions；补充程序只加载已冻结的两个候选，按原来的 test keys 做 **190 次额外读取**，没有训练、校准或重新选择候选。

两臂均为 95/95 的值与支持来源正确；独立重算的五个全成本 test 净收益均与原报告一致，仍全部为负。新物化的预测、成本、执行脚本、原始输入摘要和 MANIFEST 单独保存，没有修改原始 formal 目录。详情见 [SUMMARY.json](supplement/structure-verification/SUMMARY.json) 与 [COSTS.json](supplement/structure-verification/COSTS.json)。

如果需要再次执行此补充核验，它会产生另一份额外推理成本，必须使用新输出目录：

```sh
python "$V6_ROOT/auditors/verify_structure.py" \
  --formal "$V6_EVIDENCE/extensions" \
  --output work/memory-v6-structure-verification-new
```

该步骤需要 README 中的数值计算依赖，并核验 reader 源码摘要与正式冻结源码一致；不依赖 encoder。它不恢复原先未记录的时间点，只是从同一冻结模型新生成可审查读回。

## 5. 重新训练与运行

按 [README.md](README.md) 准备 Python 3.12 依赖和两个 encoder 缓存，使用全新的输出目录执行 `train_router → prepare → seal → run_language → audit_results`，另运行 `run_extensions`。

若要严格复现原 source commit，使用独立 checkout/worktree 指向 `856c77f8f29e84e0fdcae43e1c2171aaaaac14ee`；新的 README、审计器和证据包装可从交付分支读取。也可以直接在交付分支创建一轮新 seal，它会记录新的 HEAD。不得让旧 seal 指向不同 HEAD，或删除失败重跑的账本。

现在 held 已随本报告公开；再次使用同一 held 可用于重复计算，不能据此宣称新一轮盲测泛化。改变路由设计、阈值、数据或模型之后，需要新留出语言集才能评价未见请求。

个人数据不需要完整 formal 实验。README 的 `memory_cli.py write/train/read/revoke/inspect` 使用真正的 cell 和已保存 router，可以直接试用受支持 schema。模型预测、来源验证与精确事件读数在 readout 中保留不同身份。

## 6. 验证范围

交付前实际做过一次完整解包和逐文件 SHA 校验，并在恢复目录上执行了两个离线审计。它们针对工件可恢复性，不能增加产品功能测试数或独立语言样本数。

50 个 Python test methods 是分阶段定向验证；Rust 原仓库 `just test` 的六 crate leaf qualification 为 127 passed、2 个已有 ignored，随后完成 `just fix`／`just fmt`。没有声称全产品 CI、部署、跨主机或生产 TaskFlow 已经验收。native 证据与限制见 [native/README.md](native/README.md) 和 [native/INTEGRATION.md](native/INTEGRATION.md)。
