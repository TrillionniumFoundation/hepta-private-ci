# r8c 七项 wiremock 失败的独立只读复核

七项原失败的请求计数已经逐块核验；没有将它们重新归入明确 helper 缺失组。原分类、216 项不通过总数及测试断言保持不变。

| 原测试 | 期望 / 实际匹配 | 来源与范围 |
| --- | --- | --- |
| `hooks_mcp::mcp_tool_hook_blocks_model_tool_without_recursive_hooks_or_approval` | 2 / 0 | [原块 1](blocks/case-01.log)；test_stdio_server 前置条件已由 stage 36 接线，个案尚待原 Core 重验。 |
| `hooks_mcp::pre_tool_use_blocks_mcp_tool_before_execution_with_non_prefixed_names` | 2 / 0 | [原块 2](blocks/case-02.log)；test_stdio_server 前置条件已由 stage 36 接线，个案尚待原 Core 重验。 |
| `hooks_mcp::pre_tool_use_blocks_mcp_tool_before_execution_with_legacy_prefixed_names` | 2 / 0 | [原块 3](blocks/case-03.log)；test_stdio_server 前置条件已由 stage 36 接线，个案尚待原 Core 重验。 |
| `search_tool::tool_search_indexes_only_enabled_non_app_mcp_tools` | 2 / 0 | [原块 4](blocks/case-04.log)；test_stdio_server 前置条件已由 stage 36 接线，个案尚待原 Core 重验。 |
| `search_tool::tool_search_surfaced_mcp_tool_errors_are_returned_to_model` | 3 / 0 | [原块 5](blocks/case-05.log)；test_stdio_server 前置条件已由 stage 36 接线，个案尚待原 Core 重验。 |
| `search_tool::tool_search_uses_non_app_mcp_server_instructions_as_namespace_description` | 2 / 0 | [原块 6](blocks/case-06.log)；test_stdio_server 前置条件已由 stage 36 接线，个案尚待原 Core 重验。 |
| `skills_extension::explicit_only_orchestrator_skill_is_hidden_but_can_be_invoked` | 4 / 2 | [原块 7](blocks/case-07.log)；codex-code-mode-host 前置条件已由 stage 36 接线，个案尚待原 Core 重验。 |

七项使用的期望均是 `POST .*/responses$`，fixture 配置指向 `/v1/responses`。前六个块明确记录没有任何入站请求，因此其实际观察路径为空；不能把源码配置的路径说成已收到的请求。第七例确实收到两次 `/v1/responses`、六次 MCP 请求、三次 suggested-plugin 请求和一次 skill analytics 请求。

前六例先挂载精确 SSE 计数，再调用可返回错误的 stdio helper 解析，之后才 build 和 submit。锁定版本的 `MockServer::drop` 会验证期望并在普通返回时 panic，因此原 `Result` 错误可能被计数失败遮住。这个机制由原源确认，但日志没有保留被遮蔽的错误，仍不能宣称六例的实际原因已经确定。

第七例已经完成首轮两次模型请求。第二轮 submit 前会解析 resource-access、skills.read 以及 Code Mode 输出；真实 Code Mode host 是其明确前置条件。原块没有打印这些输出或原返回错误，不能据此认定 fallback 是唯一原因，也不能排除第二轮提交边界。

Stage 32 的七个 provider fixture、stage 33 的两个 compact 原始循环、stage 37 的 WebSocket 分组均没有直接改动这七项。现有通用 submit_turn 已等待原 finish owner，不能把 compact 的补丁泛化为本组的修复证据。Stage 36 解决所需真实 helper 的注册前提，runner 的独立通过不等于七例已通过。

**本次没有发现足以支持新增行为补丁的已证明 fixture 缺口。** 保留全部计数与时间边界，等待原 Core 门逐 ID 的真实结果；若仍失败，再在原 fallible 边界保留具体错误上下文。详细源码 pins、行号、请求路径、候选范围和原块 SHA 见 [机器审计](INDEPENDENT-WIREMOCK-REVIEW.json)。
