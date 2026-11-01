# 独立审计的实际执行源码归档

## 来源与身份

这四份脚本是本次会话已执行的四个 Python heredoc 的 stdin 正文，按原始工具调用记录逐字归档。当时没有生成 `/tmp` 源文件，也没有在执行前记录 stdin 的 SHA-256；下列哈希是本次归档时计算的，不能解释为事前冻结或第三方时间戳。

原有压缩写法、未使用的 import、未执行的条件分支、硬编码路径和输出字段均保留，没有为了美化或增强检查而改写执行逻辑。`audit_stage_02_checks.py` 是实际产生 944 项核对结果的程序。先前仅打印信息的临时只读检查命令不属于结果生成程序，未收录。

`SOURCE_EXECUTION.json` 保存每阶段的文件 SHA-256、字节数、原始环境变量前缀、执行目录和 Python 路径。每份 `.py.gz` 是同一源码的确定性 gzip 副本，解压后的字节与对应源码完全相同。它用于在通用格式化器改写可读 `.py` 时保留实际执行正文；不应格式化历史源码快照。

| 次序 | 脚本 | 作用 | 源码 SHA-256 |
| --- | --- | --- | --- |
| 1 | `audit_stage_01_ties.py` | 新建 provenance，重放五处 D/HMM 差异，写入初始 raw | `575c8b1977e679dd22b2b72ea6a638f8c44bfd35c15ed3bc9e0687908cbfde40` |
| 2 | `audit_stage_02_checks.py` | 实际的 944 项核对、全部 episode/sequence 重放、独立统计 | `f79ec61cc41fae2cc5840db3fa916fad13780ee8a13c3c7e53f7d3bbfa98351f` |
| 3 | `audit_stage_03_ledger.py` | 补全三核心逐种子训练成本及未测项 | `8a676a0fb768eb1165793b2cd0ae96cef0124c0d649357eb47663b33e7108471` |
| 4 | `audit_stage_04_finalize.py` | 加入最终人工审读的结论元数据，结束 raw 状态 | `f96d23a2292ebb78b0051f13383a947080f0694d6b4e66f542411ec2b316883d` |

报告 `REVIEW_ZH.md` 由 `apply_patch` 编写，没有声称由这四份程序自动生成。阶段 4 只读取其文件大小，并将最终解释写入 raw。

## 原执行环境与顺序

当时工作目录：`/workspace/scratch/3a732c35be06/hepta-r12`。

Python：`/tmp/hepta-r12-venv/bin/python`。阶段 1 和 2 明确设置 `OMP_NUM_THREADS=1`、`OPENBLAS_NUM_THREADS=1`、`MKL_NUM_THREADS=1`，并在程序内设置 Torch 单线程。全部阶段设置 `PYTHONDONTWRITEBYTECODE=1`。

下列是使用归档文件向 stdin 提供同样正文的重放方式。**只在另一个具备完整冻结输入的仓库副本根目录中执行**：阶段 1 会重写该副本的 `review/raw.json`。本次归档没有执行这些命令，也没有改写权威 raw 或报告。

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 /tmp/hepta-r12-venv/bin/python - < tools/hcsn/unified_cell_r12_20261031/review/audit_stage_01_ties.py
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 /tmp/hepta-r12-venv/bin/python - < tools/hcsn/unified_cell_r12_20261031/review/audit_stage_02_checks.py
PYTHONDONTWRITEBYTECODE=1 /tmp/hepta-r12-venv/bin/python - < tools/hcsn/unified_cell_r12_20261031/review/audit_stage_03_ledger.py
PYTHONDONTWRITEBYTECODE=1 /tmp/hepta-r12-venv/bin/python - < tools/hcsn/unified_cell_r12_20261031/review/audit_stage_04_finalize.py
```

需要保留原目录布局、冻结的 R11/R12 源码、24 份拟合、训练归档、确认结果、汇总结果和原生动态库。阶段 3 会按文件是否存在，附记主代理的 `audit_frozen/RESULTS.json` 与 `contract_frozen/RESULTS.json`；其存在性和内容也是完整字节级复现所需的输入。

Python/NumPy/SciPy/Torch 的归档时环境版本列在 JSON 的 `current_environment_at_archiving` 中；该字段明确是归档时读取，未补称为当时另行冻结的运行环境回执。

## 归档核对

本次只做 Python AST 语法解析和 gzip 解压字节相等检查，没有重新运行模型、episode、统计或全部审查。归档前后，以下文件哈希保持完全相同：

| 文件 | SHA-256 |
| --- | --- |
| `review/raw.json` | `0b7ec63eb1f49325b8ed05fea292051a146670c078d9d89a0592552ad87eef8c` |
| `review/REVIEW_ZH.md` | `9cd30231e4a5670146579760cbd87fc67dc7a7f11646783209ae95f3d465fe3a` |
| `evidence/FREEZE.json` | `eeb6e9cb76145024f8e58a2b0ececcfd73435f9f1997fad766fab8e1545e62fd` |
| `evidence/CONFIRMATION.json` | `60c17c15b84908c115ebcd1481b245fbff41482bd11fb22215acb5eeade0030a` |
| `evidence/SUMMARY.json` | `fca9ea250a66a720b335f7c633d2ee3a9f6a088a130ede047baa9a2af08c2f34` |
