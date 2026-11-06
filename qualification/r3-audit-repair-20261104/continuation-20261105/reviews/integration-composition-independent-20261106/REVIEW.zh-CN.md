# 单一产品候选：独立组成关系审阅

**结论：ACCEPT_COMPOSITION_ONLY，组成关系阻断 0 项。** 本次独立实现 Git tree 序列化与 Merkle 重算，未调用作者的树构造函数，未执行 Cargo、Rust、原生测试、CI、patch apply 或 ref/PR 写入。

独立重算完整产品树为 **`99a9c0cefa627290c9fc72a9ba90d0485020fe11`**。基线是 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / `3982ba56dc5a3f1da0c1de7ea57992f88125c359`。全部 10,802 个叶与 1,617 个含根目录的 tree 节点均核对；230 个实际本地 postimage 共 4,148,693 B，长度、Git blob、SHA256、模式和固定来源全部一致。

| 组成 | 核验结果 |
|---|---|
| Cargo 生成产品差异 | 223 路径：3 个根文件 + 220 个新 vendor 文件；与实际 registry `5cf849cc78dd2d706aa30f5b20868f941e96b90d` 全文相等，219 个独立 blob 的完整原 GET 均重新按字节核验 |
| 七路径修复 | arg0 2、Windows 2、PTY 1、holdout 2；完整原 GET 和本地 postimage 一致；每个 donor 在 base67 上的仅指定路径投影，都重算为该 donor fresh commit API 的实际 tree |
| 两阶段组合 | Cargo-only `c7b9fb4e029dc38034a7dfce10a646ccde3e0bf6`；seven-repair `29a55e5df7c9bfefabab28efd7a3d9ee2e042947`；两组路径完全不相交，合并后得到上述 `99a9c0ce…` |
| 原叶保护 | 10 个原路径改变，10,572 个原叶完全不变；新增恰为 220 个 vendor 叶，无删除 |
| 工具与策略边界 | 4 条 proposal 工具路径均未进入基线或候选；367 条原 workflow、脚本、BUILD、`.bzl`、`deny.toml`、`.bazelrc`、`.bazelversion` 配置路径的模式和 blob 全部不变 |

220 个 vendor 文件分布为 aws-smithy-http-0.64.1：25；aws-smithy-runtime-1.16.0：65；aws-smithy-types-1.8.1：52；loom-0.7.2：78。其实际来源绑定原 run `42175704028` / artifact `13482877841`，本次没有重新作组件 native 资格判断。

本次 fresh ref GET 确认 target `integration/ui-objective-20261103-product` 为 `63652be658ebed8d3052eb789b951793384fd5e4`，默认 main 为 `732e934ba496d90fbe042b8d41d479ef901643e5`。候选明确锚定 base67；没有宣称它等于当前 main732。

拟定的有序 parents 可保持为：

1. `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`
2. `3c9e2bba4e7e84616509d6320a9ae013a274532c`
3. `18bbef4f61c6086f145bdb6f7acbf82127741a14`
4. `8075eb367b6e97546af206b27bbf4a3a867497c8`
5. `4a1410f332e4a34564feafbc4dcb2e808c7f6c5f`

这仍是 publication 计划，不能称为已观察的发布 commit。发布后由根核对实际 parents 顺序和 tree。Windows donor 的直接 parent 实为 `340fbc0629d27e3a2bda7c6971be25c60b3bf2bc`；本审阅没有误写成直接 parent67，且其完整树相对 base67 确实只包含指定两叶差异。

`seven-source-composition.json` 中的 Cargo pending 字段属于七路径组合阶段；后续 product-composition 与实际 Cargo registry 已明确补入 223 路径。这不需要改写较早阶段证明。

本结论只接受固定源码的组成关系，不代替 Cargo 正式独审、组件 native 审阅或组合后的原 CI。没有改变预算、重试、原断言或任何 blocker 状态。验证器 exit 0、stderr 空；完整输入身份、实际 API 原件、独立脚本与结果保存在同一审阅目录。
