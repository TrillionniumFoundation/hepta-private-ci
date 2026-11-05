# Core 恢复树测试：局部本地 provider 夹具候选

本候选只改变 `resume_agent_from_rollout_skips_descendants_when_parent_resume_fails` 的 provider 前提，并给原等待失败消息补 `needle` 与线程 ID。它没有执行；原 e78 并行失败继续保留。

原失败的 5 秒窗口只观察到 MCP 启动完成和 TurnStarted。固定源码证明 TurnStarted 后仍会等待启动 WebSocket 预热，而原夹具默认 provider 支持 WebSocket，连接默认预算 15 秒。原记录不足以断定这次停在预热：上下文、skills/plugins 和 hooks 等工作也在用户记录之前；相邻 401 没有绑定该线程。

该恢复树测试的合同不要求访问外部模型。新前提使用现有 Responses mock，在真实 ConfigBuilder CLI 层注册本地 HTTP provider，并断言生效的 URL 与非 WebSocket 模式。原 hello 用户输入及 ItemCompleted 等待真实执行，原 5 秒、rollout 删除、恢复根身份、子孙 NotFound 和收尾全部保持。没有全 Harness 配置修改、生产代码或依赖变化，也没有重试、忽略或串行化。

云端隔离 Git 已验证 patch 正反应用与全文身份；原 case 在 harness 构造之后的完整正文及原等待 loop/budget 字节相等。下一门由唯一 native owner 在精确整合源构建，并以原 Core 库完整默认并行范围执行一次，保存完整原件与具名结果。单例通过不能替代这个门。
