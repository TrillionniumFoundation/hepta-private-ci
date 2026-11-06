# r26 runtime 域名策略 fixture 修复候选

基线固定为 source51 e28b0f385ee882f842911044958b2810f62f6379 / tree 763c8d2b4089f6e9806c3bbb68fa247bc2f6af36。候选只改 codex-rs/network-proxy/src/runtime.rs 内四个测试的初始 config；没有修改 canonical/native 源码，没有运行 Rust 或网络探针。

## 实际失败与限界

原 r26 两项 wildcard 用例均在 api.openai.com 的 Allowed 断言得到 Blocked(NotAllowedLocal)。固定源码先执行 deny，然后执行 DNS／local-address guard，最后判断 allowlist；该输入既非 localhost，也非 IP 字面量。因此可把失败定位到 allowlist 之前的 DNS/IP 检查路径。原失败块没有记录 DNS 答案、错误或超时事件，不能从约五秒总耗时指定其中任何一个原因。

同模块另两项命名主机策略／名单更新用例在本轮分别 PASS 0.116s 与 PASS 0.008s；它们具有相同外部解析前置。本候选一起修正这两项前置，不把它们写成已失败。

## 精确改动

四个独立 fixture 的第一个 config 显式使用现有 allow_local_binding=true，仅让被测域名 pattern／名单更新语义独立于环境 DNS。所有原 host、port、deny、apex、计数、断言和超时都保留。原共享 helper 与生产默认 false 不改。

host_blocked_requires_allowlist_match 内独立 enabled/broker/default-config 循环逐字保留。localhost、private/scoped literals、deny 优先、受管 local-binding 限制、真实 .invalid 拒绝，以及四个注入 lookup 的 timeout/error/private/public 边界测试均逐字保留；没有全局启用 local binding。

FIXTURE-ORACLES.json 保存四份完整原函数与原断言、实际 r26 结果，以及同模块未改 guard 测试清单。repair-audit.json 分开列出原观察、源码推导与仍未知的具体 resolver 原因。

## 范围与交接

runtime.rs 是既有仓库文件，但此前不在相对 framework 的194路径清单中。若采用这个单叶候选，清单应变为195路径＝181 Rust＋14其他；source51原194行保持，26 owner／27 CI选择项不变，无依赖或锁变更。具体新 commit/tree 仍为 null，由 root 后续固定。

repair.patch、source-manifest.json、edit-operations.json 与 source-input-pins.json 可独立核原文、四处配置替换及整文件逆变换。当前只具备静态候选，原 r26 仍 FAIL；需新身份下原完整项目门和后续默认工作区门实际验证。
