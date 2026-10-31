# HCSN R8：五线交付与独立续验

入口是 [完整中文报告](DELIVERY_REPORT_ZH.md)、[复现说明](REPRODUCE_ZH.md) 和 [逐项验收账本](BLOCKER_LEDGER.json)。本目录接续冻结提交 `3a0e62c61b595576f16313c9b6016ec62cf8088b`；既有训练与确认材料原字节保留，新修复和审计另有源码身份。

| 工作线 | 详细结果 |
| --- | --- |
| 首达、尾概率、重复事件、恢复与梯度 | [事件理论和数值域](event_dynamics/THEORY.md)、[重复事件网格收敛](event_dynamics/RENEWAL_RESOLUTION.md) |
| 价值校准与次优动作 | [冻结确认结果](value_calibration/RESULTS.md)、[独立复算和训练外诊断](value_calibration/RECOVERY_20261031.md) |
| 历史压缩、风险预测与普通对照 | [任务结果](state_task/README.md)、[逐场景完整预测器计时](state_task/NUMPY_COST_REPORT.md) |
| Rust 物理 owner 和实际内容成本 | [原生实现](native_owner/README.md)、[本轮复验范围](native_owner/REVALIDATION_20261031.md) |
| killed/reset Bellman 和高维近似 | [算子前提与误差传播](event_dynamics/THEORY.md)、[高维误差及失效条件](event_dynamics/HIGH_DIMENSIONAL.md) |

原始证据、冻结权重和失败记录保存在 `bundles/` 的三组分卷中，每卷、整个 archive 和每个成员都可核验。[完整交付索引](DELIVERY_MANIFEST.json) 绑定普通 Git 文件和冻结依赖，可用 `verify_delivery.py` 只读核验。`bundles.py restore` 恢复原始路径，遇到已有但字节不同的文件会拒绝覆盖。Git 中还直接提供主要结果供阅读。

本轮成立的是限定任务域内的数值修复、首达 head 的 nominal 修复和实际原生调度成本下降。分布外策略稳健性、解析状态不可替代性、统一连续任务与原生执行、宿主崩溃恢复和一般高维保证仍有未闭合项。`production_activation=false`；独立重放和重复计时没有增加确认样本数。
