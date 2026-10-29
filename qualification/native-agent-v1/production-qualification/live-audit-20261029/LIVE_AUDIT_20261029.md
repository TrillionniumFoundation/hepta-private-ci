# P1 三路代表任务：live 结果独立审计

日期：2026-10-29。状态：**已执行的局部比较；production verdict 仍为 held。**

本报告审计 `representative-live-matched-v1`、`representative-live-individual-v1` 两组共 24 个 live case，并单独审计 `representative-long-output-v4` 的 3 个 replay case。没有重跑或改写原始结果。以下结论来自原始模型请求、SSE、工具 admission、runtime job 终态与磁盘产物，而不是从通用错误字符串推断。

## 1. 可支持的结论

两组 live 的原门禁成绩分别为 **9/12、5/12**。全部 **10 个 live 失败都是第 6 个有效、新 call ID 的工具 proposal 到达时，既定 `tool_calls=5` 上限拒绝继续 admission**。没有发现未知工具名或重复 call ID；107 次 live 模型请求均有 `response.completed`、`status=completed` 的 provider 终态。因此，“任务未完成”不能改写成 provider 返回 `response.incomplete`。详见 [逐调用附录](FAILED_CALLS.md) 与 [CALL_LEDGER.json](derived/CALL_LEDGER.json)。

三路采用了相同应用任务和同一实测模型服务，但实际模型输入不同。Codex 两路注入了额外的 developer/环境消息，工具 `strict`、`parallel_tool_calls`、`store` 和请求元数据也不同。原 CLI 标签 `behavior_matched` 在此只能解释为 **application-task matched**，不能解释成相同实际请求，更不能解释成逐字节相同输入。

第二组只有 native 的 context/full-output 上限收紧；实际请求与输出远低于这些新上限，且 native 四个任务的初始实际请求在两组之间逐字节一致。当前记录不支持“优化使 native 优于 app-server”或“更小预算提高了质量”的因果结论。

长输出 replay 的三个物理 job 都成功、完整、持久地保存了同一份 1,179,648 B 输出；只有 facade 的观察及模型交付流程通过。另两路保留了 `pending_tool`。这反映了当前 bounded observation 路径的实际缺口，不能将其计为三路长输出能力全部通过。

## 2. 证据与复核范围

冻结原件 archive：`evidence.tar.gz`，3,179,371 B，SHA-256：

```text
d2fe31ff5c35d62d862d5afe3047973224ba5419cb61c8adf64cf8b809a438b1
```

独立脚本逐一读取并校验了 manifest 内 **2,996 个原文件、18,290,796 B**；无 missing、无不稳定读取、无大小或 SHA 不匹配。归档另含 manifest，所以解包共 2,997 个文件。[MANIFEST_VERIFICATION.json](derived/MANIFEST_VERIFICATION.json) 保存结果。

`audit_live.py` 对所有 case 做了以下实际核对：原始请求哈希/长度、模型响应与记录数量、provider terminal、逐 proposal 与 owner admission 的工具名/参数绑定、已进入后续请求的反馈不被改写、完整 runtime stdout/stderr 的长度/哈希、不可修改的 workspace 输入保持不变。它依据 gateway 实际的 JSON 编码和 token-cap 变换重建了每一份 effective body，并与原记录的 effective SHA/长度逐一一致。原 gateway 没有保存 effective body 文件；重建不能冒称原始 wire capture。

`audit_supplement.py` 再校验模型身份后验原 PTY 的 `bytes_hex`、chunk SHA、长度、exit=0 和完整性；对照前验核验模型、进程、库和 provider 源码，输出时间线与输入差异。

原执行使用 qualification `SessionOwner`。这些 case 没有覆盖完整 Agentd/FinalUse 生产组合；小任务集也没有登记为一般 agent 能力基准。此前同规定 proposal 序列的 **12/12 replay** 是行为契约与真实工具执行证据，仍不测 live 模型推理质量，也不证明三路输入相同；本归档主要包含随后两组 live 及长输出 replay，未重新审计此前完整 replay 原件。

## 3. 两组 live 结果

每格为 edit / repair / multi_tool / mcp_readonly，顺序固定。每路每任务只执行 1 次。

| 组 | app-server | facade | native | 合计 |
|---|---|---|---|---:|
| application-task matched | 通过 / 通过 / 通过 / 通过 | 失败 / 失败 / 通过 / 通过 | 通过 / 通过 / 通过 / 失败 | 9/12 |
| individual candidate | 失败 / 失败 / 通过 / 失败 | 失败 / 失败 / 通过 / 失败 | 通过 / 失败 / 通过 / 通过 | 5/12 |

不能从一次小样本排序推断一般能力。两组按 matched → individual、各组按 app-server → facade → native 顺序执行；没有随机顺序、重复试验或独占模型服务控制。模型没有显式 seed/temperature 字段。只能报告实际发生的轨迹，不能把轨迹差异全部归因于某个架构选项。

### 3.1 十个失败的实际原因

下表中的工具调用都是真实 provider proposal。`read` 失败一般是请求了未注册路径；这些失败也消耗一次工具调用。第 6 次均未产生新的 owner admission。

这里的“有效”指工具名已注册、call ID 合法且新、参数可解码，不保证目标路径获准或操作一定成功。

| 组 / lane / case | 前 5 次实际轨迹 | 被拒绝的第 6 次 |
|---|---|---|
| matched / facade / edit | 读源码；错读 `tests/test_calc.py`；读 `test_calc.py`；错读 `src/tests/test_calc.py`；patch 成功 | tests |
| matched / facade / repair | 初始 tests 失败；读测试；错读 `calc.py`；读 `src/calc.py`；patch 成功 | tests |
| matched / native / MCP | MCP 成功；tests 失败；错读测试；写测试被拒；错读绝对路径 | 读 `workspace/test_calc.py` |
| individual / app-server / edit | 读源码；错读 `tests/test_calc.py` 两次；错读 `tests/calc_tests.py`；patch 成功 | tests |
| individual / app-server / repair | 初始 tests 失败；读测试；错读 `calc.py`；读 `src/calc.py`；patch 成功 | tests |
| individual / app-server / MCP | MCP 成功；tests 失败；错读测试；错读 `workspace/test_calc.py`；错读 `workspace` | 读 `workspace/README.md` |
| individual / facade / edit | 读源码；错读 `src/test_calc.py`；错读 `tests/test_calc.py`；读测试；patch 成功 | tests |
| individual / facade / repair | 初始 tests 失败；读测试；错读 `calc.py`；读 `src/calc.py`；patch 成功 | tests |
| individual / facade / MCP | MCP 成功；tests 失败；错读测试；错读 `workspace/test_calc.py`；错读 `README.md` | 读 `workspace` |
| individual / native / repair | 初始 tests 失败；依次错读 `calc.py`、`main.py`、`production.py`、`production-qualification.json` | 读 `main.py` |

“同一个路径又读了一次”与“重复 call ID”不同。individual/app-server/edit 两次读取同一路径的 call ID 不同；预算照常累计。这次 109 个 live proposal 中没有重复 ID。99 个 proposal 被 owner 接纳，另外 10 个正是被拒绝的第 6 次。

individual 两个 Codex MCP 失败中，第 5 次 read 已有 backend `completed`、exit=1；同一轮紧接着的第 6 次被 guard 拒绝，所以第 5 次反馈没有进入新的模型请求。它不是未执行或输出丢失。附录把“backend terminal 已有”和“模型后续看到了反馈”分开列出。

这些证据表明，路径猜测与 MCP 成功后的无关测试消耗了预算。但“提示缺少文件清单导致了全部失败”仍只是合理机制推断，未做对照验证。原 repair 任务不提供源码路径，没有目录列表工具；所有 case 均暴露六个工具，MCP case 也暴露 tests/write。应在新版本任务定义中一致地修正这些歧义，不能回填旧分数或仅调大 max=5 把失败抹掉。

## 4. 实际模型输入未对齐

[INITIAL_INPUTS.json](derived/INITIAL_INPUTS.json) 保留各初始请求的角色、文本、字段和哈希；[INPUT_ALIGNMENT.json](derived/INPUT_ALIGNMENT.json) 比较 effective 初始请求。

| 实际字段 | app-server / facade | native |
|---|---|---|
| 初始原请求大小 | 约 6.4 KB | 约 2.1 KB |
| 共用 instructions 的位置 | developer message | 顶层 `instructions` |
| 额外前缀 | 第二条 developer 消息含 skills/权限；另有日期/时区 user 环境消息 | 无这些注入 |
| 用户任务 content | `input_text` 数组 | 字符串 |
| 六个工具的 `strict` | 全部 false | 全部 true |
| `parallel_tool_calls` | true | false |
| `store` | false | true |
| `reasoning` / `include` | `{}` / `["reasoning.encrypted_content"]` | 未提供 |
| cache / client metadata | `prompt_cache_key`、安装/线程/turn 等标识 | 未提供 |
| 原请求 `max_output_tokens` | 未提供，gateway 加入 1024 | 已提供 1024 |

额外 skills 文本包含按 case 变化的 CODEX_HOME 绝对路径。Codex 两路本身也有不同的目录与线程标识。因此 app-server 与 facade 的完整请求也不逐字节相等。

六个工具的 name、description、parameters、required/additionalProperties 在去掉 `strict` 后相同；整个工具数组并不相同。对规范 JSON 排序编码后的 SHA：

```text
Codex tools:        3a6ab84eb1a6e49a1a8489c0945aa0e1ce888539e78ba61fbe1e0210f54dfae4
native tools:       36e719a4d17dd409f225a93b191c3f8ac45eacc2c1655f902be7e61cb1b03940
去掉 strict 后全部: f9418d8c8ebc9bc3a1c7eeec6c77f3f5e44806e68b6a49ca004700ce9b3f871b
```

**HTTP headers 的原始捕获缺失。** `client_metadata` 是 JSON body，不是 HTTP header。源码显示 qualification gateway 显式发送 Content-Type/Accept，未转发入站客户端 headers；底层库还会生成 Host/Content-Length 等。该源码事实不能替代当次完整 wire headers 记录。

## 5. 预算值与真实执行语义

matched 三路共同声明：context 65,536 B；每次 output tokens 1,024；model calls 6；tool calls 5；完整 tool output 32,768 B；model timeout 120 s；tool timeout 60 s。

individual 的 app-server/facade 完全未变。native 仅将 context 降至 16,384 B、完整 tool output 降至 8,192 B。该组 native 最大实际请求 **8,389 B**、最大完整工具流 **1,083 B**，均未触及新限制；matched native 最大请求 10,197 B、工具流同为 1,083 B，也能放进新上限。native 四个初始请求在两组中逐字节相同。

全体 live provider 单次 output usage 的最高值为 361 tokens，没有观察到 1,024-token 上限耗尽。所有失败发生在工具 admission 上限，而不是 context、输出 token 或 provider terminal 上。

相同配置数字也不等于相同 deadline 语义：

- native `engine.rs` 在 `collect_model` 外使用 120 s 的 Tokio 整段 deadline。
- Codex 模型请求经过 common gateway；其 `HTTPConnection(timeout=120)` 是 socket 操作超时，不是整个流的 120 s 总 deadline。qualification backend 的 `model_timeout_seconds` 不会控制 Codex 自己的模型循环。
- `representative_compare.py` 给三路外层任务设定 240 s 等待；它与每次模型/工具 deadline 是不同范围。
- 工具 helper 的 60 s deadline 在 verify/admission/checkpoint 后建立；native `drive_tool` 也在 admission 后建立。backend `elapsed_ms` 包含更早的 owner 打开等工作，所以超过 60 s 的总体记录不能直接视为内部 deadline 被绕过。
- 取消后等待 `tools.cancel` 的额外上限不同：native 使用另一个 `tool_timeout=60 s`，外部 helper 使用 5 s。两者保留原 pending，不以取消请求冒充终态。

这些差异在原始采集源码中可直接看到：`raw/source/codex-rs/hepta-native-agent/src/engine.rs`、`raw/source/qualification/native-agent-v1/runner/src/tool_session.rs`、`model_gateway.py`、`protocol_driver.py`。它们限制了跨 lane 的耗时比较。

## 6. 包含失败的模型使用量与耗时

以下是 24 个 live case 的 **全部尝试**，未只选择成功任务。数据为 provider 返回的 usage；cached input 是输入 token 的子集。完整逐 case 数据见 [COSTS.csv](derived/COSTS.csv)；聚合见 [AGGREGATES.json](derived/AGGREGATES.json)。

| 组 / lane | 通过 | 请求 | 工具 proposal / admission | input | output | total | cached input | 未缓存 input |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| matched / app-server | 4/4 | 17 | 15 / 15 | 53,630 | 1,424 | 55,054 | 40,032 | 13,598 |
| matched / facade | 2/4 | 18 | 20 / 18 | 58,208 | 1,963 | 60,171 | 43,699 | 14,509 |
| matched / native | 3/4 | 21 | 18 / 17 | 43,970 | 1,431 | 45,401 | 39,189 | 4,781 |
| individual / app-server | 1/4 | 18 | 21 / 18 | 58,000 | 1,701 | 59,701 | 43,675 | 14,325 |
| individual / facade | 1/4 | 17 | 22 / 19 | 54,741 | 1,342 | 56,083 | 40,362 | 14,379 |
| individual / native | 3/4 | 16 | 13 / 12 | 31,734 | 1,188 | 32,922 | 29,373 | 2,361 |
| **全部 live** | **14/24** | **107** | **109 / 99** | **300,283** | **9,049** | **309,332** | **236,330** | **63,953** |

native 这批轨迹用了较少输入 tokens；其更短前缀、不同工具策略、完成轨迹和缓存状态同时变化，不能把差值解释成纯执行层节省。服务为本地模型，没有提供可用于金额换算的实际单价；没有实测 RSS、CPU、GPU、能耗或可归属的服务资源成本。不能把 token 使用量换写成系统开销或部署成本。

8 个失败的 Codex case 缺少 task `wall_ms`：异常在 `run_case` 的 `row.update(result=..., wall_ms=...)` 前退出；错误捕获也没有保存 `LaneAbort.result`。因此不从剩余成功行计算跨 lane 的平均耗时、p95 或速度倍数。原 driver 记录 matched 总计 593.349 s、individual 381.640 s；这包括启动/清理和不同执行轨迹，不是优化收益。

长输出 replay 与 matched live 在 main 上时间重叠：matched 模型 gateway 窗口为 15:18:24.558–15:27:51.207 UTC；长输出 replay 模型窗口为 15:18:53.286–15:21:12.797，最后 native backend 返回约 15:22:15。没有测得独占主机负载。后验模型服务快照仍有 active_requests=1，也不能声称这是专用模型服务。

## 7. 长输出：底层完整，交付流程未全部完成

该组是 **replay**，模型 usage 是预设合成值，不计入上面的 live token 成本。配置允许完整保留 4 MiB，模型可见条目预算 4,096 B，工具 deadline 60 s。

三条原 `exit.json` 均为 exit=0、cancelled=false、timed_out=false；stdout seen=stored=1,179,648 B、stderr=0；无 log error、synced=true、truncated=false、output_complete=true、output_durable=true、terminal_publication_protocol=1。三份原 stdout 的 SHA 相同：

```text
f70ff820f5588c15fd6bad61636b765bcdd8fa1e36c9e05e48dce455010babfd
```

| lane | 物理 job ID | started → exit | exit → backend reply | backend elapsed | harness |
|---|---|---:|---:|---:|---|
| app-server | `1a1883e2109-94be3-1` | 1.574 s | 57.284 s | 64.084 s | pending_tool，失败 |
| facade | `1a1883f46d0-973fb-1` | 1.710 s | 55.507 s | 62.250 s | completed，通过 |
| native | `1a188403b58-9bebd-1` | 2.186 s | 55.838 s | 63.390 s | pending_tool，失败 |

[LONG_OUTPUT_TIMELINE.json](derived/LONG_OUTPUT_TIMELINE.json) 保存原时间字段和验证条件。它证明输出生成与底层保留早已成功；不证明每个阶段用了多少时间。

`runtime_bridge.rs` 用固定 16 KiB 页顺序读取，1,179,648 B 至少需 72 个读取循环，之后再次 observe 原 request/receipt；presentation 还会核验保留引用。后者不是第二次全量读取。顺序小页是明确的实现事实，也可能解释较长观察耗时；原记录没有逐页时间，所以暂不认定它就是唯一根因，也不声称每页必定启动一个 SSH 进程。

优先修复应先记录 admission/dispatch/terminal-observe/page-read/final-verify/presentation/cancel 的单调时间，再评估复用 runtime 已有完整输出 accessor 或适度加大有上限的页。必须保留原 job/request/child 身份、完整流长度/哈希、durable terminal 和保留引用约束。单纯延长 60 s 不能解决证据与接口问题。本轮 qualification excerpt 也不能代替生产 checkpoint/fold 的长输出恢复证明。

## 8. 模型、服务与执行文件身份

模型 alias 和全部 live response model：`qwen38-flash-next-uc`。观测到的实际权重文件为 `Qwen3.8-Flash-Next-Uncensored-IQ4XS-NGQ4.gguf`，98,403,356,224 B，完整 SHA：

```text
cedf1e08063f6df77926e1169f67b327dcc6301b5b329589615bdf09d4895f7e
```

两组 live 后再次读取了全部权重文件，耗时 196.125 s，SHA 与前验一致。前验 refresh、后验读取前后均为同一 PID 188315、boot `b1620269-aaef-43e7-bf47-bc6eb1c1a447`、start ticks `3487379`，模型 device/inode/size/mtime 亦一致；8 个映射实现库逐文件 hash 相同。两个 main provider 源文件和 routing config hash 也一致。详见 [POST_LIVE_IDENTITY.json](derived/POST_LIVE_IDENTITY.json)。

provider revision 为 `open-responses-unified-native/r12-reasoning-loop-20261028`，服务实现版本输出为 `llama.cpp/0.7.0-dev+620d222`；routing SHA 为 `14cc9e9df85b3408dee556750fb680a13a5f6b4793400f87d97d0cad04c6f506`，观测时 active=llamacpp、connect_only_failover=false、cloud_fallback=false。

这是运行前后端点观察与后验第二次完整 hash，不是全程 inode lease、逐请求服务归属证明或独占 GPU 保证。前验 `MODEL_IDENTITY_EVIDENCE.json` 的“尚未第二次 full hash”是当时的冻结快照；本后验附录追加新事实，不覆盖旧文件。

本试验是第三方 Qwen 服务与三个执行 harness 的组合，不是 OpenAI 专有 Codex 模型能力评测。三份运行文件的原始测量 SHA 如下；本地审计没有复制或重新 hash 1.5 GB 的 Codex 二进制，而是校验归档中的 FROZEN 与源码/config 记录。

| lane 文件 | 原始测量 SHA-256 |
|---|---|
| native-published-v4 | `2ce78fe6b96c9d456e2de41fa4cb07988c212f2c43c392d194fd6805f42cfdf6` |
| codex | `7b9a74955391ef21e56a021cd119c0e934d42d4b24339bccf0af8c74abc331cc` |
| hepta_facade | `4f96fb3aa150f7f182f4527da2e83ce836a7a77d08206ce69dee294a049563a8` |

native 文件的构建 metadata 为 29,741,584 B。没有统一 release/debug/strip/link 配置的三路二进制实验，也没有运行时内存测量，不能由这一个文件大小宣称系统轻了多少倍。[SOURCE_VERIFICATION.json](derived/SOURCE_VERIFICATION.json) 明确区分实际校验的源码与仅有原测量的二进制。

## 9. 有限修复与下一轮门槛

1. **修正报告语义和观测数据。** 保留旧 CLI group 标签以对得上原件，文字使用 application-task matched / individual candidate。guard 分别记录未知工具、重复 ID、budget exhaustion；总是保留失败 wall time、`LaneAbort.result`、拒绝的 call ID 与已接纳计数。
2. **固定实际初始输入。** 按 [CONTROLLED_INPUT_PLAN_20261029.md](CONTROLLED_INPUT_PLAN_20261029.md) 在 qualification gateway 引入显式、冻结的 canonical 初始 body，记录变换前后完整字节与 SHA；逐 case 要求三路发往 provider 的初始 body SHA 相同。保留原生构造的 end-to-end 组。初始相同不能升级成所有后续输入相同。
3. **消除任务定义中的可避免歧义。** 在新的 corpus 版本中三路共同给出文件清单、测试入口、调用预算和 MCP 成功条件；如改用 case-specific 工具集，也必须共同冻结版本。原 24 个结果保持不变。
4. **让时限可比较。** 明确模型整流 deadline、工具工作 deadline、取消清理 grace 和外层任务 deadline，记录各阶段时间。修复后验证实际语义一致，而不只检查 JSON 数值。
5. **先闭合长输出观察。** 用原完整输出与原 owner 证据验证页/完整 accessor 的调整；随后独立验证 pending 续观测与生产 fold。保留所有失败原件，不把未跑的修复写成通过。

这些是根据当前证据给出的实现建议，尚未在本审计中实施或重跑。现有证据可以支持继续发展 native harness；尚不足以宣布它已完整替代 Codex，或把一般智能、生产恢复与总系统成本问题视为解决。

## 10. 本地复核入口

将上述冻结 archive 解包至本目录 `raw/`，并保留两份 post-live 原 PTY JSON；然后运行：

```bash
python3 audit_live.py
python3 audit_supplement.py
```

两脚本仅使用 Python 标准库读取证据并重建 `derived/`，不联网、不运行被测代码、不启动模型或 runtime job。报告引用的关键机读文件为 `MANIFEST_VERIFICATION.json`、`CALL_LEDGER.json`、`INPUT_ALIGNMENT.json`、`COSTS.csv`、`AGGREGATES.json`、`LONG_OUTPUT_TIMELINE.json`、`POST_LIVE_IDENTITY.json`、`SOURCE_VERIFICATION.json`。原始 terminal/admission/job 证据的 archive 内路径在 `AUDIT.json` 中逐项列出。
