# 为什么修正一次误购仍不足以采用新策略

每个独立测试来源有四个等权窗口，每次购买视频的价格为 0.30，最坏来源相对免费回答的净效用下限为 −0.05。记购买次数为 B，额外答对数减去由对改错的次数为 G。源平均净效用变化为 (G − 0.30B) / 4。当 B 为 1 至 4 时，通过下限的充要条件是 G 至少为 1。B 为 0 时两种策略的效用相同。这一结论仅用于本实验首时点的音视频购买。

对 22 种主策略及两个预先选定半径的编辑方法，按来源重算的 192 行全部与封存数值一致。投影梯度策略在两个来源各买两次、净纠正两个答案。在第三个来源买了一次，免费音频本已答对，净效用损失为 0.075。其余五个来源均持平。

即便事后只去掉这一次误购，结果也只是两个来源改善、六个持平。相对免费回答的精确单侧符号检验 p 值将从 0.50 变为 0.25，仍高于预先登记的家族显著性水平 0.05。这个算术反事实未用于选择或训练策略。它区分了本次未满足的两项条件，即单来源的损失和跨来源收益覆盖面。

可运行 `python verify.py PATH_TO_qualification/hcsn_blocker_followup` 重算。输入取自[冻结的实验结果](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7b0af00123582ab16f55cb3f0c4314d0d3099909/qualification/hcsn_blocker_followup/evidence/results.json)。价格和采用条件见[预注册协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7b0af00123582ab16f55cb3f0c4314d0d3099909/qualification/hcsn_blocker_followup/protocol.json)。
