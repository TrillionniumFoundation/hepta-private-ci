# 冻结基线与教师结果评价

本目录不读取新教师提示词或旧留出文本，不训练模型，也不修改候选。原始模型与源代码通过已发布的 V6 freeze 及选中 V5 manifest 验证。只有新留出集的三个输入字段送入基线子进程；标签只由评价器读取。

## 三条原基线

```bash
python3 run_baselines.py \
  --v6-root /path/to/hepta-cell-v6/qualification/memory-cell-v6 \
  --held /path/to/semantic_v7/holdout \
  --output /path/to/new-baseline-results
```

`--python` 可以指定已具备原依赖的 Python。V6 和确定性对照使用原 `native_router.py`，只依赖标准库；V5 使用原 `serve.py --v5-model`，依赖 NumPy、SciPy、scikit-learn。V5 原 loader 直接验证并读取原 `.part001`，无需改写或重组。没有自动安装、训练或重试。

输出保留各路 stdout、stderr、命令、逐行评价和前后冻结指纹。退出码 0 只说明三路评价流完整有效，不代表它们都通过语义门；语义门在每个 REPORT 和 SUMMARY 的 `gate_pass` / `all_gates_pass` 中明确记录。未知结果会使本次调用返回 1。

## 教师结果

```bash
python3 score_teacher.py \
  --held /path/to/semantic_v7/holdout \
  --results /path/to/teacher-run/results.jsonl \
  --output /path/to/new-teacher-evaluation
```

教师结果可以乱序，但必须以唯一 `index`、请求指纹和唯一原 `operation_id` 绑定。教师 canonical 由 parent 提供确切规范，和 held 自己的 canonical 分开核验；两者都不把输入 JSONL 的末尾换行计入请求指纹。模型未完成、身份错配、重复或损坏记录全部计 unknown，不能当成 OOD 正确拒绝。

预先规定的门为 120 条合法输入中至少 96 条正确、60 条 OOD 中最多 3 条错误接受，并且全部 180 条终态完整、身份正确、unknown 为 0。详细规定见 `EVALUATION_PROTOCOL.json`。教师评价仅在整个门通过时返回 0。

统计分开保留正确路由、错路由、拒绝和 unknown。可用 token 使用量包含已记录的失败或无效尝试；缺失使用量不记作零成本。基线的时间和 CPU 只是子进程路由成本，不是完整 agent 或模型服务的资源成本。

已执行的本地检查只验证评价器：完美的合成结果、未知 OOD、指纹错配、重复 operation、结果数量异常等。它们不是真实教师或路由器运行结果。真实比较由 parent 在既有 V6 工作树运行并保存原始证据。
