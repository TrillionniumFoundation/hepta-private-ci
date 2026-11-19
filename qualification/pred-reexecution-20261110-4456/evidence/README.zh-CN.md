# PRED 新执行004：完整训练、重放与原件

新执行注册于 [#5668](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5668)，提交 `260922ba18438a24b2941c306606ec853f4a7348`；所有正式数据在发布和读回后生成。本次没有恢复或替换未定位的旧189-fit原件，两组旧确认集仍封存。

## 完成的实际执行

- 189/189 fits 完成，零失败；每fit30epochs/960optimizer calls，共181440calls、23224320次训练样本呈现。
- 完整保留189个checkpoint及Adam状态、曲线、逐任务预测/选择/费用、九份冻结源码、配置、日志、原始启动/终态回执。外层墙钟623.474455秒、child CPU622.591221秒；这不是全生命周期物理成本。
- 在新的执行身份门禁与原完整campaign门禁通过后，重放全部189个checkpoint，零新训练；外层墙钟16.065397秒、child CPU15.712234秒。
- 独立算术实现核对训练1276个、重放2926个summary数值叶子，最大差分别2.46e-14、8.88e-16。Fixed1原件桥接193536个逐episode字典精确相同。这些重复任务不是独立确认样本。

## 结论与边界

GRU原始observed NLL的有限网格差异中，data分量为82.05%；这可能包含难度、缺失与标签粗化的变化，不能解释为优化失稳的因果比例。与single-step配对后，NLL差异的data×init交互占39.83%；效用差异的同交互占43.11%。没有一个随机源足以解释全部变化。

| GRU，扩展资源面板 | 预期模拟净效用 | 实际样本模拟净效用 |
|---|---:|---:|
| 廉价匹配Fixed1 | 0.635655795 | 0.633427337 |
| 匹配缓存1/3 | 0.633934056 | 0.631681183 |
| 匹配缓存1/3/6 | 0.633743018 | 0.631383957 |

短/长策略的平均模拟环境成本分别增加0.033609961/0.037669864；七种模型的短/长期望净效用均下降，实际样本方向有正有负。原资源面板仍全部STOP；budget16/deadline20仅为注册资源干预。上述效用不是成功率百分点；本实验是准备时长选项的直接预测，不是latent rollout。

本开发网格中，删去action显著变差，完整history对比reset的增量小；无显式clock/lag的GRU开发均值较好，故显式timing编码优势未成立。顺序与missingness仍可见，不能把该消融解释为去除全部时间信息，也不能据此删掉真实回执中的时间事实。下一实验应处理数据/初始化交互与编码方式，并继续以廉价Fixed1为强对照。

这些是有限train/dev诊断；未计算新p值或选择确认赢家，未改变历史+0.020与p≤0.05门槛。真实owner动作历史、经认证的效果/单位、native-history训练、readback驱动的真实行动、完整物理成本与新独立任务净收益仍未闭合，HOLD保留。

## 原件与复核

[训练独立复核](TRAINING_AUDIT.zh-CN.md)与[重放独立复核](REPLAY_AUDIT.zh-CN.md)包含完整模型/消融表。`analysis-methods.tar.xz`保存两份独立复算源码、完整JSON结果、额外新执行pre-gate及实际replay外层脚本。

`ARCHIVES.json`列出完整训练和重放archive的每个part大小、SHA256及Git blob身份。按其parts顺序拼接分别恢复training-004.tar.xz与replay-004.tar.xz，再验证archive SHA256。两个压缩文件清单保留799个原始文件的独立大小/SHA256；ARCHIVE_VALIDATION.json记录逐成员与拼接验证。每个大part在原blob policy中追加精确字节pin，原allowlist前缀和阈值不变。

所有raw曲线、逐episode记录和checkpoint均已保留，没有用summary替代原件。声明时间和操作计价仍未覆盖全部物理、能耗、资金与组织成本；新原件不证明旧失联运行发生或完成。
