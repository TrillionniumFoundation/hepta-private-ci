# 原生工作状态

本阶段已经完成有限任务的真实 Rust 执行、恢复和最终权重一致性验证。运行仍为 `DENY_ALL`、`production_activation=false`。

| 工作项 | 实际结果 | 适用范围 |
| --- | --- | --- |
| 旧四 crate 原门禁 | 安装真实官方 nextest 后 **178 通过、1 跳过**；安装前原命令因缺少 nextest 失败 | 原 `just test` 及其脚本未替换，没有用直接测试回退冒充通过 |
| 新五 crate 原门禁 | **179 通过、1 跳过** | 保留旧 178 项，新增 joint 模型 golden；不是整仓或全平台 CI |
| 新原生流程工程资格 | **48 episode、48 崩溃条件、468 次进程调用**；Q／33 维质量／9 项 bank 最大误差 `4.44e-16` | 四族未训练 synthetic 工程模型，含实际 FullHX、24 次 pending 冷恢复、质量篡改与未读载荷检查 |
| 20 个正式冻结权重 | **80 episode、240 次原生 CLI**；最大误差 `7.77e-16`，160 次实际 FullHX，33 次 pending 冷 ACK 恢复 | 五个 fit、四个模型族，每 fit 只用已有 validation 首两世界、fixed/value 两控制器；没有新增确认世界、读取标签、评估效用或调参 |
| 独立复核 | 真实任务 5,968 项配对；另有 24 项实际 pending STOP／SUBMIT 取消检查 | 取消保持已付费用，零新增费用／时间／IO；独立原始证据单独保留 |

最终模型发布提交为 `8977e83d89fc0b2e7e74c2ed6f025adb096f5dfc`，原始冻结清单 SHA256 为 `982ccd42b472072aa860e6c0d203fab72a740bd8bef120bc6e01197b1befa29c`。20 项正式源码及全部权重在资格运行前后、封包后逐项保持不变。

真实 joint owner 使用 43 项公开输入、完整 33 维条件质量与 reset-aware bank，并执行导出的 GRU64。观测在到期边界发生，始终以 deadline 6 为目标；恢复从完整已完成历史核对保存的质量／bank，不借用旧 hard cell 或轨迹残余时间的结论。

事务层先在未发布 generation 执行真实原生 owner，完整持久化后原子发布。旧原生 witness 不被回滚；同 request id／parent ACK 可以取回已提交结果。**durable prepared receipt 之前，物理 packet READ／FullHX 可以重复**，测试已实际观察到两次执行；之后复用收据，取走原到期 packet 也不会重读。保证范围是一份已发布的逻辑后继和费用账，不是任意外部副作用 exactly-once，也不是硬件断电证明。

正式权重资格的外层 `wait4` 实测为 exit 0、wall **6.893600 秒**、完整已等待进程树 CPU **5.260879 秒**；另计具体 artifact 的独立 SciPy 审核 wall **0.449279 秒**、CPU **0.446517 秒**，最大 `T−expm(dtQ)` 误差 `4.03e-14`。这些费用包含资格检查的双方执行，不能当成单一后端的性能采用结论。

`ru_maxrss` 是实测峰值；外层数值不是并发进程内存总和。继承的 `transient_allocation_bytes=4096` 只是未资格化估计，未当作实际分配量或已证上界。Rust 检查 generator／T 表分别合法，具体冻结 artifact 另行核对指数关系；没有宣称普遍拒绝所有恶意不匹配 artifact。

旧 17 状态事务、早期 pure-policy、失败构建与开发检查记录均保留，并按来源区分。当前证据不代替正式质量／延迟／吞吐／能耗采用门、GPU 验证、一般连续自由边界或生产所有权验收。模型与原生核心没有因本次发表准备而修改，已通过的检查没有重跑。

构建与重放见 `joint_native_README.md`；精确发表文件、字节数、SHA256 和分阶段建议见 `joint_native_PUBLICATION_MANIFEST.json`。
