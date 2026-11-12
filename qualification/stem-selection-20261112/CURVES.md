# 性能与成本曲线

图中种子范围仅为同一批历史文档上的描述性重复结果，不是置信区间；不同信息面板不能合并排名。数据表为 [performance_cost.csv](performance_cost.csv)，解释与限制见 [RESULTS.md](RESULTS.md)。

## 分化

![分化的参数、计算、学习曲线与跨任务变化](figures/01_differentiation.png)

## 语义、GRU 与 CfC

![时序候选的参数、耗时、B 选择与 C 后续使用](figures/02_temporal.png)

## 延迟反馈归属

![固定 GRU 上的读出信用与相同向量打乱控制](figures/03_credit.png)
