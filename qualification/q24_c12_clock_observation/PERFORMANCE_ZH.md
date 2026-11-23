# Q24 六次原读取的耗时与修补边界

对新复现的两条失败与早先同探针区间的两个成功读，重新按不重叠的 read_original 区间计算。下表单位为毫秒，均为进程单调时钟的经过时间，包含调度等待。每格分别是 healthy / timing。历史成功为单次原完整 Agentd 目标的两个用例，不能充当当前失败作业的配对时间基准。

| 原过程区间 | 历史成功 | c12 同源失败 |
|---|---:|---:|
| 三处 require_task_input_current 的实际调用 | 123.215 / 136.324 | 214.154 / 212.658 |
| 两处原 Cell selection 读取 | 83.140 / 91.626 | 138.746 / 182.090 |
| 按当前模式取得观察值，包括 NextUse 的原 Source 与 Cell 读取 | 60.137 / 56.309 | 117.430 / 77.200 |
| 其余已计入 owner 的标记区间 | 2.404 / 3.037 | 3.230 / 4.386 |
| 原最外调用 | 290.710 / 309.234 | 501.155 / 502.260 |

healthy 第六次 selection 处的 10.380 ms 包含到函数返回为止的误差传播；timing 的六次原读取全部完成。timing 最外服务的 handler 返回后，真实截止检查已比该服务自己的截止晚 17.578 ms。把该次 owner 内 4.386 ms 的其他标记都设成零，固定其余实测时间，服务仍会迟到。该差额属于这个具体运行，未提出新的验收门槛。

## 两个已实测候选

- a91102d3 的有界纯解析复用保留原物理读取、完整字节校验、witness、游标还原和失配后的 poison。历史证据为 226 个原测试通过、原 500 ms 单项 245.866 ms。其三个实现和两个测试与 c12 按 SHA256 逐字一致，两条失败已执行这项改进。[五项原始指纹与原测](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a91102d3639a5a1f02394bfc0331611e9ab101a1/qa/repository-consolidation/20261118/round-08/verification.json)
- 53a2877 的纯 mode 重用在六次独立窄对照中位数减少 3.024 ms；原完整四片基底 1,552 过，候选 1,551 过、1 失败，健康读返回 OwnerUnavailable。该真实失败仍有效。[历史配对资格与原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/10f9fe574f36b5e9756133db32eed4e85086ead8/qualification/hcsn-q24-native-archives-20261123)

## 当前缺口

耗时最多的 task-input 段内，Cell task 在 Source 调用前后都检查 CURRENT，Source 在持有其原始锁时核对 identity、原输入及撤销状态，在原 journal 与 witness 两侧分别校验。Cell selection 段自身也包含 coordinator 验证、Cell 的两侧 CURRENT、原 Version 读取等多项操作。旧与新探针都把这些内部操作合并计时。healthy 的错误位置已缩小到 read_learning_selection，但它内部真实返回 Unavailable 的子调用仍未被观测。整体时间无法区分物理读取、验证 CPU、锁等待和调度竞争。[原 task-input 调用](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/circuit_learning_read_service.rs#L168) [Source 物理校验](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/circuit_task_source_readback.rs#L41) [Cell selection 调用](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/circuit_feature_current_learning.rs#L11)

本次复核没有找到具备因果依据、能在保留六次实际读取、全部验证和 500 ms 合约下接入的新补丁。可重开所需的新输入为下列任一类：在同源原失败中直接识别一个有显著开销、可局部等价优化的子操作，并区分它的运行与等待和真实失败分支；或出现通过原并发、原重读与拒绝语义的独立后续修复。完整复查需要原无主动撤销的健康正例、主动撤销反例及原 timing 用例，不以一次孤立成功代替。

`cost_attribution.py result.json /path/to/original-stage.zip /path/to/c12` 可复算两批所有者区间并核对五个旧修补文件。历史 original-stage.zip 在前述固定归档的 raw 目录；新原件已在本目录。此项工作只执行已有证据的离线回放。

