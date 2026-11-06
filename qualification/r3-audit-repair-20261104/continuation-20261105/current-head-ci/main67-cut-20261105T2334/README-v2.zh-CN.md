# main67：23:34 CI 原始证据切点

本包只记录 **2026-11-05 23:34:08.987–23:34:17.526 UTC** 的一次有界状态采集，以及该切点已经结束的六个关键 Windows job 的原始日志与制品。它是非原子快照，不是持续轮询，也不代表所有 blocker 已经闭合。

源码为 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`，tree 为 `3982ba56dc5a3f1da0c1de7ea57992f88125c359`。恢复测试的实际 base-merge 为 `b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae`，同一 tree。`prior-originals/` 中两份完整提交 API 保留前一次实际 GET 的时间，不伪装成新采集。

## 状态与资格

一次 runs API 加 19 份完整 jobs API，共 19 runs、53 jobs：**18 success、23 queued、2 in_progress、8 cancelled、2 skipped，0 failure**。API success 仅是任务状态，下表才是原始用例范围。

| 原始范围 | 已核对的实际证据 | 边界 |
|---|---|---|
| Windows Supervisor | 3 个恢复用例、14 个协议用例通过，零失败和跳过；raw 的唯一 PASS 名称与两份 JUnit 一致 | 严格 Clippy 和 Windows Supervisor 包级 fmt 成功；不替代 Linux 全 workspace fmt |
| Windows owner-local | UDS 14、Matrixd 31、Agentd 172 个唯一用例通过，零失败和跳过 | 原始完整日志、实际 source/tree 与工具链保留；不扩张为跨平台资格 |
| Windows Memory | 两个指定回归通过，404 个 SKIP；JUnit 的 2 个用例与 raw 精确一致 | 不是完整 Memory 包、目标硬件或生产授权资格 |
| Windows exec recovery | source-head 与 base-merge 分别为 server 254、rollout 121、resume 13 个用例通过 | 每边 resume 另有 35 个 SKIP，不在成功 JUnit 中；原命令零重试，输入保留前后相同 |
| Windows private-state | 六个原始过滤范围合计 53 个唯一 PASS；两个 acquisition 正例通过 | 此两正例已包含在原 19 个 path 用例内，不重复累计 |
| private-state 物理反例 | unchecked-create 实际出现 `created=true`；path-check-open 实际出现 `denied=false redirected=true`；各自目标断言失败、exit 1 | 这是预期反例；正常源码、两个变体、补丁和日志完整哈希一致，manifest 记录恢复完成 |
| Linux Supervisor | job `127581905245` 仍 queued、steps 为空 | 全 workspace canonical fmt 尚无执行资格；没有新增 Unix signals 资格 |
| PTY | 新六份 job 日志和七个 ZIP 没有 PTY 目标实际用例资格 | 编译 PTY 依赖不能算目标执行；既有 native10 保留清单虽含 PTY，但明确是 `NOT_REPORTED`，不推断为 filtered、skipped 或 PASS |

两条运行中的 job 都是 v8 Windows 构建。八个 cancelled job 都是 macOS 任务，runner_id 为 0 且 steps 为空；仅凭这些 API 不能断言取消原因。其他已完成任务沿用前一包的原件，不重复下载，也不借此新增测试结论。

## 完整原件和离线复核

保留六份原始 job 日志，共 **7,085,040 个原工具返回字符**；七份完整原始 ZIP 共 **188,823 字节**。每个 ZIP 的官方大小、SHA-256、CRC、成员路径和完整成员字节均已核对。原日志的 CRLF 完整保留；首次读回曾因 Python 文本模式统一换行而触发比较失败，改用原字节解码后确认写入字节没有改变，继续完成所有片段读回。该过程记录在 `terminal-originals/full-original-readbacks.final.json`。

`verify_current_cut_v2.py` 不联网、不执行 Git、不编译或运行产品代码。它核对全部 API 数量与状态、来源身份、完整 ZIP、JUnit 与 raw 的精确用例名、原命令、零重试、输入保留、两条物理反例及证据范围。nextest 的运行时和最终输出会重复显示用例，复核按二进制与完整名称去重，绝不把两次展示算成两次通过。

首次离线复核退出 0，完整标准输出即 `summary-v2.json`。`delivery-v2/` 以分片保存全部原件；封包在独立临时目录逐字节还原后，重跑此只读验证器并要求输出与冻结 summary 完全相等。该重放验证证据完整性，不是新一次原生 CI 执行。

所有状态仅对上述切点成立。未执行新 dispatch、rerun、cancel、native 容量查询、源码修改或 ref 更新。每个成功用例内部是否存在平台相关提前返回，不在本次逐例源码复审范围内；不得据此宣称整个项目或平台矩阵已全量验收。

## v2 序列化修正

首次封包的独立目录重放在完整语义核验退出 0 后，发现两个正常用例名称对应的 JSON 对象键顺序改变，因而严格字节比较失败。`custody-attempt-001.json` 保留精确差异；所有原件与统计值完全相等。v2 唯一验证器变化是启用 JSON `sort_keys=True`，并再次要求独立目录完整重放字节一致。首次脚本、summary、封包成员与传输清单作为历史证据保留；当前交付以本 README、v2 验证器和 v2 summary 为准。
