# 已有回归终端原件保全

本目录只保留先前已完成的 6 项 stdlib 回归证据，没有重新运行测试、诊断、verifier 或模型。

- PTY_LAUNCH_REQUEST.json：从本对话保留的原启动工具参数转存。
- PTY_LAUNCH_RESPONSE.json：本对话中原启动响应 text 内容逐字转存；不声称它是 HTTP/MCP 原始传输帧。
- PTY_READ_RESPONSE.json：对同一已退出 durable PTY 的只读 archive 再观察，包含原输出 bytes_hex、text、chunk SHA 和 terminal status。
- PTY_READ_TOOL_ENVELOPE.json：上述本次只读工具响应 envelope。
- stdout.log：完整 1,120 字节输出，保留原 CRLF；SHA256 6db514bbbb4aa53a1340934d731094dab4adec2ece6e670e3bdbe2c63be8bb86，与此前已观察输出一致。
- TERMINAL_OBSERVATION.json：从只读响应派生的会话和退出状态，明确区别于启动状态。

会话 dpty-50779e2a569032996365645cfabeb533766b71e462011d96459de82d42fa488b。
原启动 PID 95315，owner PID 95314；本次观察仍为 exited、exit_code=0、output_complete=true、capture_error=null。
原 REGRESSION.json、源码、manifest、diff 以及已封存实验原件均未修改。
