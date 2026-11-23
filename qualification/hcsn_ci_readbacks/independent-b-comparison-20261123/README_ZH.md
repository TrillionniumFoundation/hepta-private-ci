# B 完成数据中的比较摘要

对照代码来自 `3b1387335f57a67ae9f5878064feb26a1601d715`。其中 Agentd 的 10 条 unused 诊断有一条针对 `OriginalRootIndependentBEvaluationReadbackV1::comparison_digest`。这个 crate 内部方法把已完成数据里的字符串解析为非零、规范编码的 `Digest32`。实际客户端在 `original_training` 里对原对象做同样的解析，并在错误时返回同一个 `OwnerUnavailable`。同一段逻辑处理完成请求和只读回查。检查 1,664 个 Agentd Rust 源文件，没有找到该旧投影的方法调用或关联函数调用。类型在 lib.rs 仅作 crate 内部重导出。

补丁将这个纯数据投影移至实际输入 `CompletedData`，作用域收窄到模块。在原位置检查 `data.comparison_digest()?`，随后才解析计划和执行摘要、验证范围和记录结果。将新方法体代回其唯一调用位置，剔除旧文件中的未用投影，两个 Rust 文件其余字节完全相同。数据格式、错误转换、检查次数、返回次序、拒绝标志、时钟及连接检查都在此次逐字比较范围内。其他九条涉及历史接收者资料及截止时间、保留的到期检查、持久拒绝臂、模型读取、通道绑定、一次性接受或流构造。原源码合同明确要求在构造历史 proof 之前以 retained acceptance 比较工作到期时间。此补丁只涉及比较摘要。

| 复验对象 | 结果 |
| --- | --- |
| 原文件 Git blob | `801d8663b2a110fd4ec959d5bf08b7aa3911b918` |
| 候选文件 Git blob | `84b3342da917dfade86fcf5b73f1f5f358eda113` |
| 原有接受、保管、发布数据和调用路径四套源码测试 | 两侧各 11/11，测试名完全相同 |
| 独立还原程序的负控 | 改错输入字段、改错错误类别、跳过调用、调换验证顺序均被拒绝 |
| 直接调用原客户端完成或回查的具名 Rust 测试 | 现有用例文本中未找到；相关的 7 条原有接受与发布数据测试属于邻近组件 |

`source-replay.zip` 包含两个完整 Rust 源文件、原协议文件和八份原测试日志。`subject-blobs.json` 列出固定提交的 19 个 Git blob。`candidate.patch` 可通过 `git apply --check` 校验。`verify.py` 只使用 Python 标准库。

```sh
python3 verify.py
python3 verify.py --source /absolute/path/to/checkout-at-3b138733
```

如需重跑原源码测试，可在原工作树和仅应用 `candidate.patch` 的独立工作树各执行以下命令。原测试包含删去必需调用、移除校验、注释化保护、引入未登记调用等反例。

```sh
for suite in acceptance custody publication_data routes
do
    python3 -m unittest discover -s qa/b4-no-bypass -p "test_original_b_${suite}_source_closure.py" -v
done
```

合并运行以 `e75dbc89ae4c2677e0c96874a279446cb6a7d118` 为产品源码，包括另外两项数据参数修复。两侧 50 个具名原生测试中含这里建议的 7 个接受与发布数据用例。此目录封存的是源码等价性和 11 对原源码用例。合并运行的编译器退出值、原生二进制和执行结果由该作业单独记录。[组合源码](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e75dbc89ae4c2677e0c96874a279446cb6a7d118) · [原严格构建及原生测试](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45163733463)
