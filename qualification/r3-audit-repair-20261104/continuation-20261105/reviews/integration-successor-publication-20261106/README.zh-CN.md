# 两次整合源码后继发布与审计准备快照：追加原件包

本包保全已经完成的两次正常 PR 源码发布及指定准备阶段原件，限定为原件身份、实际 API 关系与全树组合的离线验证。没有执行 Rust、Cargo、Bazel、真实 socket、原生测试或 CI，没有改 ref/PR。它不包含最终 C4 报告、最终台账/index/config/审计发布 plan，不构成这些尚在准备的对象的最终验收。

## 两次实际发布

1. arg0 fixture 前置构建修补：PR4936 的实际 source `aaf86881da0b3a7651b4a6a56be49515b9aa9f2e`，parent `ac18b623c7a6cb953b4660979e9b620fe7176bb2`，tree `66552bda88637403f4f1d72a5be8592e07a8a308`。实际 merge `8ca7a5b30bf6abfaf3ad7bb538d00f505d0847f8` 的 ordered parents 为 `[63652be658ebed8d3052eb789b951793384fd5e4, aaf86881da0b3a7651b4a6a56be49515b9aa9f2e]`，同树。原出版核验切点为09:28:34 UTC。
2. PTY 观察和 Supervisor 连接阶段上限：先创建 `875b774885c002bbe157fd2919fcb590ee1e0131` / tree `c24f6910e0af5a3ebf809c29f1fb06dafbd94146`，parent aaf；再创建 `840e8b5dbffca017753cdf87482ce325938f313c` / tree `b38cc55050c74f8765bdee397a24066c100a179a`，parent875。实际 merge `e0993cb056c30ae4b694f5c0a187759f0edeefe1` 的 ordered parents 为 `[63652be658ebed8d3052eb789b951793384fd5e4, 840e8b5dbffca017753cdf87482ce325938f313c]`，同树。原出版核验切点为09:50:07 UTC。

包内含两组完整 commit/ref/PR/merge 工具原返回及正文 plan、原出版核验。离线 verifier 逐项核对原 API 记录中的身份、父关系、目标 base、ref 的前后值、PR 正文精确相等及旧正文后缀保留；不是新一次 GitHub 状态查询，也没有重新执行签名密码学验证。

## 六路径组合与限定范围

从原完整 aaf 全树到中间 PTY 全树，恰改原 PTY 的三路径；随后恰改 Supervisor 的三路径，一旧叶修改、两新叶增加。最终10,804叶，10,798个 aaf 原叶不变；完整 paired process 测试仍是 `c03bdba974ea48281cd839b9161eb0ccdc38b892`。两个实际根 API 的全部53个根项也按重新计算的目录树核对。arg0 的3个发布前像还原至 ac18/c3e9，全树身份一致。

仅复制两个必要的 B21 全树输入用于独立树重算；没有重复 B21 的23件作者包或 Supervisor 的77件作者包，也没有运行它们的外部 verifier。三份实际独审正文保存在出版工具返回中并核对既有 blob：arg0 `cd7ed2f2a033882671a24258e1d360863039e5d0`、B21 `4f14ab769aa1d95a4e46249f345323beaeeaf68c`、Supervisor `35b07140231fa056026ca00088930873a4812b55`。这不把三个静态审阅转成原生资格。

## 完整保留的原件和失败历史

`ORIGINALS-MANIFEST.json` 固定74个输入、12,875,033 B：arg0 publication21件、PTY/Supervisor publication31件、两份根脚本快照、third-post-audit-inputs当时已存在的12件、4份arg0完整登记工具回执，以及4个必要全树/既有登记表依赖。

根 `prepare_third_post_audit_delta.py` 仅保留明确指定的28,382 B / Git `170ed6f6b22184a9e8fe759342c2942e1e6690eb` 快照；早期 before_alias_adapter 和 before_self_adapter 均完整保存。ready01/02 和 validation01..04、C3 Merkle 原件只代表当时的有界准备阶段，不是最终 C4 配置、最终审阅或最新工作状态。本包不会执行根 preparer，也不会宣称重新检查了其全部外部输入。

组合首次把 leaf-only 输入当成完整目录树的实际失败，以及修正 adapter 后的成功执行原件，均完整保留，没有把失败重写成成功。

arg0 原 registry `08e8e7ea26909d95392a0eddc157f75e308e2e9c` 当时的4份 `registration-originals/batch-00..03.original.json` 在此按完整原字节无损压缩保存，总计4,776,742 B，不以摘要或后造工具返回替代。这些原 JSON 含30份完整 GET payload、4份 actual create 与4份 tree GET；离线 verifier 对30个正文合计4,716,332 B重新计算身份，并与原 registry 对应路径、actual tree 叶及实际 self GET核对。其余原件的 HTTP wire 字节不在 MCP 工具交付内，本包不声称保存 HTTP wire。

## 恢复和验证

交付目录的 `archive.json` 列完整 gzip 档案及 base64 分片身份；`MANIFEST.json` 列档案中每个成员的原 bytes/Git/SHA256。分片为无损编码，没有日志裁剪或换行归一化。

```bash
python -B verify_packet.py <delivery-directory> <new-empty-output-directory>
```

脚本核全部分片、gzip、tar 成员及 manifest，恢复到输出目录，再只运行本包 `verify_publications.py`。后者只读恢复件，核上述原件、API关系、全树和30份原 GET；不运行根 preparer、外部作者/verifier或产品工具链。冻结的首次验证 stdout 为9,321 B，恢复重放须 exit0、空stderr、与该 stdout 全字节相等。

原23项退出条件未修改；状态仍16 CLOSED_SCOPED / 6 OPEN / 1 SCIENTIFIC_HOLD。新 source 的原 CI 资格、原 Intel 失败原因、原 paired 60秒原因均不能从本包获得。所有 blocker 并未全部闭合。
