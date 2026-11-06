# #4895：固定 Chain 254 的双端 packet-v1 源码增量核验

封存时间：2026-11-06 02:08:16 UTC。本篇追加到已有并行 PR 审计，保留旧切点正文和结论。

## 结论

固定 Hepta `09de43ba008ad594b31551cdaa928c77da17597a` 与固定 Chain `254033da23faf10f24a62249f40ce2ddb542645a` 的真实源码已经实现可以相接的完整包传输：公开客户端、真实控制 socket、普通 PQ FinalUse owner、PoN 子进程 stdin 与 Chain 的完整 Packet 解码和 submit 分支均有对应实现。因此，bounded packet-v1 应记为明确的源码推进。

本次只接受“固定源码中双端路径存在、边界和字节格式相容”。未取得并独立核验这两个精确版本组合的原始配对原生执行、工具链、构建产物及完整验收输出；没有新启动任何原生任务。B16/B19 的完整接受条件不因此闭合，B18 的科学资格也不由包传输推出。

## 固定身份及真实 URL 来源

| 对象 | 实际固定身份 |
| --- | --- |
| Hepta commit | `09de43ba008ad594b31551cdaa928c77da17597a` |
| Hepta tree | `c8e1c878358800eef319740b5d7667b96070afc8` |
| Chain commit | `254033da23faf10f24a62249f40ce2ddb542645a` |
| Chain tree | `afd521c35d4f342cc6e7c1ca0827405034bd63d5` |
| URL 来源 | Hepta `codex-rs/Cargo.lock`，blob `fb06f0969d1581d3599a769a6cd4b03daaeba858` |

[固定 Cargo.lock](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/Cargo.lock) 实际包含 `git+https://github.com/TrillionniumFoundation/Trillionnium-Chain.git?rev=254033da23faf10f24a62249f40ce2ddb542645a#254033da23faf10f24a62249f40ce2ddb542645a`。这是已有源码给出的真实仓库地址和完整版本，未猜测仓库、分支或版本。完整锁文件 UTF-8 为 426,460 字节，重算 Git blob 等于固定目录 API 所指对象。

两侧 commit API 均完整取得。Chain recursive tree 为 11,624 项、`truncated=false`；实际用 code-mode 重建其 1,194 个目录对象，每个对象及根对象均与原 API 相等。Hepta recursive tree 的两次请求出现传输关闭，错误保留；Hepta 选定源码使用四个固定 ref 目录的实际 path→blob 绑定和 commit API，不声称回收了其完整 recursive tree。

## 原门保留与 49,508 字节的具体来历

[协议常量](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agent-protocol/src/lib.rs)、[旧 inline host 校验](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/automation_effect_host.rs) 和 [控制帧读取器](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/control.rs) 给出的当前门如下：

| 层 | 实际上限 / 条件 | 49,508 字节完整包的关系 |
| --- | --- | --- |
| 旧 inline 解码后载荷 | 24 × 1024 = 24,576 字节，host 原入口仍检查 | 超过，旧入口继续拒绝 |
| 旧控制 JSON 帧与新 header | 65,536 字节，包括完整换行帧 | 包若 hex 化，仅 hex 就有 99,016 字符，尚未计 JSON 元数据 |
| packet-v1 独立原始包体 | 非空，最多 64 × 1024 = 65,536 字节 | 完整 49,508 字节可在此边界内传输 |
| 固定 Chain CLI 的 packet 输入 | 1,048,576 字节；读取上限再多一字节用于拒绝超量 | 是 Chain 自己的输入门，不是修改 Hepta 旧门 |

49,508 可以直接由固定 Chain 源码推导。[pon_wire.rs](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/254033da23faf10f24a62249f40ce2ddb542645a/trillionnium/crates/trnm-protocol/src/pon_wire.rs) 的 Header 为 318 字节；[pon_work.rs](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/254033da23faf10f24a62249f40ce2ddb542645a/trillionnium/crates/trnm-crypto-primitives/src/pon_work.rs) 固定 `N=64`、`CELLS=N*N`，完整 proof 为 `4 + 3*CELLS*4 + 32 = 49,188` 字节；[Packet::encode/decode](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/254033da23faf10f24a62249f40ce2ddb542645a/trillionnium/crates/trnm-pon-node/src/lib.rs) 还有 2 字节交易计数。因此零交易包为 `318+2+49,188=49,508` 字节，hex 为 `2*49,508=99,016` 字符。这是源码编码长度推导，不是假称本次运行测得了新包。空交易列表不移除 proof。

## 双端实际调用关系

1. [公开客户端](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/client_effect_packet.rs) 校验非空、独立 raw 上限和完整载荷 SHA-256；构造带 intent、grant、command_id、wire_len 的有界 JSON header；要求单独的 packet-v1 capability；依次写完整 header、完整原始 bytes，再关闭写侧发送 EOF。响应仍做原 request/identity 校验，传输错误不触发旧接口回退。能力发现和控制请求共用原绝对 deadline。

2. [真实控制 server](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/control.rs) 用同一个 BufReader 接住 header 和可能已合并到缓冲区中的 body。[packet admission](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/control_packet.rs) 在分配 body 之前检查长度并取得两份容量许可之一；read_exact 完整读取，额外读取一字节必须得到 EOF，随后核对完整 bytes 的摘要及 execution 状态。许可由 Arc 跟随 packet 和实际 provider worker，不能因为控制 future 结束就提前释放。

3. [状态分派](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/state_control.rs) 检查 admission packet 与 header 长度一致，继续原 readiness/fencing 检查，要求支持 packet-v1 的普通 host，然后调用 [execute_packet_v1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/automation_effect_host_packet.rs)。该 host 要求 PoN adapter、PQ owner 和 ML-DSA-65 FinalUse profile。它进入既有 execute_wire / execute_authorized_taskflow_effect，保留 subject、destination、scope、载荷摘要、TaskFlow fence、授权 owner、nonce、durable attempt 和 terminal receipt 路径；旧 inline 分支仍执行旧 24 KiB 校验。

4. PoN adapter 的新 packet dispatch 把同一完整 bytes 交给原 command 构造器，操作为 `submit`，参数含 `--packet-stdin`、实际 state backend 和既有 `--development`。[子进程 runner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/automation_effect_host_pon_process.rs) write_all 原 bytes、shutdown 并 drop stdin，使 Chain 得到 EOF。provider 使用原 execution deadline 与自身 timeout 的较早者；进入子进程后的超时、取消或输出不完整仍是 Unknown，并只承诺有界的直接子进程清理，不能推出任意后代保证。

5. [固定 Chain CLI](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/254033da23faf10f24a62249f40ce2ddb542645a/trillionnium/crates/trnm-pon-node/src/main.rs) 的 packet_input 要求 file 或 stdin 二选一；stdin 实际读取原 bytes，限制 1 MiB。submit 分支真实调用 Packet::decode、node.admit、node.activate_observed，并返回 block/state JSON。backend 选择真实分流到 `legacy-v2` 或 `authenticated-v1` 的 Node 打开方式。此处核验的是本地 native CLI 入口，不把另一个网络 push 的 hex 路由算作同一路径。

6. [Packet 解码](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/254033da23faf10f24a62249f40ce2ddb542645a/trillionnium/crates/trnm-pon-node/src/lib.rs) 要求完整 header、交易数和逐项长度，并要求剩余 proof 精确等于 PROOF_BYTES；不会为满足 Hepta 旧帧而拆包或剥除 proof。

这条读取范围足以证明两端 source contract 相接；没有重新审计整个 Chain 共识、存储、密码学和所有生产路径。另行取回的 `trnm-protocol/src/pq_frame.rs` 是 TPQ1 研究预检模块，已标记为本调用路径外，不能将其较大研究帧上限替代 packet-v1 的 64 KiB 门。

## 配对测试已写到什么程度，以及仍缺什么

[固定配对测试](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/09de43ba008ad594b31551cdaa928c77da17597a/codex-rs/hepta-agentd/src/automation_effect_host_pq_packet_chain_tests.rs) 明确带有 `#[ignore = "requires exact Chain release binary; selected by paired native CI"]`。源码循环两个 backend，通过真实控制 socket / 公共 client 使用真实 Chain make 输出。断言涵盖同包旧 inline 拒绝、无效 PQ 签名不消耗 nonce、实际 provider 前后观察、完整 wire 写入 durable attempt、一次 nonce 消耗、关闭 SQLx pool 并释放 owner 后重开，以及移走 provider namespace、关闭信任服务后的 exact historical receipt readback。

这些是已存在的可执行测试源码，不能据此声称测试已经通过。HEPTA_PON_CHAIN_SOURCE 只是格式检查为 40 位十六进制并记录；fixture 对实际 executable bytes 做 SHA-256，不等于证明该 binary 确由宣称的 source 构建。本次没有取得该固定配对的完整原始构建来源和执行回执。

fixture 自己也明确记录 `readiness_fixture_only=true`、`app_server_launched=false`、`evidence_startup_executed=false`、`chain_task_profile_is_pq=false`、`independent_trust_deployment_qualified=false`、`production_activation=false`。PoN command 的既有 development 模式及测试的 legacy task/model profile 不能据包传输成功升级为生产 PQ task、完整 release root、独立 trust custody 或真实 AppServer/Evidence consumer 接受。

在本次有限读取的源码和说明中，没有提取到可据以直接读取该精确配对原始结果的 GitHub run/artifact 标识。没有轮询整个外部仓库的 CI，也没有新触发执行。

## 对后续工作的直接影响

应把 packet-v1 从“仅设想”更新为“已实现、待固定配对独立接受”。下一个验收材料应由既有原生执行链提供：绑定 Hepta 09、Chain 254、锁文件、toolchain、测试 executable 和实际 Chain binary 的完整来源；保留两个 backend 的原始输出、失败与成功尝试、完整包和 receipt/nonce/rollback 物理观测。该组件验收与真实 AppServer/Evidence 启动、Root/Current→FinalUse、独立持久 frontier/owner、生产 trust custody 等接受项分别登记，不用组件结果覆盖后者。

## 证据完整性和本次实际验证范围

17 个完整选定源对象共 1,036,049 字节；逐件 UTF-8 Git blob SHA 与固定 path leaf 相等。完整原始工具返回对象以 JSON 无损序列化，共 27 份返回/错误记录，10,286,016 字节，再按次序切为 11 份 UTF-8 分片。分片是序列化后的 MCP 返回对象，不是 HTTP wire；第一次 tree 传输错误只保留了准确失败文本记录，已单独标明。重组总 SHA-256 为 `69b65a81f61d8b6a41a7f0ad7efb3711019b2fe5a51b6c2f4c2421d7c520ffc8`。

`SOURCE_BINDINGS.json` 给出全部 fixed source/path/size/hash 和原包分片；`VERIFICATION.code-mode.json` 记录实际运行的离线身份、tree 重算、源码定位及 hash 向量。源码定位不属于行为测试。两个定位辅助脚本的拼写/后缀错误和纠正一并记录，均未涉及产品执行。

人工阅读覆盖完整小型传输模块和大文件中上述相关函数、常量、解码器、测试段；“完整保存源码”不等于宣称人工逐行审完所有大文件。本次未编译、未运行 rustfmt、未执行配对 native、未授予生产接受，也没有生成未运行的 portable verifier。执行器不可用期间的新包直接通过 immutable Git create + full GET 封存；没有声称新文件已经写入本地。Git refs 仍由根代理统一发表。
