# R16：以显式高精度回退完成有限精度合同

这是独立于原 pure-Q24 的新 profile。原生 Q24 在正式 seed `163201/163203` 上的严格 1% 证书分别只能完成 22/33 个事件，结果保持不变。本 profile 在相同 `167772/2^24` 误差合同下，遇到原生精度拒绝时，用 80 位十进制区间重放已经消费的公开事件，并对重建后的 Q24 状态给出新的实际误差证书。

新状态的误差界降低有实际计算依据和成本：它来自更高精度重算相同公开历史。原生进程重启本身不会清零误差账。整个方案因此称为 **Q24＋区间重放**，不能写成纯 Q24 在原合同下通过。

## 精确覆盖的对象

区间算法覆盖 `MODEL.txt` 中逐行归一化的整数权重模型。它不直接证明原始浮点 `expm` 的误差，更不证明连续 HX PDE。原 R15 双精度有限模型仍作为另一个描述性数值参照，其比较门槛继续是最大 L1 `<1e-4`。

`IntervalModel` 固定 80 位精度，下界运算使用 `ROUND_FLOOR`，上界运算使用 `ROUND_CEILING`。`Q24` 中心 `q/2^24` 在该精度下可精确表示。范围错误、下溢、无正似然下界或仍然过宽的区间都会失败，不能通过调大误差门槛继续。

## 区间归纳

假设 `L_i <= p_i <= U_i`，转移 `P_ij` 被 `P^-_ij/P^+_ij` 包围，所有项非负。传播使用

\[
 L'_j=\operatorname{round}_{-}\sum_i L_iP^-_{ij},\qquad
 U'_j=\operatorname{round}_{+}\sum_i U_iP^+_{ij}.
\]

其中每个乘法和求和都在指定方向的上下文执行，不是仅对最后结果加一个经验容差。

对已观察到的 token，先形成未归一化上下界 `a^-_i/a^+_i` 和总质量上下界 `Z^-/Z^+`。当 `Z^->0` 时：

\[
 L'_i=\operatorname{round}_{-}(a^-_i/Z^+),\qquad
 U'_i=\operatorname{round}_{+}(a^+_i/Z^-).
\]

公开 WRITE 以相同方向对相位内质量求和，再确定性地放入指定内容位置。结构支持按相同事件保留。每步再与概率单纯形的必要约束相交：

\[
 L_i\leftarrow\max(L_i,0,1-\sum_{j\ne i}U_j),\qquad
 U_i\leftarrow\min(U_i,1,1-\sum_{j\ne i}L_j),
\]

其中被减去的上界和向上计算，被减去的下界和向下计算。因此该收缩仍包含真实后验。

恢复只验证保存的区间，**不会再额外收缩一次**，所以从同一状态继续执行的十进制端点可以逐字相同。独立 `Fraction` 测试使用精确有理数后验逐事件验证包含关系，也覆盖极小正先验 `1/2^80` 的真实观测。

## 回退时的 Q24 证书

对选定的 Q24 中心 `q_i/M`（`M=2^24`），由区间直接计算

\[
 R=\sum_i\max(q_i/M-L_i,\ U_i-q_i/M).
\]

该求和与差值向上取整，故真实 L1 误差不超过 `R`。写入原生 checkpoint 的半径是 `ceil(M R)`。只有当该半径不超过原 `167772` 门槛时才重新进入原生执行。

原生拒绝前成功执行的事件保留。区间缓存重放这些已消费事件以及下一条被拒绝的事件，后一条由区间核恰执行一次，然后原生从下一条事件继续。动作、token、时距和内容写入均不改动，不重采样，不读取隐藏标签，也不读取未来事件来构造当前后验。

## 成本与恢复状态

每次回退保留调用起点、拒绝位置、重放范围、区间缓存字节数、Q24 checkpoint 字节数、区间状态哈希和计算收据。末尾尚未进入区间缓存的公开事件也会被重放并审计，成本纳入本 profile。

该研究实现保留完整公开事件 tape，并在恢复 bundle 中绑定它的哈希。不能据此声称无历史扫描、常量总存储或无界流的资源安全。最终 bundle 包含 Q24 状态、支持位、误差账、事件游标、整数时钟、完整 80 位区间缓存及累计计费快照。

恢复测试在第 274 个事件退出，再由独立进程完成同一条 549 事件 tape。验证逐事件状态、最终原生 checkpoint、完整区间缓存和累计重放次数。checksum/model/tape 绑定只属于**可信 snapshot** 的损坏与混用检测，不提供签名、授权或防回滚。

成本报告以外层进程 CPU 收据为准，它已经包含该进程等待的原生子进程。`replay_cpu_seconds` 是 Python CPU 的组成部分，不能再次加总；bundle 中累计 CPU 是生成 snapshot 时的下界，不能代替外层完整收据。`recorded_artifact_bytes_before_run_receipt` 明确不含 `RUN.json` 自身，完整归档索引另列所有原始字节。

此 profile 会付出高精度重放、进程调用和日志开销。它关闭的是限定整数模型/有限 tape 的持续精度与恢复问题，没有速度、净效用、能耗或真实业务吞吐优势结论，也没有原生价值规划器和生产 owner 接入结论。

## 证据与复现

`HYBRID_PUBLISH_MANIFEST.json` 固定五个新源码/协议文件；正式 seeds 是 `163211/163213`，必须在发布和读回源提交后运行。之前 `163201/163203` 的 hybrid 结果都是开发证据。

每个完整验证目录的 `HYBRID_VALIDATION.json` 给出门槛、恢复与成本结果。`EVIDENCE_INDEX.json` 列出原始文件的大小与 SHA-256。按列出的顺序拼接 `EVIDENCE.tar.gz.partNNN` 后解压，可以恢复全部原始字节；单片最大 480,000 字节。`PUBLICATION_FILES.json` 给出上传这些完整证据所需的最小文件集。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m tools.hcsn.reachable_state_r16_20261101.numerics.test_interval_replay
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m tools.hcsn.reachable_state_r16_20261101.numerics.validate_hybrid --output /tmp/r16-hybrid-reproduction --seed 163203
```

输出目录必须不存在，避免覆盖既有实验。正式运行还必须提供 `--source-commit`。完整原生来源仍固定为 `4c51e9a068a887fcf80573628e7692a1f84f9c18`。
