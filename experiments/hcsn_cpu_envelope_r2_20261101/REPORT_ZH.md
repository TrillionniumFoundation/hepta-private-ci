# R2：受限 CPU worker 的执行与 RSS 验证

本组件继续固定 R1 MQAR/Binding 的 Flow/Diagonal 四个 seed17 检查点。它不修改模型或默认实现，也不新增任务能力声明。源码、依赖、四个检查点和12个固定负载在执行前冻结；远端提交 `20d45c35f5b402a4ecfe0f907d44c7797849e2db` 的 worker 源已读回。

每个负载分别使用普通 worker 和数值导入前加载内核限制的 worker，共24个真实冷进程。限制同步到所有任务，拒绝 fork/vfork/clone/clone3/execve/execveat；实际 fork 返回 EPERM，NoNewPrivs=1、Seccomp=2，结束时只有一个任务，数值阶段等待子进程 CPU 增量为零。全部12对输出 SHA256、质量和冻结检查点身份逐项相同，worker RSS 点门通过。

受限 worker 的外层 wait4 RSS 高水位为 **223,203,328–245,264,384 字节**，低于预先声明的512MiB点预算。已测 supervisor 与 worker 两者高水位之和最大 256,929,792 字节，只是这两个进程的保守上界，不是同时峰值，不包括文件系统缓存。

完整活动族内存仍未验收。当前 procfs 不提供 children 文件，实际 ptrace 跟踪也返回权限拒绝，不能独立枚举初始子进程；限制加载前已存在约0.003秒的等待子进程 CPU 计数，其来源未归因。所有初始计数照实保留，只检查加载后的增量。不能把这个 worker 的 RSS 代称整个活动族峰值，`attributable_full_family_peak_rss_bytes=null`。

前置开发中，按虚拟 PID 构造 procfs 路径、随后读取不存在的 children 文件、假定初始等待子进程计数必为零，均触发真实失败；源快照、失败说明和未执行的旧协议保留。最终用实际 task 目录、缺失能力的 null 表达和明确基线增量完成兼容性检查。跟踪权限拒绝后没有改变系统权限，转为范围有限的直接 worker 测量。前置检查没有完整外层计量，成本保留未知。

最终完整 profile 外层成本 **56.744202 CPU秒**，包含启动、导入、全部24个 worker 与结果写入。内部 worker 56.657249 秒已经包含，不能重复相加。没有 GPU、可归因设备焦耳或生产部署所有权。本组件只通过本地受限 worker 的固定负载兼容性／RSS点检查；完整族、GPU、能耗及生产采用门均保持开放。

内核接口常量来源：[libseccomp 官方头文件](https://github.com/seccomp/libseccomp/blob/main/include/seccomp.h.in)。规则实际生效及输出相同来自本轮运行记录。

复现：在仓库根目录设置与原实验一致的单线程CPU环境及PyTorch2.6.0+cpu，使用 `campaign freeze --out NEW` 后发布协议，再 `campaign run --out NEW`；必须使用新的输出目录。旧确认样本的重放只算工程复现。
