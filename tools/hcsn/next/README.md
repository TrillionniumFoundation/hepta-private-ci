# HCSN 下一轮：完整算子、记忆修复与独立验证

本目录继续上一轮 160 次训练之后的研究，保留上一轮全部文件原字节。**完整 He–Xiong 公式派生的 C1/float32 算子已经实际参与训练；四项关联检索得到修复；“全部 blocker 已关闭”及“已经具备完整 backbone 扩展依据”仍不成立。** 当前不支持金融算子相对普通门控的稳定质量优势。

主要结论和验收状态见 [RESULTS.md](RESULTS.md)，逐项状态见 [blocker_ledger.json](blocker_ledger.json)。独立解释审查见 [INTERPRETATION_REVIEW.md](INTERPRETATION_REVIEW.md)。本轮正式矩阵为 335 次神经网络训练，另有 4 次开发集训练和 2 次线性参考拟合；实际完成数、文件哈希及重放证据由 [evidence_checks.json](evidence_checks.json) 和各实验目录核验。数值探针、重复预测、计时和 checkpoint 重放不计成新增训练。

## 内容及阅读顺序

| 目录 / 文件 | 工作内容 | 证据边界 |
| --- | --- | --- |
| [full_kernel](full_kernel/README.md) | 原完整 A7 股权、明确修改的 C1 风险函数、float32 Hermite 数值核、状态导数及 BPTT 检查 | 固定金融参数的受控近似；金融九参数不经查找表训练 |
| [sequence](sequence/README.md) | 120 次训练；八槽记忆、同预算旧 v2、完整核、普通门控、GRU、Transformer、SNN；容量与长时距挑战 | v3 在更长时距及检索门槛上仍有失败 |
| [ridge](ridge/README.md) | 105 次新测试矩阵；正则化关联统计、五种子及独立审计 | 检索成功不能替代每种子记忆标准，也不能归因于金融形状 |
| [encoder](encoder/README.md) | 40 次新文本 / 图像训练、2 个线性拟合、原始输入缺失、真实 encoder 流水线成本 | 两套独立单模态；没有配对多模态训练 |
| [ablation](ablation/README.md) | 70 次完整核和去 Call / 恢复 / 动态边界 / 记忆消融；独立重放 | 全核与 sigmoid 参数匹配；删组件实验仅宽度匹配 |
| [common.py](common.py) | 强 dtype、按形状 AOT 预编译、无额外预热更新、独立验证集选 checkpoint | 执行仍有冷 dispatch；共享 CPU 计时不是规模 / 能耗证明 |
| [verify_delivery.py](verify_delivery.py) | 历史保留、源文件、训练矩阵、checkpoint 及交付清单核对 | 完整性通过不代表科学假设通过 |

## 复现

在项目的 `tools/hcsn/` 目录工作。参考环境为 Python 3.12、CPU-only Linux；直接依赖沿用上一轮文件，并补充新视觉数据工具。

```bash
python -m pip install -r requirements-cpu.txt -r next/encoder/requirements-extra.txt
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
python next/verify_delivery.py --require-manifest
```

该命令检查已交付记录，不重新训练或下载数据。模型 checkpoint 和数值模板均随项目提供。公开预训练模型、原始数据及特征缓存不进入 Git；若要独立重放 encoder 预测，按其目录说明下载固定 revision、核验 SHA，并重新生成特征。训练随机数、数据 seed、选择规则、源码及 checkpoint 摘要均在原始 JSON 中。

重新生成完整实验时，建议复制项目保存原证据；以下程序会写入相应结果路径。

```bash
python next/full_kernel/validate_kernel.py
python next/full_kernel/check_joins.py
python next/validate_training.py

python next/sequence/run.py
python next/sequence/run_v2_reference.py
python next/sequence/run_full.py
python next/sequence/challenge.py
python next/sequence/audit.py

python next/ridge/develop.py
python next/ridge/validate.py
python next/ridge/run.py
python next/ridge/challenge.py
python next/ridge/audit.py
python next/ridge/independent_audit.py --phase static
python next/ridge/independent_audit.py --phase replay
```

冻结 encoder、完整算子消融与原始流水线复现命令见各目录 README。开发集和确认集是不同数据；重跑不得用确认集分数选择模型后再把同一个测试集称为新确认。`ridge/development_failures/` 和 solve 小步长差分失败均保留，不应删除以制造全绿结果。

## 如何解读“连续”和“自由边界”

训练对象是连续可微的神经状态、边界坐标和读写函数。快慢状态含时间间隔的指数泄漏，槽 / ridge 记忆按 token 或事件更新。整体网络不是原金融模型的非线性时间流解析解，也没有证明任意拆步不变。当前边界是输入依赖的神经偏置，不是在每个时间步重新求解原文最优停止边界。

本项目验证一阶自动微分和有限任务训练可行性；没有将 C1 可微性等同于生理脉冲、普遍相变、长期梯度有界、事件稀疏算力或能耗优势。研究名称 HCSN 不替代这些独立验收项。

## 保存与审计

`delivery_manifest.json` 列出此轮源码及证据的字节数、SHA256、Git blob SHA。它与 `evidence_checks.json` 自身不纳入清单，避免循环摘要；导出归档包括两者。上一轮 `../delivery_manifest.json` 继续约束原来的 123 个文件，本轮验证器检查其全部保持原字节。

代码按小阶段提交，生成结果和 checkpoint 与实现分开提交。没有改动 Rust 或生产运行时；当前没有运行 Rust workspace formatter/test，不能将 Python 研究验证写成整个仓库 CI 已通过。
