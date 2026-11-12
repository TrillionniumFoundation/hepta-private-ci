# 同会话阶段与全量验证检查点

这是进行中的源码候选与原始证据快照，不是通过报告。当前原生受测源码为 `d9737937eaccccf2ed2f1f79444ddec6c10d0eea`；三个连续 PTY 读取确认它仍在原始 `caller-full-verify` 阶段，下一字节游标为 6421。此目录里的阶段源码尚未装配进该受测源码，也没有继承其任何测试结果。

四组基础切片按 foundation → frontier → grant → observation 组成。Root 独立重算了完整前后像和 32 个正逆操作，原 504 个边界及库存仍保留，新库存为 510。实际阶段 caller 尚需由最终运行代码补齐。完整候选 CALLERS 可以由 V34 的已提交前像及四个 EXACT_OPERATIONS 顺序重建；此处没有把未装配的元数据替换为产品文件。

core-drafts 是明确未完成装配的源码快照。必需通道 EOF 的局部错误已改为关闭所有通道；Initial 预期退役的两次握手另有草稿。Root worker、真实 Prepared/Outcome 与 retained source 连接、入队计数原子交接及完整退出路径仍需实现和审查。物理 drained 不等于业务完成，记录中也没有 durable Closed 状态。

V12 原始失败记录已完成 34/34 分片与全归档哈希核验，保存在前序证据提交。V13 原导出成功，但本检查点只引用已冻结 8/42 的传输记录，后续只读恢复正在进行；没有宣称 V13 完整传输。

普通完整链、正向采用、NoUpdate/rollback 均为 **0/0/0**。独立消费者及真实 daemon 与 Root 退出后重启均未验收。所有工作保持 Draft，不合并 main。
