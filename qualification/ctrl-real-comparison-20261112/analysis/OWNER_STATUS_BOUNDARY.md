# 开发报告与原生 owner 决定的边界

本修复基于 `3517d1f11294d2a89750f0dcd542181743fdd7c5`。
该基线相对 d47 只新增证据；本修复涉及的代码与 d47 相同。

## 问题与修正

三个开发报告出口没有调用原生 owner，却硬编码 `decision=NoUpdate`：
`ctrl_macro_factorial.reconcile`、`ctrl_macro_analysis.analyze`，
以及直接读取 factorial REPORT 的 `summarize_ctrl_factorial.summarize`。
此外，factorial 报告嵌入的通用 cohort 结果也带有旧的同名字段。

后续生成的开发报告统一输出：

```json
{"decision": "HOLD", "owner_evaluation": "not_evaluated", "owner_decision": null}
```

factorial 外层及嵌入 cohort 的研究状态同时投影到这些字段；
通用 `macro_cohort.evaluate` 的实现、数值和类型保持不变。
summary 对旧报告的 NoUpdate、伪造的 owner_decision 和评估声明均不授予权力，
也不修改传入的原报告对象。collection analysis 无论完整或 UNKNOWN 阻断均无 owner 决定。

原生 owner 的类型、权限、root/CAS、评估标准和签发路径不在此次改动范围内。
HOLD 表示研究报告未完成 owner 评估；只有原生 owner 实际完成评估后签发的决定才是 owner 结局。

## 回归与验证边界

- 加强已有真实 reconcile→REPORT 构建测试，覆盖外层与嵌入 cohort 的状态，保留 24 个未启动记录。
- 新增真实 REPORT→实际 summary 回归，检查旧标签/伪 owner 字段不升级权力，算术审计一致且原对象不变。
- 加强 collection analysis 的现有完整原件与 UNKNOWN 分母用例，保留实际指标和原件不变检查。
- CTRL workflow 的 factorial 最低计数从 10 加到 11；collection analysis 仍为原 5 项。
- 同一 workflow 单独运行直接 summary 的原有 3 项完整/不完整/动作归因回归，显式 PYTHONPATH 与 minimum=3，保留独立结果。
- 目标相关套件为 factorial 11 + collection analysis 5 + summary 3，共 19 项；这是预期数量，不是已执行结果。
- 直接 summary 的源码与测试两个精确路径触发 CI，格式门只增加实际改动的 summary 源文件。
- 本次仅进行源码阅读和静态差异核对。环境断连，Python 测试与格式化均未运行，不报告通过。

当前 campaign 冻结在 `3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd`，未被修改。
运行请求、idempotency key、freeze/source pins、原 REPORT 和 COLLECTION_ANALYSIS 字节均保持原状。
原报告中的旧 NoUpdate 标签没有原生 owner 授权证明；本修复不会回写历史或借字段更名认证研究收益。
