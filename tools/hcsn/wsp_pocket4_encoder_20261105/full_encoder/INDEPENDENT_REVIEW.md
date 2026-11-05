# 完整 Laya CPU 检查：独立结果审阅

## 结论

**通过 CPU/F32 工程检查，未形成预测或交易有效性结论。** 本次只审阅冻结源码、协议、实际结果与 supervisor 回执，未再次运行模型。111 项一致性检查全部通过；原始结果与协议文件保持不变。

检查使用真实基础检查点和已经存在的父、子 adapter。在四个公开合成且无标签的输入上，按 parent → child → restored 顺序完成 **12 次完整 encoder + head 前向**；实际 encoder hook 提供每次激活的形状、哈希和数值范围。三个目标 head 分别与独立 float64 数学参考比较，合计 **36 项数值比较全部通过**。

固定判据仍为 `abs(error) <= 2e-5 + 2e-5 * abs(reference)`。最大绝对误差为 `0.00013030747504672036`；最大“误差 / 允许误差”为 `0.027054485156926746`，小于 1。这里存在相对容差，不能将结果写成“所有绝对误差都小于 2e-5”。

## 身份与恢复证据

执行的 driver、supervisor 和 helper 的 SHA-256 与执行前审阅版本完全一致；结果中的 protocol SHA-256 对应实际协议文件。基础模型共 **321,908,995 参数**，检查点大小 **643,835,514 字节**。运行版本是 Python `3.14.4`、Torch `2.13.0+rocm7.14.0`、NumPy `2.4.1`，一个 CPU 线程，GPU 未初始化。

每个状态的 restored 最终两路输出均与 parent 逐位相同；三阶段 encoder 输出哈希相同。每次 parent/child/restored 参数装载后均检查全部六个 adapter tensor 的字节哈希，退出时再次恢复父参数。基础冻结参数在运行结束时重新哈希，磁盘基础快照、父子 adapter、manifest、源码及 live binding 重新验证一致。稍后的只读指标审计仍绑定同一 candidate、parent manifest 与 live process。

父 manifest 只含 scorer adapter。action A 来自固定源码初始化，B 严格为零，因此保持父基础 action head 的函数；这不证明历史记录中存在一个可还原的 action A tensor。此检查也没有把内存恢复等同于生产进程或运行时快照回滚。

| 合成状态 | 时间跨度 | 输入 token 数 | encoder 最大绝对激活 | 最大 PRICE logit 变化 | 最大 ACT logit 变化 | restored 逐位一致 |
|---|---:|---:|---:|---:|---:|---|
| EUR.USD / 0 | 300 s | 388 | 42.145694733 | 0.013288021 | 1.432006836 | 是 |
| EUR.USD / 1 | 900 s | 410 | 42.147026062 | 0.011462688 | 1.521484375 | 是 |
| BTC.USD / 2 | 300 s | 968 | 42.143192291 | 0.012771606 | 1.431640625 | 是 |
| BTC.USD / 3 | 900 s | 958 | 42.145328522 | 0.011142731 | 1.366943359 | 是 |

这些 logit 差值只证明既有 adapter 对输出产生影响；输入没有结果标签，不能判断变化是否改善预测。

## 成本口径

完整 child 成本采用 supervisor 的子进程测量：**CPU 32.746145 秒、墙钟 65.710593 秒、峰值 RSS 2,770,612,224 字节（约 2.5803 GiB）**。supervisor 自身另耗 CPU 0.047205 秒。

worker 内部报告的 CPU 31.596805 秒、墙钟 63.505866 秒已经包含在上述 child 口径中，**不能再次相加**。系统实际观察到 CPU 配额 50%、memory.max 3 GiB、pids.max 32；本次完成时没有触及既定 CPU 180 秒或 wall 420 秒预算。

## 失败保留与结论边界

早先 oversized transfer 在工具输入边界以 `INVALID_ARGUMENT` 被拒绝，记录没有 job ID，模型没有执行；该次不能计入模型运行次数。旧 scale-1000 激活测试仍是原固定门限下的失败，本轮真实激活测试没有取消、放宽或覆盖它。

本次没有训练、生产权重写入、broker 请求或订单；`value_qualified`、`production_rollback_qualified` 均保持 false。它不能证明样本外 PRICE 效果、NDU/Hepta Neuron 能力改进、交易收益、GPU/低精度等价性，或自主权重编辑的收益。

## 核验文件

- 主结果 SHA-256：`0d70e6f518fb761120069f151f5868b83f13f52b603255740d103619e9860485`。
- 协议 SHA-256：`3b3e7777aa2cf2a78cb0d6c305a6b622bb1a2695365f2334abef889a0cfd2b6f`。
- Supervisor 回执 SHA-256：`d89e178a006fd117f8fd51c63bea14a7032d351d778549e7b065d8115ffdf9d4`。
- 机器可读逐项审阅：[INDEPENDENT_REVIEW.json](INDEPENDENT_REVIEW.json)。
