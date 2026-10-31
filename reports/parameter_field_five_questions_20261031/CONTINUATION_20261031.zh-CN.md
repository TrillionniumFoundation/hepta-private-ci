# Execution06 续跑 checkpoint：预启动证据已保全，等待内存

快照时间：**2026-10-31T02:01:37.528977+00:00**。这是工程续跑记录，**不是科学完成或效果结论**；旧报告继续保留。

## 实际完成的远端验证

| 批次 | 对象数 | 总字节 | 实际闭合时间 |
| --- | ---: | ---: | --- |
| 原 prelaunch 包 | 8 | 13,481,379 | 2026-10-31T01:44:29.153093+00:00 |
| 后续私有传输、准备与清理凭据包 | 3 | 140,884 | 2026-10-31T01:56:30.447665+00:00 |

两批均已实际上传并独立回读，同一实际上传版本的字节验证通过。它们没有产生生产 stage ACK。两份实际 `REMOTE_BYTES_VERIFIED.json` 的 SHA256 分别是：

- 原 prelaunch：`ee7a7d360cdc52f3019b50f5e6a4ed22de9288db0e43647224fdf13b7ffcf187`（10,654 B）。
- 后续凭据：`3c189ee9e2892c11d91c921cfe44030fa452a83d6f1c009770097ca2c851eab2`（4,438 B）。

完整私有传输响应另行保存；本公开记录不含 Library/传输标识、URL 或完整 ToolResponse。

## 已完成的缓存清理

| 范围 | 凭据中的实际空间变化 |
| --- | ---: |
| 闲置依赖缓存 | 文件系统可用空间观测增加 8,757,567,488 B |
| 闲置 profile 子项 | 文件系统可用空间观测增加 2,020,806,656 B |
| 两个明确的 tmpfs debug profile | tmpfs 释放 164,585,472 B |
| 两个明确的 tmpfs release profile | tmpfs 释放 263,024,640 B |

四个 tmpfs 范围合计释放 **427,610,112 B**。磁盘两行是各操作前后观测，不能相加后当作此刻的全局可用容量承诺；其他并发工作持续改变磁盘和内存。已选缓存确已移除，原 Cargo lock inode 保留，没有发送进程信号或调用 drop_caches，源码、模型、工具链及科学证据保持不变。原凭据的 basename、时间和 SHA256 见同名 JSON。

## 最新完整采样与 OOM 历史

最新完整 watch sample 采集于 **2026-10-31T02:01:30.125950+00:00**：effective RAM **255,070,208 B**，可用磁盘 **3,278,442,496 B**，连续通过计数 **0**。原门为 RAM ≥ **1,879,048,192 B**、磁盘 ≥ **2,415,919,104 B**。

共享 cgroup 累计 OOM/oom_kill 先前记录为 **1/1**，01:45:35 UTC 的 host 观测为 **9/2**，本次最新 sample 为 **29/6**。这些事件发生在本次已注册06科学启动之前；不能归因本项目，也没有清零或改写为本项目科学失败。watch 仍在进行，当前采样不构成实际 supervisor 准入；本次较晚采样也没有被冒称已包含在较早的私有归档包内。

## 当前状态与唯一下一步

本快照检查了真实06工作目录：`STATUS.json`、`supervisor_run/START_POLICY.json`、`daemon_bootstrap/`、`wait4_launcher/` 及 COMPLETE/FAILED 均不存在；新增生产 **ACK = 0/17，已接受 ACK = 0/17**。新增科学 worker/gradient microsteps 均为0，**原十二小时运行窗尚未启动**。已导入A17仍归属此前完成的原运行。

待资源恢复且无既有启动标记后，唯一冻结生产入口为 `operational/parameter_field_recovery06/daemon_bootstrap.py --execute`，使用原已注册 pipeline 和精确 expected SHA256。实际 supervisor 仍须取得间隔十秒的连续三次原阈值通过；watch 不能替代该证据。保持原 worker 300秒 backpressure 等待上限、43,200秒外层窗和OOM检查；不重建 initializer/A17，不直接启动 supervisor 或 wait4 launcher，不对未知启动结果自动重试。

绑定保持：C1 `058cd3d22aecbf67f9c5054f2131eeb0ccd55793`；C2 `bc4e757f5c90f6365f383c1127be710d2ded874a`；protocol SHA256 `2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55`；pipeline SHA256 `d16bac3194b36d286f180976ddbc7dff16e544763e195d408a135b30af4fb86e`。
