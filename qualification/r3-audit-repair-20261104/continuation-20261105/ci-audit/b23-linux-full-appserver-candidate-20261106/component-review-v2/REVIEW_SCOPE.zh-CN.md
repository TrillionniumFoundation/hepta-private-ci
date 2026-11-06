# B23 工作流外壳 v2：限定范围独审材料

状态：固定 基线67 上的非 collector 部分已形成并静态验证；collector 尚未独审接受，模板不可发表或执行。此快照之后不再改写。完整工作流的最终独审必须绑定已接受 collector 的确切字节。

## 范围

拟新增且仅新增 `.github/workflows/hepta-b23-linux-app-server-original-gate.yml`。基线为 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / tree `3982ba56dc5a3f1da0c1de7ea57992f88125c359`。拟用分支 `codex/b23-linux-app-server-original-gate-20261106`，由根代理统一创建 ref/PR。

完整目标为 `//codex-rs/app-server:app-server-unit-tests`；Ubuntu 24.04 / GNU，原 120 分钟 job、原 8 shards、默认线程和 flaky 重试不变。原 checkout、prepare、V8/脚本检查、lock 检查、cache save、clean worktree 步骤语义逐项相等。保留原 wrapper 与原 test arguments，仅加入已同意的 no-test-cache、private JSON BEP 和 JSON local URI 三个取证 flags。没有 test filter、test argument、测试 timeout、jobs、重试或 test-thread override。

运行前后 source identity 使用实际 PR merge checkout，要求 parents=[固定 基线67,event.head]；完整 HEAD tree 移除唯一新增 workflow 后必须还原 基线67 tree，原 10,582 blob leaves 不变；14 个关键输入逐字节 Git hash、工作树及新 workflow 字节另行核对。这个设计不在文件内自引用未来 commit SHA。

Bazel 与外层 tee 退出码分别保存，collector 退出单独保留。source-after 必须在 collector 前产出完所有元数据；两项 artifact 上传均由 collector 的 safe-for-upload=true 门控。raw BEP 在两个上传目录之外。最终门还要求原退出码和 tee=0、source before/after 成功、collector 成功、两个 artifact 实际上传成功，且继承前置/clean 步骤结果。它只报告独立 B23 接受仍 pending，不把 diagnostic 通过当主线 required checks 全过。

## 已实际验证

`verification-draft/static-verification.json` 记录完整 YAML parse、7 个 shell block 的 bash -n、3 个嵌入 Python 块 compile、原步骤逐项相等、原 full target 参数实参顺序、三个真实原 API ancestor tree 的重算、仅新路径的正反 Git apply、逆向恢复原树和额外原文件导致树不相等。14 原 source body 在核验后仍全部原字节。

三个 shell 用例只执行临时目录中的明确 stand-in，不调用 Bazel 或任何产品二进制：wrapper 0 / tee 0 时 final=0；wrapper 3 时 final=1；wrapper 0 / tee 1 时 final=1。为检查最终退出码文件门，fixture 故意给所有 GitHub step outcome 填 success，负例仍失败。这不构成 native、真实 source guard、AppServer target 或五个回归用例通过。真实 GitHub checkout 的 source guard 和原生运行均为 NOT_RUN。

## 独审重点

1. actual merge/base/head 绑定和 tree projection 是否会引入自 pin 失配；原所有 product leaf 与工作树约束是否正确。
2. 原 GNU 执行语义、默认 retry/threads/timeout 是否保留；仅完整目标选择和取证 flags 有明确差异。
3. wrapper/Bazel/tee/collector/upload/clean 各失败是否能被最后步骤误盖；raw/private 与两个公开目录是否分离。
4. source-after 在末端 privacy gate 之前，之后不写入未扫描公开元数据。

旧 f03 完整摘要已登记，但原 status/XML 未恢复。历史 checkpoint d0ed 保留为先前状态；这次恢复不把它改写，也未重做旧负控。

## v2 单点纠正

v1 将“基线67”的工作标签误写为 literal base.ref=main。独立审阅用已冻结 #4902 原 API 指出实际基线 ref 为 fix/r3-original-product-contracts-20261104；根确认 B23 也以这个 ref/固定67 建 Draft PR。v1 完整保留，v2 仅替换 source guard 的这一字符串。独立取回的原 API blob 为 5c213344391c4d17203af88e94f25a28c7b6e0d3，45,899 B，SHA256 2e0c5cff88604e22878745c15598f8c5734f6a77bc1525c5d0244214bdcea6df。原件保存在 source-api/base-ref-pr4902.original-tool-return.json。

source_identity.py 与完整 workflow 模板各只有一个替换 hunk；逆替换全文恢复 v1。固定 base.sha67、merge parents [67,eventhead]、全树投影3982、14源字节与工作树约束全部保留。相同静态验证已重新运行成功。collector 仍为明确占位，v2 仍不可发表或执行；真实 source guard/原生 run 仍 NOT_RUN。
