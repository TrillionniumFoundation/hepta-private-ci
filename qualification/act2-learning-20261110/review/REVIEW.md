# ACT-2 SQLite 学习实验独立复核

结论：**受限负结果已复现；不关闭产品、生产权限或 field blocker。**

最终审计对象是 run2，当前三份源码 SHA 与其 frozen manifest、执行前后回执一致。run1 是已曝光 pilot；其原始源码完整保存在 pilot-source.zip，逐文件 SHA 已核对。run2 仅增加特征与原数据库保管，但重复使用同一任务集，不能称为新的独立确认样本。

完成 220 项显式检查；另对全部 3,280 个保留 SQLite 数据库逐一核对原始字节摘要，并用独立只读 SQL 重算目标、部分效果、重复效果和 operation/payload 绑定。训练张量独立组装后与全部 fit 摘要一致；16 个模型以原种子和 220 步训练重建，所有逐步 loss 与最终参数精确一致。3,200 个确认 episode 在新 SQLite 文件中重放，决策、事件、效果计数和数据库字节摘要全部一致。重放使用审阅过的原 provider/runner，并非外部独立运行认证。

| arm | 完整目标 / 640 | success claim | primitive calls |
|---|---:|---:|---:|
| B0 workflow | 512 | 512 | 6,144 |
| B1 macro | 512 | 512 | 6,144 |
| B2 flat | 512 | 512 | 6,144 |
| B3 head | 512 | 512 | 6,144 |
| B4 GRU | 464 | 464 | 6,000 |

原件中的 false success 和 duplicate effect 均为零。head 没有严格减少原语调用；GRU 的较少调用伴随更少完成目标，不构成效率优势。两个必要 primitive-frontier 条件均为 false；保持本候选的固定 skill library 合理，不表示已证明所有 learned hierarchy 无价值。

关键限制：

- B0 与 B2 调用完全相同的 `primitive()` 控制器，不能描述为五种独立策略；B1 也来自同一确定性启发式。
- 虽有 80 个确认任务实例，但 schema 是同一 SQLite 家族中的表／列重命名，destination 是实例标签，replicate 仅改 goal hash；B1 仅出现五种不同决策序列。没有 destination-family holdout 或复杂真实组合泛化证据。
- 在线模型只使用十个手工状态特征；未见读取 scorer oracle 或未来标签的路径。scorer 是同进程同权限下另一只读连接，不能称为外部独立评价机构。
- `unknown` 等于没有 success claim，包含已知 partial/unsatisfied 的停止；不只表示缺少终局标签。事后 oracle 终局标签全部可得。
- 训练记录保留每步 loss 与最终模型，不含每步 gradient/Adam moments；13 项有限差分只抽每个参数组一个坐标。
- 执行顺序固定，计时未做随机／交叉平衡；时间数据为描述性结果。episode duration 与 collection/fit/process elapsed 有嵌套，不可重复相加。模型驻留峰值、调参机会成本和状态恢复未获资格验证。
- 未运行 Hepta FinalUse、真实 Notes、进程重启／私有状态恢复、生产权限、旧能力保持或真实外部 field 验收。

详细检查及范围见 REVIEW.json。原始源码、数据库、模型和实验输出未被本复核修改。
