# 跨演员的 N32 自由边界、解析读出和物理成本编辑

CREMA-D 的 180 个真实视听片段来自 15 位演员，每人说两句话、各有六种情绪。先排除本项目已核对的历史演员组，再按固定盐排序选 6/3/6 位训练、开发、确认演员。分别有 72/36/72 个片段。全部输入媒体的字节数与原仓库 Git LFS SHA-256 一致。训练集单独决定标准化参数。前端从原音频和视频取 32 个对齐位置，每四个位置取均值得到 8 步。各模型都学习 256→8 的输入投影，片长、人物身份和文件名不作输入。运行中使用共享 CPU、每个进程一个 Torch 线程、最多四个冷进程并行。数据准备一次 170.944 秒。

## 研究结果

| 32 更新，每臂 3 种子 | 测试演员平均准确率 | 多类 Brier | 完整拟合均值，秒 |
|---|---:|---:|---:|
| N32 原始边界 | 16.67% | .83895 | 7.45 |
| N32 名义中心化边界 | 16.67% | .83879 | 8.02 |
| N32 边界加有符号流 | 16.67% | .83470 | 7.49 |
| 替代梯度二值 LIF | 27.78% | .81764 | 3.56 |
| GRU | 25.46% | .80564 | 4.12 |
| 因果自注意力 | 29.63% | .78852 | 5.31 |
| 对角状态空间 | 26.39% | .80072 | 3.22 |
| 线性池化 | 26.39% | .79069 | 2.75 |

中心化与原始边界在每个种子、每个演员上的准确率差都是零。各个原始端到端头在 72 个测试输入上只预测一个类别，种子间的常量类别可不同。预登记门槛要求三个种子均有提升，至少四位演员有提升，平均 Brier 不变差。主检验未通过。所有 33 个拟合在登记验证刻度均未同时达到开发准确率 .35 和 Brier .82，达到该质量的时间为删失。跨种子平均开发交叉熵选出的传统对照是自注意力，逐种子选择依次为线性、自注意力、自注意力。

用训练与开发数据重新估计二次线性读出、保持各编码器固定以后，原始边界表征达到 28.24% 准确率、Brier .81674，中心化边界达到 32.41%、.80417，GRU 为 30.56%、.80577，中心化与 GRU 拼接为 34.26%、.80077。相对同法读出的 GRU，拼接达到预登记的准确率、Brier 和逐演员保持三项条件。接近零的逐演员差值应按浮点精度理解为持平。该比较增加了表征维度，也训练过两个父模型。共同的 6 位测试演员限制推断，无法把全部增量归给自由边界机制。四种表征的直接解与相同凸目标的 L-BFGS 在每个种子预测相同标签，最大 Brier 差小于 4e-7。仅计中心化头的开发选点和求解，直接法约 .0010 秒，L-BFGS 约 .1410 秒；计入父模型拟合与提特征为 8.42 和 8.56 秒。这些是同一 CPU 进程内的求解成本，完整冷进程 GPU 计时见同级 accel 目录。

独立的成本编辑在每个已训练 N32 父模型上改写 32 个 raw_cost 参数，发送、接收各半使用同一个边界目标位移，可写控制维数为二。以参考漂移反演，再逐样本走原输入依赖的真实动力学。三个开发集选中的直接改写分别使 raw_cost 最大绝对变化 .3510/.3466/.3512，在四个目标类别上的测试交叉熵分别降低 .000562/.000087/.000891，三个种子的测试准确率增量都为零，两个保护类别的准确率也持平。两个连续控制的梯度适配同样未增加正确预测。全参数对照有一个种子为保护旧类选择原模型，其余两种子的交叉熵降幅较大，二者都在全部 72 个输入上切换到了另一个常量类别，目标准确率仍持平。精确编辑命中局部位移与改善外部分类是两个可分别验证的指标。

## 数学与口径

令重置点为 a，参考漂移为 μ，贴现率为 ρ，不应期的 Erlang 折现为 η，增益为 g，维护费为 m。采用上游模型的 u=g/ρ，i=gμ/ρ²−m/ρ，k=2ρ/(sqrt(μ²+2ρσ²)−μ)，A=u/k。给定合法边界 b<a，局部脉冲成本为 K(b)=η[ua+i+A exp(−k(a−b))]−[ub+i+A]。导数为 −u[1−η exp(−k(a−b))]。在物理域内可逆，再以 atanh 写回有界成本参数。执行器将每个合法位移代回原 QVI 求根，将绝对边界残差限制在 1e-6 内；同一参考点的零位移精确保留父参数。非零输入会改变漂移和有效成本，解析式不会直接给出分类损失对整网的逆。

## 核验与复现

在本目录执行以下命令。六个 ZIP 各自可独立解压，分别保存 QVI 编码器、可学习与固定阈值对照、传统编码器、条件读出、物理编辑、数据凭证与父模型封存。`SHA256SUMS` 核对各包和成员清单，`MEMBER_SHA256SUMS` 逐一核对 339 个原始运行文件的相对路径与文件内容。复算使用 Python 和 NumPy。

```sh
evidence_dir="$PWD/evidence"
run_dir="$(mktemp -d)"
(cd "$evidence_dir" && sha256sum -c SHA256SUMS)
for archive in "$evidence_dir"/*.zip; do
    python -m zipfile -e "$archive" "$run_dir"
done
(cd "$run_dir" && sha256sum -c "$evidence_dir/MEMBER_SHA256SUMS")
python summarize.py "$run_dir" "$run_dir/recomputed.json"
cmp "$evidence_dir/summary.json" "$run_dir/recomputed.json"
```

最初传输的 `av-records.tgz` 由七个分片重组，SHA-256 为 `7e92ef71713db8bb2782605a60f535043e828a9736f8f468019137c8475bec01`。六个 ZIP 中的每个原始文件均与该历史传输包逐字节比对通过。

审阅原始训练时，results 包含 33 个权重、训练日志、耗时、预测和统一封存；readouts 包含 24 个候选头、训练选择、逐片预测和统一封存；phys 包含 12 个完整参数快照、候选轨迹、开发选择、确认结果与逐片预测。data/data_receipt.json 提供 180 个源文件摘要。各子任务共享测试集，统计单位为演员。

重新开展训练需要固定提交 c4ae70d44613434aaf165529a6076fa3400ca431 的 qualification 包在 PYTHONPATH 中，并满足上游解码器的 ffmpeg 依赖。建议使用全新工作目录保存训练阶段的不可覆盖文件。源版本和资格条件详见 protocol.json、readout_protocol.md、physical_edit_protocol.md。

```sh
python acquire.py data
python campaign.py fit results data --workers 4
python conditional.py fit data results readouts
python physical_edit.py fit data results phys
python campaign.py confirm results data --workers 4
python conditional.py confirm data results readouts
python physical_edit.py confirm data results phys
```

来源为 Cao 等的 Crowd-sourced Emotional Multimodal Actors Dataset（CREMA-D），官方固定提交 1658cd342dff90010aa843eaeebd53610a08b1dc；数据库许可 ODbL、内容许可 DbCL。
