# 第二轮原件导出与重建

主实验 run-v2-01 已终止。修正后的 export-v2-02 与 restored-v2-02 已完成：
973 份原件逐字节核验，八份模型清单通过，两份适配器在新目录、新进程下
重放原最后一条 B 请求，答案、token 数、输入与模型摘要、消息协议均匹配。
这验证本次模型材料与加载配置的恢复，不产生 Adopt 或新增独立样本。

## 固定身份

- 实验源码提交：`507f04e20b6b9034d490b38a799eb32577ba5bbb`。
- 44 份实验包 Python 文件摘要：
  `fdcd9466664b6847bab4d4f547c5e8452a0eb5fe831452c9b4aa4607408aeae1`。
- 最终 EXPORT.json SHA256：
  `2f554acf9e774469dfa5d078da08186954dfc93d05e1be66f9a9eb4f086f2d2f`。
- INVENTORY.json SHA256：
  `45848ea1b849f4d7e5dd69d86afd0dc5875413436ba8b58d777520ea2ed04f6f`。
- RESTORE_RESULT.json SHA256：
  `f989b245f09ebd6419846ecaaa89b8e5c97c35dd2acf84781930db233c00c1c3`。

运行、日志、源目录均在 /home/qq/hepta-cell-experiments-20261116-0c078a 下，
分别为 run-v2-01、run-v2-01-receipts、candidate-v2-01。
导出器核对 supervisor 终态、FREEZE.json、冻结输入、44 份源码与 fixture，
并在归档后重扫原件，拒绝变化中的运行目录。

## 原件范围与公开底座

INVENTORY.json 逐文件登记大小、SHA256、Git blob 和归档位置。恢复根目录
run/ 保存全部运行文件，execution-logs/ 保存阶段及 supervisor 日志，
source/ 保存所提供的 scripts 源码及精确 fixture。源目录的临时 Python
bytecode 不作为源文件归档；冻结的源码与 fixture 必须逐字节一致。

| ZIP 原始流 | 内容 | 条目 | 分块 |
| --- | --- | ---: | ---: |
| receipts.zip | 运行、日志、模型清单、源码与 fixture | 953 | 4 |
| base-metadata.zip | tokenizer、configuration 等元数据 | 6 | 2 |
| checkpoints.zip | 六个训练 adapter、optimizer 状态和 rank8 集成 adapter | 13 | 36 |

唯一不重复写入 Git 的原件是公开底座权重，它仍登记在完整清单中：

- 模型：HuggingFaceTB/SmolLM2-135M-Instruct。
- revision：`12fd25f77366fa6b3b4b768ec3050bf629380bac`。
- 文件 model.safetensors：269,060,552 字节。
- SHA256：`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`。
- 恢复位置：run/base/model.safetensors。

恢复必须提供并核验同一份权重。本次命令从原运行目录读取该固定公开权重；
独立重建时可提供其他位置的同一字节文件。

## 有效 ZIP 分块

每个原 ZIP 流按最多 491,520 字节切分，每块再装入有效 ZIP_STORED 容器，
唯一条目为 payload.bin。满块容器 491,640 字节，严格小于 512,000 字节。
先核对容器大小、SHA256 和 Git blob，再按 EXPORT.json 顺序提取并拼接
payload；不能直接拼接 ZIP 容器。恢复器也核对各段 payload 和整个重建流。

发布以 EXPORT.json 的 publish_files 为准，并附上匹配工具和本说明。
不要提交超过上限的原大 ZIP 流。

## 匹配工具和实际命令

两份工具放在同一目录，字节身份必须匹配 EXPORT.json tools。
修正工具目录 archive-tools-v2-02，文件权限 0444、目录权限 0555。

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| export_run_v2.py | 15,611 | `6e5cddb74338de64bf648337fa0e204f4ca3f7cafa8bb9e05dbc6c321a936821` |
| restore_run_v2.py | 16,458 | `d425781f3ac99286847d01ef6db9628cb114b2fc046ace8fd5b0eacdc9791abd` |

以下为本次实际命令。所有输出目录只允许新建，再次运行须换用尚不存在的目录。

```bash
/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python \
  /home/qq/hepta-cell-experiments-20261116-0c078a/archive-tools-v2-02/export_run_v2.py \
  --run-root /home/qq/hepta-cell-experiments-20261116-0c078a/run-v2-01 \
  --logs-root /home/qq/hepta-cell-experiments-20261116-0c078a/run-v2-01-receipts \
  --source-root /home/qq/hepta-cell-experiments-20261116-0c078a/candidate-v2-01 \
  --output /home/qq/hepta-cell-experiments-20261116-0c078a/export-v2-02 \
  --restore-script /home/qq/hepta-cell-experiments-20261116-0c078a/archive-tools-v2-02/restore_run_v2.py \
  --source-commit 507f04e20b6b9034d490b38a799eb32577ba5bbb
```

```bash
/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python \
  /home/qq/hepta-cell-experiments-20261116-0c078a/archive-tools-v2-02/restore_run_v2.py \
  --export-dir /home/qq/hepta-cell-experiments-20261116-0c078a/export-v2-02 \
  --output /home/qq/hepta-cell-experiments-20261116-0c078a/restored-v2-02 \
  --base-model /home/qq/hepta-cell-experiments-20261116-0c078a/run-v2-01/base/model.safetensors \
  --expected-export-sha256 2f554acf9e774469dfa5d078da08186954dfc93d05e1be66f9a9eb4f086f2d2f \
  --probe-adapters
```

省略 --probe-adapters 时只核验原件和模型材料。启用后分别创建新 Python
进程调用冻结的 study_v2_support.cold，使用原最后一条 B 请求，并在探针后
再次核验全部原件。没有新的语义验证、候选选择或训练。

## 首次失败及修正

archive-tools-v2-01、export-v2-01、restored-v2-01 全部保留。首次恢复完成
原件与八份模型清单核验，final-answer 也发出了预测；随后原 CLI 资源
记录器试图新建已经恢复的 run/stage_resources/cold-final_answer.json，
触发 FileExistsError 并退出 1。失败日志、预测及成本均保留。

修正仅改外部恢复工具：Python -c 驱动直接调用同一个冻结 cold 函数，
避免原 CLI 的资源记录器写入历史原件。PID、请求、模型、答案、token 与
协议比较不变。44 份源码、原 run、日志及 journal 路径均不修改。
新 EXPORT.json 绑定修正工具身份；不得对旧 manifest 跳过工具摘要检查。
42 个分块与 INVENTORY.json 和首次导出完全相同，已逐块重读核验，
详见 ARCHIVE_EQUALITY.json。

## 实际恢复与成本边界

修正后恢复总墙钟 18.9144 秒，探针均 MATCH：

| 适配器 | 输入 token | 输出 token | 探针墙钟秒 | 新进程 PID |
| --- | ---: | ---: | ---: | ---: |
| final_answer | 602 | 256 | 12.8025 | 3656834 |
| trajectory | 371 | 26 | 3.88927 | 3657393 |

父进程 PID 3656788。加上首次失败发出的一个预测，共三次事后推理重放、
1,575 个输入 token、538 个输出 token；新增独立样本与语义验证调用均为零。
这些重放不改变主实验的 NO_UPDATE 决定，详细成本见 RESTORE_ATTEMPTS.json。

匹配的是已保留的行为，不是新的业务成功率。optimizer.pt 只核验字节，
未反序列化或恢复 optimizer。原 journal 绝对路径保持历史原件，不声称
另一 owner 已恢复运行。能耗与完整系统成本未测得。

三项机械测试在格式化前通过；just fmt 和锁定 Ruff 0.15.13 保持格式化
前后 AST 一致，44 文件包字节不变。修正后的完整 --probe-adapters 工作流
已实际通过，没有仅因排版重跑测试。RUNTIME_ENVIRONMENT.json 作为独立
环境证据保留，不回写冻结 run。
