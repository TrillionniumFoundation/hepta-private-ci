# 最终独审与可移植恢复增量

此增量追加于主包，不覆盖第一版、第二版、原 verifier、旧失败或已登记的原恢复入口。

最终第二版计算候选树为 `cb7f5eaaadd55c1476a8b695c04c70848c603e85`；独立审阅实际 blob 为 `f22966fd399dccc6719d1546ea16dcae5f0384d4`。独审已核四份实际源码 GET、81 份冻结文件、109 项隔离回放、22 个额外控制，以及全部原 10,582 叶上的正反 index patch。它接受源码进入正常 PR 的 proposal 阶段；真实 Cargo/Bazel 新锁、原 deny 与产品编译测试仍未由此离线包取得资格。

`independent-review.tar.gz.b64` 无损保存独审清单中的 38 原件及清单本身，共 39 成员。包括第一版冷启动失败的完整控制日志、固定 Bazelisk/setup-bazel/Cargo 1.95 primary、最终独审、四源码实际 GET 与独审实际登记回执。`independent-archive.json` 逐项记录字节、Git blob 与 SHA256。未再次复制独审目录中的作者全包和合成 repo。

根任务在另一个恢复目录实际执行旧冻结 verifier 时，发现唯一区别是最前两条 Python AST 检查列表顺序互换。原因是原 verifier 使用未排序的 `Path.glob`，不是候选业务逻辑或原生结果变化。根保留自己的原 stdout；作者此前三次逐字节相等的回执也按其实际结果保持原样。

主包原 `restore_packet.py --replay` 继续保留其严格逐字节行为，因此遇到该枚举顺序差异会失败。完整可移植入口改用本增量的：

```sh
python3 restore_portable.py --root /absolute/path/to/delivery --extract /absolute/path/to/new-directory --replay
```

该入口恢复主包与独审补充包，执行同一未修改的离线 verifier，并保存完整新 stdout/stderr。只允许 `checks` 列表最前面两个已知、成功的 Python AST 记录互换：两个文件名、字段、布尔值和格式必须完全匹配，除此之外全部字节必须相等。三个其它派生文件仍逐字节比较，静态 JSON 同样只容许这两个检查块换序。输出同时记录真实 `raw_stdout_bytes_equal`、原/新 identity 与限定规范化结论，不把顺序不同写成原字节相等。

受控验证证明：仅互换这两块可以通过，其它已知字段的一字节漂移仍拒绝。该恢复修正是 evidence-only 增量，没有改四个候选源文件、原版本断言、工具链、隐私门、真实命令、预算或 Git ref。

主包的 `SOURCE-FREEZE.json` 中 PENDING 与未发布标志是冻结时的历史状态。最终独审由本补充回执解除；实际 PR/ref 发布由根任务另留完整原件，不在此文件预填尚未提供的提交身份。
