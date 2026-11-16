# 归档、核验与模型材料

本目录保存 run-v1 的原件与派生分析。原始运行位于 AI395：

`/home/qq/hepta-cell-experiments-20261116-0c078a/run-v1`

执行日志位于同级 `run-v1-receipts`；冻结源文件位于 `candidate-v1`。这些原始目录保留在用户机器上。

## 归档组成

| 归档 | 字节数 | SHA256 | 内容 |
| --- | ---: | --- | --- |
| `archives/receipts.zip` | 608,475 | `8ebdfbdaefbd1ffa849f9a69141c6bc7020b2db8616e48c64b6e577263372c7e` | 477 份模型清单、训练/评价/交互原件、SQLite 和分阶段日志 |
| `archives/base-metadata.zip` | 595,541 | `2e8c9583a9afc75da225d17a4385cc7d8defa0ecfbc7056bdb9bc49267e9505d` | 6 份原始 tokenizer/configuration/material-manifest 文件 |
| 重组后的 `checkpoints.zip` | 18,426,636 | `bdbcbdc4b7b77e5c177e0d608eb5f815e72596e7468ff8ca7036b0248e144ea5` | 7 份 LoRA safetensors 与 7 份 optimizer.pt |

checkpoint ZIP 分成 `archives/checkpoints.zip.part-000` 至 `part-028`，前 28 块各 645,120 字节，末块 363,276 字节。它们是同一个 ZIP 的连续字节，不是分别可解压的 ZIP。每块的 SHA256、Git blob 和大小在 [EXPORT.json](archives/EXPORT.json) 中。

这三类归档共保留原始 498 条清单中的 497 份文件。269,060,552 字节的公开底座 `model.safetensors` 通过固定来源及 SHA256 引用，不重复放入 Git。

## 底座权重身份

- 模型：`HuggingFaceTB/SmolLM2-135M-Instruct`。
- revision：`12fd25f77366fa6b3b4b768ec3050bf629380bac`。
- 原件：[固定版本模型卡](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct/blob/12fd25f77366fa6b3b4b768ec3050bf629380bac/README.md)。其标注许可为 Apache-2.0。
- 权重 SHA256：`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`。
- 重建位置：`results/base/model.safetensors`。

模型卡、底座与这些新训练的实验 adapter 有各自的身份。任何能力结论都必须使用本次任务和输出原件，而不能由底座模型卡的结果代替。

## 核验和解包

在本目录执行以下标准 Python 代码，可校验所有归档和 checkpoint 分块，将原始目录结构重建到一个新的 `restored-v1/` 目录：

```python
import hashlib
import json
from pathlib import Path
import zipfile

here = Path.cwd()
manifest = json.loads((here / "archives/EXPORT.json").read_text())
destination = here / "restored-v1"
destination.mkdir(exist_ok=False)

def checked(path, expected):
    raw = path.read_bytes()
    assert len(raw) == expected["bytes"]
    assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
    return raw

parts = [checked(here / "archives" / item["path"], item)
         for item in manifest["parts"]]
checkpoint = destination / "checkpoints.zip"
checkpoint.write_bytes(b"".join(parts))
checked(checkpoint, manifest["checkpoints"])

archives = [checkpoint]
for key in ("receipts", "base_metadata"):
    item = manifest[key]
    path = here / "archives" / item["path"]
    checked(path, item)
    archives.append(path)

for archive in archives:
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            relative = Path(item.filename)
            assert not relative.is_absolute() and ".." not in relative.parts
            assert relative.parts[0] in ("results", "execution-logs")
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as stream:
                stream.write(z.read(item))

inventory = json.loads((here / "INVENTORY.json").read_text())["inventory"]
missing = []
for item in inventory:
    path = destination / item["path"]
    if path.exists():
        checked(path, item)
    else:
        missing.append(item["path"])
assert missing == ["results/base/model.safetensors"]
```

加入固定底座权重后，对该文件再次检查上述大小和 SHA256。`coding_sft.verify_model(manifest, artifact_root)` 随后可用 `artifact_root=restored-v1/results` 校验模型清单内全部实际材料。

原始 E6 request、教师 registry 和日志保留原 AI395 的绝对路径。换路径后的新预测或新操作应单独记录，不能把它当作原 operation 的重放，也不能增加独立样本数。原 E6 冷进程只覆盖 NoUpdate 后的父模型重载。

## 原件与派生分析

`INVENTORY.json` 是原始 498 份文件的固定快照；它包含实际大小、SHA256 和 Git blob。原始收据 ZIP 的 477 份文件与随后取回的 6 份底座元数据均重新计算并匹配该清单。

29 份 checkpoint 分块的实际传输内容创建了 Git blob，每个返回的对象 ID 都与远端实际文件的预计算 Git blob 一致；完整 ZIP 的大小和 SHA256 在导出时记录。checkpoint 原件及其逐文件 SHA256 也保留在原始清单中。

随后已在 AI395 的新目录中实际重组全部分块、解包三类归档，并加入固定底座权重。498/498 份文件的大小与 SHA256 全部匹配，父模型及七个候选的 8 份 model manifest 全部通过材料校验，实际退出码为 0。结果见 [RECONSTRUCTION.json](RECONSTRUCTION.json)，job 为 `1a1e3b06516-392-348b`。这个操作验证材料重建，没有执行新的模型推理或覆盖 Adopt 后冷恢复。

READOUT 报告中的“当时本地缺失材料”描述的是报告生成时的复核范围：当时先取得了 477 份收据，checkpoint 和底座元数据随后归档。这个历史观察不应改写为当时已经完成了本地 tensor 重算。

SCORECARD、READOUT、CI 快照、归档说明和发布记录属于派生文件，单独列入 `PUBLICATION_ARTIFACTS.json`。原始清单不包含后来生成的分析，也不会自引用自己的摘要。

这些核验保障本轮材料的一致性；来源授权、独立评价主体、未来任务和生产准入的证据缺口仍按结果总表保留。
