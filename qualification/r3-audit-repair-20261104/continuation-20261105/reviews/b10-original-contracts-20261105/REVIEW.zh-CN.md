# B10：14 个冻结 Core integration 合同独立核验

## 结论

**建议将原 B10 合同范围裁为 CLOSED_SCOPED，由 root 最终决定；本审查不修改账本。** 原出口逐字保留：

> 原连接数、请求数、工具/模型/工作区断言通过；身份变化的拒绝和重连边界保留。

冻结的 14 名由 **10 个旧故障名、3 个原 turn-state 回归及1个新增真实重连控制**组成。它们在 GNU e78 的完整 stdout/JUnit 中各有真实 PASS，在 Windows 5b 的原 core-all-test 完整日志中各有最终 ok。Windows 有3名随 shard13 额外执行一次，首试与最终均ok；不是本14失败后重试转绿。两项原身份单元控制另列，GNU各1case PASS，未加进14名计数。

本结论不要求原出口没有写入的一律五平台门，也不把 GNU/Windows 资格写成 macOS、真实 musl、Wine或eed新head已通过。原48分平台故障索引保留；原GNU项目整体5FAIL和Windows目标整体6/21 attempts失败也保留。

## 实际原件与源绑定

- GNU：原 `just test --locked --cargo-profile dev-small --no-tests fail --retries 0 --success-output immediate -p codex-core -p codex-linux-sandbox`，source tree `e78c819b8b1f435f8b37bea17b4ffdc724961aa2`。完整11,059,831B stdout与839,106B JUnit按旧固定SHA重开；逐名块包含running1/1passed/0ignored，JUnit无failure/error/skipped/flaky/rerun节点。原整体3962PASS/5FAIL、exit100没有改写。
- Windows：run `41999114842` / attempt1 / job `127339256056` / artifact `13430354553`。原job实际checkout merge `9063c52a063b6f26c48e9418f6d8dbd14e9e06ff`，Git API亲读其父为base63652与head5b，tree精确为 `b26598d0d97d8d51e723bb5582137315f2174d35`。完整ZIP45成员CRC/hash均核，collector42份log/XML全部原bytes重开。
- 完整5b/e78/eed叶表分别独立重算Git Merkle树，全部等原tree；本审查的18份当前源码逐blob三者相等。完整5b→e78仅2路径、5b→eed14路径差异另表保留；不宣称整树相等、不转借程序hash，也不把Windows工作树CRLF说成Git LF字节相等。

## 14 名与合同

| 名字（完整 suite 前缀见JSON） | GNU秒 | Windows | 已核断言 |
|---|---:|---|---|
| `agent_websocket::websocket_model_switch_to_responses_lite_omits_top_level_tools` | 0.268 | 1次ok | 1 handshake / 3 requests (prewarm, non-lite turn, lite turn). 模型 gpt-5.2→gpt-5.4；Node REPL 审核/禁用元数据逐请求改变；非 lite tools 非空；lite 无 top-level tools/instructions/previous_response_id，首 input 为非空 additional_tools。 |
| `agent_websocket::websocket_v2_first_turn_drops_fast_tier_after_startup_prewarm` | 0.162 | 2次ok（含首attempt） | 1 handshake / 2 requests; prewarm generate=false. 预热 priority，首真实 turn service_tier 缺省；response.create、非空 input、previous_response_id 缺省均实际断言。 |
| `agent_websocket::websocket_v2_first_turn_uses_updated_fast_tier_after_startup_prewarm` | 0.173 | 1次ok | 1 handshake / 2 requests; prewarm generate=false. 预热无 tier，首真实 turn priority；response.create、非空 input、previous_response_id 缺省均实际断言。 |
| `agent_websocket::websocket_v2_next_turn_uses_updated_service_tier` | 0.263 | 1次ok | 1 handshake / 3 requests; prewarm then two complete turns. 预热无 tier→第一 turn priority→第二 turn 无 tier；两个真实请求均有非空 input 且无 previous_response_id。 |
| `compact::remote_v2_compaction_keeps_creation_time_instructions_after_same_path_mutation` | 0.752 | 2次ok（含首attempt） | 3 HTTP requests before cold resume, then exactly 4 total. 同一 AGENTS 路径真实改写；运行时三请求保旧 instructions；compact trigger 精确；冷恢复保完整 durable replacement history、provider-visible 全顺序前缀及新 instructions 替换片段；源文件确有新文本且 source URI 不变。未将 durable 私有 metadata 重新泄露到 wire。 |
| `compact_remote::remote_compact_v2_reuses_compaction_trigger_for_followups` | 0.756 | 1次ok | Five response batches; code inspects request[3] as compaction and last request as follow-up. It does not contain a separate exact total-length assertion. 真实父/子/后代消息和手动 compact；before 无 replacement、after 有 replacement；原用户/委派消息 creation time 完全保持，后续时间>0；wire 全无私有 metadata；compact header/window/phase/strategy 精确；保留委派与后代 ciphertext、用户图像邻接notice，去掉进度/完成与未许可notice；summary/trigger 内容按阶段检查。 |
| `compact_remote::remote_mid_turn_compact_v2_sends_turn_state_over_websocket` | 3.591 | 1次ok | single_connection() enforces one physical connection; exactly 5 requests; first generate=false. 请求2为 compaction_trigger；状态精确 [null,null,sampling-state,sampling-state,sampling-state]，后来的 compact/continuation metadata 不能覆盖首状态；真实工具调用前后进入同一 turn。 |
| `git_enrichment::ephemeral_system_thread_prewarm_skips_and_turn_observes_fresh_state::test_case_1_system_background_thread` | 1.392 | 1次ok | Real initial prewarm and a second connection for ephemeral thread; inspect second-connection request[2]. No extra total-handshake assertion invented. system 与 ambient_background 两实例；两个实际 prewarm 均等待，ephemeral prewarm 无 workspace；真实创建 git repo/commit/remote 后新增脏文件；follow-up root-turn 无错误父绑定，workspace 精确 cwd→origin/HEAD/has_changes=true。 |
| `git_enrichment::ephemeral_system_thread_prewarm_skips_and_turn_observes_fresh_state::test_case_2_ambient_background_thread` | 1.403 | 1次ok | Real initial prewarm and a second connection for ephemeral thread; inspect second-connection request[2]. No extra total-handshake assertion invented. system 与 ambient_background 两实例；两个实际 prewarm 均等待，ephemeral prewarm 无 workspace；真实创建 git repo/commit/remote 后新增脏文件；follow-up root-turn 无错误父绑定，workspace 精确 cwd→origin/HEAD/has_changes=true。 |
| `git_enrichment::startup_prewarm_skips_git_enrichment_and_user_turn_observes_fresh_state` | 5.381 | 2次ok（含首attempt） | Startup prewarm observed before mutation; inspect same-connection follow-up request[2]. 预热无 workspace；真实 git repo/commit/remote 与后续脏文件；启动前权限配置保持到后续 turn，避免 submit_turn 偷改 Disabled；匹配实际 turn_id 完成后，workspace 完整值为新状态。 |
| `turn_state::responses_turn_state_persists_within_turn_and_resets_after` | 0.525 | 1次ok | Exactly 3 HTTP requests. 响应先给 ts-1；请求状态精确 [None,ts-1,None]；同 turn 两请求的 turn_id 相等，下一 turn 不等。此用例有真实 echo 调用但未直接断言其 stdout；不冒充 stable 用例的两工具输出控制。 |
| `turn_state::websocket_turn_state_persists_within_turn_and_resets_after` | 0.502 | 1次ok | 1 handshake / 4 requests = 1 prewarm + 3 turn requests, under fixed Disabled permissions. 状态 [null,null,ts-1,null]；request_kind 为 prewarm+3turn，generate 仅首个 false；同 turn ID 保持、下 turn ID 改变；同权限连接复用与权限变化隔离分为两个真实场景。 |
| `turn_state::websocket_turn_state_is_stable_within_turn` | 0.610 | 1次ok | 1 handshake / 4 requests = 1 real tool-free prewarm + all 3 real turn requests. Intentional correction from the historical wrong total 3. 后三请求原 [null,ts-1,ts-1] 保持，拒绝后来的 ts-2 覆盖；generate/request_kind/同 turn ID/固定 sandbox 均检查；ws-shell-1 与 ws-shell-2 的真实 function_call_output 必须 exit0，stdout 分别 one 与 two。 |
| `turn_state::websocket_turn_state_survives_permission_change_by_reconnecting` | 0.548 | 1次ok | Exactly 2 physical handshakes and connection request counts [1,3], exactly 4 total. 先读真实 read-only prewarm，再改 Disabled；首 socket script 耗尽仍不关闭，第二 socket 由生产身份变化触发；原权限向量 [read-only,full,full,full]、状态、request_kind、同/跨 turn ID 保持；真实工具输出 exit0/websocket。该新增控制不伪称旧定义。 |

## 合法修正原错误 oracle，不能写全部断言不变

`websocket_turn_state_is_stable_within_turn` 旧cafb源码246行把总请求期望为3。已接受的7744前格式源码294行、当前8c20源码296行将其修正为4：**1份真实无工具prewarm +3份完整turn请求**。后三请求原 `[null, ts-1, ts-1]` 语义保留，后来ts-2仍不得覆盖；新增断言还要求ws-shell-1/2真实输出exit0及one/two，generate/request_kind和同turn_id匹配。旧脚本会把首工具响应消耗在prewarm，这个修正恢复完整业务动作，没有通过少执行工具来绿。

原read-only→full×3权限向量与一连接要求冲突。同权限复用场景仍精确1连接/4请求；原权限变化向量移入新增重连场景，要求2连接且请求数 `[1,3]`。测试服务器首socket脚本耗尽后保持读取、不会主动close，GNU原日志实际记录connection0的request0与connection1的request0/1/2。因此第二连接不是serverEOF强制得到。

## 身份拒绝与恢复指纹

固定client_tests的两项现有unit分别实际PASS 0.011s/0.013s。第一项对sandbox、parent/fork/thread source、review、Memory request kind、extra metadata、beta及四类provider字段作严格assert_ne，保留身份隔离；第二项对五类动态字段同时要求连接身份可复用、真实wire摘要改变、完整cold-recovery指纹改变。固定client.rs在身份不等时先清旧request/response状态再开新连接。两unit的数据反例与上述实际双socket控制一起支持原出口，不把它们说成新的guard-removal运行。

## 早退、缓存、重试及预算

14名的13个函数定义没有ignore或平台cfg排除，现有提前成功路径是 `skip_if_no_network!(Ok(()))`。GNU完整success输出中没有该marker，WS名还含实际请求记录。Windows成功stdout由libtest捕获，所以仅看ok不能证明没早退：本审查另按官方Bazel9.3 `spawn.proto` blob19f68f22完整解析原30,370,252B compact日志至末尾89,920条entry，提取21个真实tw.exe测试action与21个XML生成action。真实action均local、cache_hit=false、timeout900000ms，env均无网络禁用键；固定defs/BAT launcher没有补入该键。XML每份只有一个外层wrapper testcase，其system-out与对应完整test.log bytes相等，14名来自真实libtest正文，未伪造14个XML节点。

预算原样：Bazel原long/16shards/flaky；本14涉及3名的额外shard13 attempt逐条保存。GNU命令retries0，原nextest配置保留。共享提交助手为匹配turn_id的逐事件30秒等待，普通wait助手逐事件至少10秒；WebSocket request waiter本身无内层timeout，原git用例另包5秒prewarm。startup/ephemeral的原5000/1000ms同步工具与30秒TurnComplete不改；没有新执行命令或放宽预算。

## 可复核材料与保留边界

- [独立结论与原出口](independent-review.json)、[14项完整合同及实际结果](fourteen-contracts.json)、[逐名原件投影](case-result-projection.json)。
- [完整源桥与Merkle核验](complete-source-bridge.json)、[Windows实际action环境/缓存/预算](windows-original-test-action-projection.json)、[XML/原日志逐字一致](windows-XML-original-log-consistency.json)。
- [原完整GNU传输索引](upstream-complete-originals/GNU-full-originals-existing-actual-Git-map.json)与[原完整Windows传输索引](upstream-complete-originals/Windows-full-originals-existing-transport-manifest.json)保留原70/85分片身份；新包不重复上传其多MB原件。派生GNU XML节点明确标为serialization，原完整JUnit仍在既有无损归档。
- [执行日志完整解码与官方schema来源](execution-log-decode-and-primary-provenance.json) 保留原ZIP压缩成员→完整compact→42个原frame的长度/hash/偏移；GitHub原response全文与固定proto字节相等，原job还明确Bazel9.3.0。
- [解析器纠正记录](evidence-parser-correction.json)：初版错误预期只有21个TestRunner mnemonic，实际还包括21个xml.exe；现全部保留并按原argv分型。这是证据处理假设纠正，没有运行或重跑任何产品测试。

当前报告仅建议原B10合同scoped闭合。其他平台未读结果、新eed整头、B15/整仓质量和所有非B10失败继续各自保留，最终账本由root裁定。

## 无损归档与复核

完整逐例材料、18份固定源、3份完整叶表、原21对Windows log/XML及42个action frame由 `delivery/transport-manifest.json` 指向的gzip/base64分片保存。`delivery/verify_bundle.py.source.txt` 仅解码证据，并逐成员核长度、SHA256与Git内容ID；不启动产品、测试、Cargo或CI。原多MB全日志和ZIP由上面的既有GNU/Windows传输索引完整保留，未重复上传。原件的计算Git内容ID不是独立上传状态；可达性以实际传输分片及publication map为准。
