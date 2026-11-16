# 第二轮原件导出与重建

本文说明归档工具和验收边界。准备工具时，run-v2-01 仍在执行；
没有读取其 C 输入、实时评价结果或模型输出，也没有提前导出运行目录。
实际文件数量、归档摘要与恢复结果，应以完成后生成的 EXPORT.json、
INVENTORY.json 和 RESTORE_RESULT.json 为准。

## 固定范围

运行目录：

`/home/qq/hepta-cell-experiments-20261116-0c078a/run-v2-01`

执行日志：

`/home/qq/hepta-cell-experiments-20261116-0c078a/run-v2-01-receipts`

冻结源目录：

`/home/qq/hepta-cell-experiments-20261116-0c078a/candidate-v2-01`

44 份实验包 Python 文件的固定摘要：

`fdcd9466664b6847bab4d4f547c5e8452a0eb5fe831452c9b4aa4607408aeae1`

导出程序同时核对运行 FREEZE.json、全部冻结输入、任务 fixture 清单和
supervisor 的终态源摘要。只有 COMPLETE_DEVELOPMENT 或 INCOMPLETE 的
终态日志可以导出；操作者仍须先观察实际 durable job 已终止。
工具拒绝重复使用导出目录，失败后保留已经生成的文件。

## 导出保存什么

INVENTORY.json 逐文件记录 bytes、SHA256、Git blob 和归档位置：

| 恢复后的根目录 | 内容 |
| --- | --- |
| run/ | 全部运行文件，包括输入、计划、模型、评价、SQL 数据库和原始请求 |
| execution-logs/ | 全部阶段 STARTED、RESULT、stdout、stderr 及 supervisor 结果 |
| source/ | 已提供的 scripts 源码及依赖、精确 fixture 文件和可用的根级说明 |

源码中的临时 Python bytecode 不作为原始源文件归档。实际执行的 44 份
Python 文件及其 fixture 必须与运行冻结清单完全一致。恢复包因此不依赖
仅保留脚本名或运行摘要，也不会丢失模型调用和语义验证管线。

所有原件分为三个 ZIP 流：

- receipts.zip：运行和执行日志原件、模型清单、源码与 fixture。
- base-metadata.zip：底座 tokenizer、configuration 等元数据。
- checkpoints.zip：全部训练与集成的 adapter safetensors，以及 optimizer.pt。

唯一不重复写入 Git 的原件是公开的底座权重：

- 模型：HuggingFaceTB/SmolLM2-135M-Instruct。
- revision：`12fd25f77366fa6b3b4b768ec3050bf629380bac`。
- 文件：model.safetensors。
- 大小：269,060,552 字节。
- SHA256：`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`。
- 恢复位置：run/base/model.safetensors。

它仍完整登记在原始清单中。恢复时必须提供并核验同一份权重。

## Git 分块容器

每个 ZIP 流按最多 491,520 字节切分。每块再放进一个有效的 ZIP_STORED
容器，容器中唯一条目为 payload.bin。满块容器为 491,640 字节，
严格小于仓库的 512,000 字节二进制上限。

例如：

`checkpoints.part-000.zip`

先验证容器大小、SHA256 和 Git blob，再提取 payload.bin。按 EXPORT.json
声明的顺序拼接 payload，即可重建原 ZIP 流；**不能直接拼接 ZIP 容器**。
工具也核对每段 payload 的长度及 SHA256，并验证整个重建流的身份。

发布时使用 EXPORT.json 的 publish_files 列表，再附上两份工具与本说明。
整个大 ZIP 流留作本地原件，不应以超过限制的单个二进制文件提交。

## 终态后执行导出

将 export_run_v2.py 与 restore_run_v2.py 放在同一个工具目录。
以下 archive-tools-v2-01 工具目录已完成 create-only 上传；两份脚本权限为
0444，目录权限为 0555。ARCHIVE_TOOLS_UPLOAD.json 保留上传过程与字节身份。

```bash
/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python \
  /home/qq/hepta-cell-experiments-20261116-0c078a/archive-tools-v2-01/export_run_v2.py \
  --run-root /home/qq/hepta-cell-experiments-20261116-0c078a/run-v2-01 \
  --logs-root /home/qq/hepta-cell-experiments-20261116-0c078a/run-v2-01-receipts \
  --source-root /home/qq/hepta-cell-experiments-20261116-0c078a/candidate-v2-01 \
  --output /home/qq/hepta-cell-experiments-20261116-0c078a/export-v2-01 \
  --restore-script /home/qq/hepta-cell-experiments-20261116-0c078a/archive-tools-v2-01/restore_run_v2.py
```

如已核对完整 Git 源提交，可以额外传入 --source-commit 和完整 40 位提交。
未传入时保留 null；源文件快照和固定摘要仍可独立核验。
导出程序结束时返回实际 EXPORT.json 的 SHA256，供下一步骤使用。

## 在新目录恢复

两份工具须保持与 EXPORT.json tools 字段记录的原始字节一致。
EXPECTED_EXPORT_SHA256 表示上一阶段实际返回的摘要，应替换成该值。

```bash
/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python \
  /home/qq/hepta-cell-experiments-20261116-0c078a/archive-tools-v2-01/restore_run_v2.py \
  --export-dir /home/qq/hepta-cell-experiments-20261116-0c078a/export-v2-01 \
  --output /home/qq/hepta-cell-experiments-20261116-0c078a/restored-v2-01 \
  --base-model /home/qq/hepta-smollm2-weight-research-20261103/pinned-base/model.safetensors \
  --expected-export-sha256 EXPECTED_EXPORT_SHA256
```

程序从小 ZIP 容器重建三个流，检查原始文件集合完全相同，复制并核验
固定底座，然后从恢复后的源码导入原模型材料验证器，验证预计八份
model manifest：父模型、六个训练候选和一个 rank8 集成候选。

所有目录均新建。失败留下 RESTORE_FAILED.json，不覆盖先前恢复结果。

## 可选的新路径预测探针

仅在完整任务终止、操作者决定执行额外探针后，在恢复命令中增加：

`--probe-adapters`

它分别启动新进程，从恢复后的新目录加载 final-answer 和 trajectory
两个适配器，输入原始最后一条 B 请求。程序比较原答案字节、模型摘要、
输入输出 token 数、输入摘要及消息协议，并保留 stdout、stderr、PID 和墙钟耗时。

该探针是重放，不增加独立任务或样本。它不重新执行语义测试、不进行训练、
不重新选择模型，也不产生 Adopt。默认恢复不进行任何推理。

## 验证边界

原 SQL journal、请求及日志里的绝对路径保留为历史原件。工具不改写它们，
因此“全部文件一致”和“两个适配器可以从新目录重新预测”都不等于
“原 owner 已在另一位置恢复运行”。

optimizer.pt 仅验证字节身份，既不反序列化，也不恢复 optimizer。
既有 Adopt/NoUpdate、来源独立性、未来任务及生产资格，只能依据对应
原始实验结果；归档或重建不会提高这些资格。

准备阶段的三个本地机械测试已验证：满块为有效 ZIP 且低于大小限制、
实际流与成员逐字节重建、损坏容器拒绝和规范相对路径约束。
这些测试使用单独临时数据，没有读取真实运行或 C 集。

三份工具/测试文件随后使用既有 Mac 工作区的 just fmt 和锁定的
Ruff 0.15.13 完成排版。AST 前后一致，44 份实验包文件保持逐字节一致；
没有仅因排版而重新运行测试。详见 ARCHIVE_TOOLS_FORMAT.json。

最终上传到 AI395 的工具身份：

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| export_run_v2.py | 15,611 | `6e5cddb74338de64bf648337fa0e204f4ca3f7cafa8bb9e05dbc6c321a936821` |
| restore_run_v2.py | 15,985 | `385a53a5c286365d800a6c3559d275768a802ba181e4cc80e1b224d6fecfe6d0` |

运行环境观察 RUNTIME_ENVIRONMENT.json 应作为单独证据保留，不回写冻结的
run 目录。上述格式化和上传均属于准备工作，不表示实际运行已经终止或已经归档。
