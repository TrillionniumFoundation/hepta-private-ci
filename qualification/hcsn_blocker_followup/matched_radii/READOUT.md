# 同一编辑半径下的直接解与梯度更新

在 #6991 已发表的八个录制来源上，两种更新使用相同的 18 个输入特征和一个截距、同一初始读出、相同训练数据与目标函数。逐个固定允许的 L1 权重位移后，半径 0.25 时线性规划和投影次梯度的 32 个购买决策全部相同。半径 1 时，梯度法多答对一次、少购买三次，八来源平均效用高 0.059375。原实验按开发集分别选中的半径为 1 和 0.25，得到的两法差额为 0.06875。[同坐标协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7b0af00123582ab16f55cb3f0c4314d0d3099909/qualification/hcsn_blocker_followup/readout_protocol.json) · [原研究报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7b0af00123582ab16f55cb3f0c4314d0d3099909/qualification/hcsn_blocker_followup/RESULTS.md)

| 允许的 L1 位移 | LP 净效用 | 梯度净效用 | LP / 梯度购买次数 | 两法决策相异窗口 | 梯度胜 / 平 / 负来源 |
|---:|---:|---:|---:|---:|---:|
| 0 | 0.715625 | 0.715625 | 7 / 7 | 0 | 0 / 8 / 0 |
| 0.25 | 0.765625 | 0.765625 | 5 / 5 | 0 | 0 / 8 / 0 |
| 1 | 0.696875 | 0.756250 | 9 / 6 | 5 | 3 / 5 / 0 |
| 4 | 0.696875 | 0.756250 | 9 / 6 | 5 | 3 / 5 / 0 |

每个来源有四个窗口，每购买一次扣 0.30 效用。半径 1 的五次分歧可以逐项解释。LP 额外购买四次，其中三次本来已经答对，一次购买后仍答错。梯度独自购买一次，并挽回了一次错误。因此固定这两个决策策略，价差贡献为 \(3\times0.30/32\)，正确率贡献为 \(1/32\)。两法各自在半径 1 与 4 的 19 项位移向量均逐项相同，这两行重复观察了同样的更新。半径 0.25 的更新向量彼此不同，但诱导出完全相同的 32 项决策。[原始训练与确认归档](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7b0af00123582ab16f55cb3f0c4314d0d3099909/qualification/hcsn_blocker_followup/evidence/paid-roster-04.zip)

直接解确实改善了训练目标。半径 1 时，同一带惩罚间隔损失的 LP 最优值为 0.000007864，梯度法为 0.002791。半径 0.25 时两者具有同一观测到的测试决策，原单次求解记录分别为 7.23 和 2.66 毫秒。两个时间只覆盖求解片段。固定的 32 个窗口来自八个来源，方法各只有一轮训练实例。近零训练损失、相同窗口上的多个半径以及毫秒级单次测量都不能给出一般训练加速率。原协议的采用判据对两法各选中方案都返回 false。[冻结选择](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7b0af00123582ab16f55cb3f0c4314d0d3099909/qualification/hcsn_blocker_followup/evidence/edit_seal.json) · [原参数与数据清单](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7b0af00123582ab16f55cb3f0c4314d0d3099909/qualification/hcsn_blocker_followup/evidence/archive_manifest.json)

## 复算方法

`compare_edit_radii.py` 仅依赖 Python 3.10+ 标准库。传入固定提交的 `qualification/hcsn_blocker_followup/evidence` 目录。输入只需 `affine_inputs.json` 与 `paid-roster-04.zip`。脚本先核实已发表的两份输入的完整 SHA256，再以存档特征、初始权重和锁定的更新向量重建购买决策。对八个来源分别核对购买数、正确数和扣价后的净效用，并输出每一个不一致决策的原查询 ID。以下命令将标准输出保存为 `matched_radius_results.json`。所有八个候选头和全部注册半径均进入输出，开发集的选择保留在 `dev_selected_radii`。未重新拟合、用测试标签选择半径或新增一次确认实验。[原仿射输入](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7b0af00123582ab16f55cb3f0c4314d0d3099909/qualification/hcsn_blocker_followup/evidence/affine_inputs.json)

```sh
python3 compare_edit_radii.py /path/to/hepta-private-ci/qualification/hcsn_blocker_followup/evidence > matched_radius_results.json
```
