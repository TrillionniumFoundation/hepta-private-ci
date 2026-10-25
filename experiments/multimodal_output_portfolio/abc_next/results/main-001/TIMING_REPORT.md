# 新五策略真实串行成本与同源质量诊断

状态：**completed**。共 19200 次真实请求，失败或未完成评分 0 次。

每个条件覆盖五个训练 seed、16 个来源对、八个视图和两个生成场景。策略仅执行自己选择的路径；没有其他候选路径的规划成本混入该策略。

主请求时间包含 owner RNG、encoder、需要的 public sensor、实际生成、特征、critic/route 与无损 terminal NPZ 序列化及 SHA。模型加载、来源构造、磁盘写入/fsync、离线评分和统计分析单独计量。主时间不含磁盘持久化；完整摘要另报逐请求 archive append 后的成本以及全部 run 成本。

## 主请求延迟

单位 ms；所有请求保留，不删除慢请求。区间及完整工作量见 [TIMING_SUMMARY.json](TIMING_SUMMARY.json)。

| 训练臂 / 策略 | Wall mean | Wall P50 | Wall P95 | CPU mean | 完成率 |
|---|---:|---:|---:|---:|---:|
| sft_continuation/fixed | 6.587274 | 6.300107 | 8.114274 | 13.114593 | 1.000000 |
| sft_continuation/static | 6.258888 | 6.226509 | 7.816585 | 12.559987 | 1.000000 |
| sft_continuation/one_shot | 8.375554 | 8.457106 | 10.657589 | 16.708562 | 1.000000 |
| sft_continuation/feedback | 8.817919 | 9.233923 | 12.381397 | 17.633605 | 1.000000 |
| sft_continuation/legacy | 7.331834 | 7.712973 | 9.669306 | 14.501657 | 1.000000 |
| output_mean/fixed | 6.635136 | 6.405696 | 7.798772 | 13.256770 | 1.000000 |
| output_mean/static | 5.797211 | 5.501162 | 7.285255 | 11.516227 | 1.000000 |
| output_mean/one_shot | 8.799738 | 8.780168 | 10.865410 | 17.624036 | 1.000000 |
| output_mean/feedback | 9.127244 | 9.305979 | 12.265761 | 18.027893 | 1.000000 |
| output_mean/legacy | 7.117339 | 7.708421 | 9.535084 | 14.194463 | 1.000000 |
| output_ndu/fixed | 6.499063 | 6.343424 | 7.405130 | 12.919072 | 1.000000 |
| output_ndu/static | 5.846788 | 6.229706 | 7.468084 | 11.647256 | 1.000000 |
| output_ndu/one_shot | 8.336310 | 8.545728 | 10.352569 | 16.712643 | 1.000000 |
| output_ndu/feedback | 8.646325 | 9.148075 | 11.762076 | 17.286320 | 1.000000 |
| output_ndu/legacy | 6.963046 | 7.087693 | 9.180842 | 13.723033 | 1.000000 |

## 反馈与开发选定非反馈策略（注册三类候选）

参考策略在评价前按各 seed/训练臂冻结，当前数据不再选择参考。正的 cost difference 表示更贵；正的 CE gain 表示质量更高。下列区间均为描述性 95% 来源 × seed 配对 bootstrap；两个生成场景、八个视图和重放行数不扩增独立来源 N。

### sft_continuation

冻结参考：`{'17': 'static', '29': 'static', '43': 'static', '59': 'one_shot', '71': 'static'}`。

Wall mean 差 +2.189960 ms，区间 [1.1667413055664078, 3.221864456171876]；P95 差 +3.108458 ms，区间 [1.9923296499999998, 5.2298717999999935]。

primary 原始 joint CE 差 +0.003918，区间 [-0.028987156439421104, 0.04680577220642076]。

secondary 原始 joint CE 差 +0.014035，区间 [-0.02214963892358645, 0.06584610921273065]。

### output_mean

冻结参考：`{'17': 'fixed', '29': 'static', '43': 'static', '59': 'one_shot', '71': 'static'}`。

Wall mean 差 +2.584163 ms，区间 [1.3602869615039048, 3.780645351601562]；P95 差 +2.292213 ms，区间 [1.5212009225, 5.6782074]。

primary 原始 joint CE 差 +0.011446，区间 [-0.017452282606291183, 0.04840007915862892]。

secondary 原始 joint CE 差 +0.011643，区间 [-0.026612024704088088, 0.05554010399506535]。

### output_ndu

冻结参考：`{'17': 'fixed', '29': 'one_shot', '43': 'static', '59': 'static', '71': 'one_shot'}`。

Wall mean 差 +1.428072 ms，区间 [0.6520124138476558, 2.129240122617187]；P95 差 +2.088689 ms，区间 [1.2623142162499983, 4.386506150000001]。

primary 原始 joint CE 差 -0.009985，区间 [-0.0398035267570526, 0.020097002669114267]。

secondary 原始 joint CE 差 +0.004816，区间 [-0.028499899892659622, 0.04207720293498027]。

## 成本与声明范围

总 runner wall 197.768446 秒；CPU 379.884493 秒。完整 setup、归档、评分及原始工作量在摘要和本地逐请求账本中。

这是主 test 中前 16 个来源的预先注册成本队列。其质量统计不能替换 512 来源主评价。五个 seed 的 bootstrap 仍是有限样本近似；正的点估计不能自动成为优越性结论。0.002 步成本没有被当成实测墙钟价格，当前报告不声称质量收益已抵偿全部现实成本。

base 模式不执行 public sensor；enriched 模式计入输入与实际草稿 sensor。旧 legacy 按原算法执行。注册核心源码、模型与策略在主 test 开启前固定；生成后实际 NPZ 写入本地 archive，关闭并 fsync 后重开校验，才交给离线评分器。

Git 保存本详细报告、冻结协议和主要聚合摘要。原始媒体、时钟行和大 ledger 留在本地，不作为长期归档 blocker。


## 发布版来源与完整进程口径

真正的事前绑定是主 test 开始前发布的协议 `e552230547779d3f92527d62272b115e7d940ff1b56400f5e9347dabfa16a834` 及其中的 TIMING_PROFILE，见 [GitHub commit 595d6ea7d728](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/595d6ea7d728c0d293077bdf19dde31095ab5373)。本次 runtime registration 在主 512 来源正式评价完成后写入；其中 `test_outcomes_materialized_before_registration=False` 仅指本次 timing 调用在登记前尚未物化自己的队列/输出，不表示主 test 的结果此前未被读取。

完整 process wall 199.262528107 秒、child CPU 增量 382.201685000 秒、wrapper CPU 0.001912747 秒，见 [TIMING_PROCESS_RECEIPT.json](TIMING_PROCESS_RECEIPT.json)。这些进程数字已经包含上文 runner 内部计时，不能再次相加。进程口径覆盖启动至退出及日志 flush，不含最后 receipt 自身写入。

RSS 字段值 591233024 bytes 来自 RUSAGE_CHILDREN 累计高水位；未保存前序 child 基线，因此保守解释为 wrapper 范围，不能声称是本次目标 child 独有的精确峰值。

本发布版仅澄清非反馈选择名称及来源/计时范围，不改变原始数值。原始 runner 报告 SHA256：`ee101f4d20f4b74813755770f32da186bbc33231d70d26bd2c14fe3705c35c4b`；原始聚合摘要 SHA256：`0c84458bb9744d6f5c065af0032ac0debc24c48ac6e38413e7a08b2e4f11b070`。TIMING_SUMMARY.json 与原始聚合摘要逐字节一致。
