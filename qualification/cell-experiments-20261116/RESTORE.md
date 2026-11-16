# 归档、核验与模型材料

本目录保存 run-v1 的原件与派生分析。原始运行位于 AI395 的
`/home/qq/hepta-cell-experiments-20261116-0c078a/run-v1`；执行日志位于同级
`run-v1-receipts`，冻结源文件位于 `candidate-v1`。

## 当前归档布局

原证据提交 `37486a3e2f94b6ab66052c3c0734ac3cd10946e8` 的部分二进制块超过仓库
512,000 字节的上限，而且不以 `.zip` 结尾的原始碎片被 Codespell 当作文本扫描。
本次只修改归档布局：每个新块都是有效 ZIP，其中只有 `payload.bin`。按清单顺序连接
payload，可逐字节重建下表中的原 ZIP。源码、训练结果、模型和原始清单均不改变。

| 重建后的原 ZIP | 字节数 | SHA256 | 内容 |
| --- | ---: | --- | --- |
| `receipts.zip` | 608,475 | `8ebdfbdaefbd1ffa849f9a69141c6bc7020b2db8616e48c64b6e577263372c7e` | 477 份模型清单、训练/评价/交互原件、SQLite 和分阶段日志 |
| `base-metadata.zip` | 595,541 | `2e8c9583a9afc75da225d17a4385cc7d8defa0ecfbc7056bdb9bc49267e9505d` | 6 份原始 tokenizer/configuration/material-manifest 文件 |
| `checkpoints.zip` | 18,426,636 | `bdbcbdc4b7b77e5c177e0d608eb5f815e72596e7468ff8ca7036b0248e144ea5` | 7 份 LoRA safetensors 与 7 份 optimizer.pt |

当前块位于 `archives/policy-parts/`：receipts 和 base-metadata 各 2 块，checkpoints
共 38 块，合计 42 块。最大容器为 491,640 字节，小于 512,000 字节；最大 payload
为 491,520 字节。每个容器及 payload 的大小、SHA256，以及容器 Git blob 身份，见
[ARCHIVE_PARTS.json](archives/ARCHIVE_PARTS.json)。必须先解出 payload，不能直接连接 ZIP 容器。

[EXPORT.json](archives/EXPORT.json) 和 `PUBLICATION_ARTIFACTS.json` 保留为原提交的历史快照，
其中旧分块路径已由新布局替代。当前路径映射、被替代的对象和传输核验见
[ARCHIVE_POLICY.json](ARCHIVE_POLICY.json)。原始 `INVENTORY.json` 继续固定 498 份运行文件。

## 底座权重身份

三类归档保留原清单中的 497 份文件；269,060,552 字节的公开底座通过固定来源及 SHA256
引用，不重复放入 Git。

- 模型：`HuggingFaceTB/SmolLM2-135M-Instruct`。
- revision：`12fd25f77366fa6b3b4b768ec3050bf629380bac`。
- 原件：[固定版本模型卡](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct/blob/12fd25f77366fa6b3b4b768ec3050bf629380bac/README.md)，标注许可为 Apache-2.0。
- 权重 SHA256：`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`。
- 重建位置：`results/base/model.safetensors`。

模型卡、底座和本次实验 adapter 有各自的身份；底座模型卡结果不代替本次任务输出。

## 核验和解包

在本目录运行以下标准 Python 代码，将目录重建到新的 `restored-v1/`：

```python
import hashlib
import json
from pathlib import Path
import zipfile

here = Path.cwd()
manifest = json.loads((here / "archives/ARCHIVE_PARTS.json").read_text())
destination = here / "restored-v1"
destination.mkdir(exist_ok=False)
(destination / "archives").mkdir()

def checked(raw, expected):
    assert len(raw) == expected["bytes"]
    assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
    if "git_blob" in expected:
        header = b"blob " + str(len(raw)).encode() + b"\0"
        assert hashlib.sha1(header + raw).hexdigest() == expected["git_blob"]
    return raw

for name, archive in manifest["archives"].items():
    assert name in ("receipts.zip", "base-metadata.zip", "checkpoints.zip")
    payloads = []
    for part in archive["parts"]:
        container = here / "archives/policy-parts" / part["name"]
        checked(container.read_bytes(), part)
        with zipfile.ZipFile(container) as z:
            assert z.namelist() == ["payload.bin"]
            payload = z.read("payload.bin")
        checked(payload, {"bytes": part["payload_bytes"],
                          "sha256": part["payload_sha256"]})
        payloads.append(payload)
    raw = checked(b"".join(payloads), archive)
    restored_archive = destination / "archives" / name
    with restored_archive.open("xb") as stream:
        stream.write(raw)
    with zipfile.ZipFile(restored_archive) as z:
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
        checked(path.read_bytes(), item)
    else:
        missing.append(item["path"])
assert missing == ["results/base/model.safetensors"]
```

加入固定底座权重后，再检查其大小和 SHA256。随后可用
`coding_sft.verify_model(manifest, artifact_root)`，设置
`artifact_root=restored-v1/results`，校验父模型与七个候选的全部材料。

## 核验范围

新容器在 AI395 生成并重建验证，job 为 `1a1e48f799c-392-3762`，实际退出码 0。
三个重建 ZIP 的字节数和 SHA256 与原归档一致；42 个实际传输内容创建的 Git blob
均与生成时的对象身份一致。此次仅重排容器，没有增加训练、推理或独立样本。

原来的完整材料重建已在另一个新目录校验 498/498 份文件，并通过 8 份 model manifest
检查，见 [RECONSTRUCTION.json](RECONSTRUCTION.json)，job 为 `1a1e3b06516-392-348b`。
这保障材料身份，不证明 Adopt 后的冷恢复；原 E6 只覆盖 NoUpdate 后的父模型重载。

上面的恢复代码还在新目录实际执行，job 为 `1a1e49a1ed3-392-3781`，退出码 0：
497 份归档内原件全部通过校验，仅缺预期中单独引用的公开底座。

原始 E6 request、教师 registry 和日志保留当时的 AI395 绝对路径。换路径后的新预测或
新操作需单独记录。READOUT 中“当时缺失材料”描述当时的复核范围，不改写为当时已完成
tensor 重算。来源授权、独立评价主体、未来任务和生产准入缺口继续保留。
