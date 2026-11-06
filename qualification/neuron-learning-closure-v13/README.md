# V13 学习状态内容闭包 → CellLearningBindingV2

这个适配模块读取固定 V13 checkpoint，验证实际内容后生成现有
`CellLearningBindingV2::Resumable` 的五个成员摘要。它复用 V13 的原始
`Adapter.load`；不运行训练、预测、encoder、下载、发布或采用操作。

所有结果都标记 `authority: "DENY_ALL"`。内容一致性不能证明来源仍处于有效前沿、
模型质量达标或模型已被产品采用。V13 是冻结 MiniLM embedding 上的残差分类器；
它不是 Joint 生成模型。这个目录与 Rust generation bridge 分阶段验证，测试资格不互相转移。

## 固定来源与依赖

参考提交是
[`aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1` / #4532](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1/qualification/memory-cell-v13)。
`PROVENANCE.json` 记录完整 commit、Git blob、SHA-256、字节长度和零改动声明。
`reference/*.py.source` 保存以下四个文件的原字节，扩展名用于避免格式化改变参考内容：

| 原文件 | 用途 | 原始 SHA-256 |
| --- | --- | --- |
| `adapter.py` | 唯一被执行的参考源：原初始化、保存、读取和 state hash | `f4c3b03dd22c4a5e7a27459348ba673842060624c6f983e9211112a49bfccba9` |
| `backend.py` | encoder manifest 与哈希格式的只读来源 | `47b18cca113cf50ee47bb67032083abb39c44fe151410be792888d3abea55a53` |
| `lifecycle.py` | SourceOwner cut、release、发布边界的只读来源 | `0cb9ce6a732f5fa3156ebc5c28776e3eb241153f7ade3286938965317b9c50eb` |
| `download_model.py` | 以 AST literal 读取原 MiniLM revision 和八个文件 pin，不执行下载 | `fd0a7e1ba831c4f2929ee8d29d22495c61ecfdbf7ceee3daec9f5110ff09c0f7` |

每次进程首次加载参考源都会核对其完整库存、SHA-256、Git blob、长度和 pin。
只有通过这些检查的 `adapter.py` 原字节才会被编译执行。其余三份来源不会被导入。
验证器依赖 Python 3.10+ 和已有 NumPy；本次运行环境 NumPy 为 `2.3.5`，与 V13 要求一致。
不新增包依赖，不导入 ONNX Runtime 或 tokenizers。

## Python 与命令行入口

```python
from verify_closure import verify_checkpoint

receipt = verify_checkpoint(
    "model.npz",
    source_snapshot="source-snapshot.json",
    encoder_manifest_path="encoder-manifest.json",
    encoder_root="local-encoder-files",
    dataset_npz_path="training-inputs.npz",
    expected_data_id="the-original-training-data-id",
    # 默认 reference：必须符合固定 V13 MiniLM profile 和真实文件 pins。
    release_manifest_path="manifest.json",  # 可选：原 SourceOwner release manifest。
)
binding_json = receipt["binding"]
```

```bash
python3 qualification/neuron-learning-closure-v13/verify_closure.py model.npz \
  --source-snapshot source-snapshot.json \
  --encoder-manifest encoder-manifest.json \
  --encoder-root local-encoder-files \
  --dataset training-inputs.npz \
  --data-id the-original-training-data-id \
  --release-manifest manifest.json
```

成功时 stdout 输出一个完整 JSON receipt；失败退出 `2`，stdout 不产生半份 receipt。
工具不写 checkpoint、encoder、数据集或 SourceOwner 数据库。CLI 不创建输出文件，
需要保存时由调用方接收成功输出。Python 调用抛出 `ClosureError`。

输入要求：

- `source_snapshot` 是 JSON 路径或 `{"cut": cut, "records": records}`，对应原
  `SourceOwner.snapshot(scope, source_ids)` 返回的两个值。每份 body 都要实际提供；
  工具核验 body 哈希、scope、revision、active、去重与原 cut 排序，再按原 canonical JSON
  规则重算 source version。仅给非零摘要不构成内容验证。
- `encoder_manifest` 使用原 `FrozenEncoder.manifest` 的完整结构；`encoder_root` 必须已有
  manifest 中的真实文件。默认 profile 固定 `sentence-transformers/all-MiniLM-L6-v2`、
  revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`、384 维、八个原始文件 pin、
  ONNX CPU backend 与 attention-masked mean / L2 pooling。工具按实际文件验证长度、SHA-256
  以及原 Git/SHA-256 pin；manifest 中记录的软件版本参与身份，但不在本工具中执行 encoder。
- 数据集 NPZ 恰有 `X`、`y` 两项。`X` 为有限的 float32/float64 二维特征，`y` 为对应的整数
  类别数组。形状、样本数、类别范围与 checkpoint 相同。fingerprint 按原训练代码将特征规范化为
  `<f8`、标签规范化为 `<i8` 后重算。工具不重新提取 embedding，不声称已经验证特征的计算来源。
- `model.npz` 必须包含 12 个 float64 参数/Adam 数组、int64 `sampler_order` 和 uint8 JSON
  `metadata`。不接受缺项或未知项；metadata 也不接受重复 JSON 键或未知字段。

为了验证一个可续训的完整状态，本接口要求 sampler 已有非空数据身份、fingerprint 和排列。
尚未绑定数据的初始空 sampler 不作为 `Resumable` 内容闭包通过；这不改变原 V13 初始化行为。

## 验证与摘要规则

所有 NPZ 先经过 `bounded_npz.py`，然后才允许 `np.load` 或原 Adapter 构造。
检查包括 ZIP 目录条数/长度、成员名称与重复、加密/压缩方法、声明解压总量；逐个读取受限的
NPY v1/v2 header，拒绝 object、结构化或其他未支持 dtype，并比较 shape 乘积和该成员的
真实声明 payload 长度。之后流式读完每个成员，触发 CRC/截断检查。巨型 shape 不能让
NumPy 先分配数组。已经检查的同一份 bounded NPZ bytes 通过 `BytesIO` 交给原 loader，
避免重新打开一个已被替换的 checkpoint。

metadata 前置验证限制模型维度、参数总量、整数类型、PCG64 状态、Adam 语义、cursor/epoch。
原 `Adapter.load` 随后再次检查真实数组 dtype/shape/finite、Adam v 非负、完整 permutation、
数据与 encoder/source 身份。没有臆造 step、epoch、batch size 之间的约束：原实现允许显式
换数据和改变 batch size，二者不意味着 optimizer step 重置。

每个成员使用 SHA-256，按小端 u64 长度分帧绑定 domain、成员名、共同上下文和成员内容。
共同上下文包含原 adapter 源码 SHA-256、schema、完整 config、经验证的 encoder identity、
source version、data ID 和实际 data fingerprint。数组绑定名称、dtype、shape 与 C-order bytes。

| Resumable 成员 | 实际参与摘要的内容 |
| --- | --- |
| `weights` | A、B、W、b 的完整实际数组 |
| `optimizer` | 全部 Adam m/v 数组、lr、batch size、beta1/beta2/epsilon、step |
| `rng` | 原 loader 接受并精确保留的完整 PCG64 状态与缓存字 |
| `sampler` | 完整 permutation、n、data ID、实际数据 fingerprint |
| `training_cursor` | step、cursor、epoch、n、batch size，以及刚验证的 sampler digest |

输出 `binding` 的 `kind` 为 `resumable`，五个值均为 32 个 u8 的 JSON 数组，与现有 Rust
`CellLearningBindingV2` 的 serde 形状一致。`member_sha256` 提供对应十六进制值。
完整 NPZ artifact SHA-256/字节数、原 `Adapter.state_hash()`、数据集 NPZ SHA-256、
source snapshot 身份、encoder manifest/文件身份和参考源码另行保存在 receipt 中。
ZIP 封装字节与逻辑成员状态分别记录；不能用两者之一替代另一个。

可选 release manifest 必须与原 `SourceOwner.stage` 产生的 canonical 结构一致，
其 NPZ/state/source/encoder 内容绑定均重新核验，返回 manifest artifact ID。
`parent_artifact` 仅校验引用格式，未读取父级内容；receipt 明示该边界。

## 接入原 owner 的位置

1. 调用原 `SourceOwner.snapshot` 获得实际 source cut 和 body，连同已有 encoder files、
   原训练输入以及 checkpoint 交给本模块。工具不构造第二个 SourceOwner。
2. 将成功 receipt 的 `binding` 作为所选后端 manifest 的学习状态身份。收到完整 receipt 的
   host 仍需按已有来源/工件 owner 校验该 artifact 的允许使用范围，不能仅凭五个非零 digest 授权。
3. 原 `SourceOwner.load`/`publish` 继续持有发布状态。`publish` 在原 SQLite transaction 内
   重验 live cut、expected epoch CAS 和 executable quality validator；撤回及后续 read 同样
   留在原 owner。这个工具不返回 `passed: true`，不能代替其质量 validator。

这里闭合的是内容到学习状态身份的映射。运行 state/prefix/outbox 仍由 generation owner 提交；
演化 lineage、采用和撤回仍由已有 owner 管理。没有新增采用权限或把冻结 source snapshot
当成当前 source frontier。

## 硬资源边界

调用方可传 `ClosureLimits(...)` 收紧边界，不能提高默认上限。

| 项目 | 默认上限 |
| --- | --- |
| 原 checkpoint / 数据集 NPZ bytes | 64 MiB / 128 MiB |
| 单个 NPZ 的声明展开总量 / 单数组 payload | 128 MiB / 64 MiB |
| NPY header / JSON metadata | 4 KiB / 128 KiB |
| ZIP 成员 | checkpoint 14，数据集 2，库存必须精确 |
| 样本数 / 单个模型维度 | 131072 / 4096 |
| 参数元素总数 / 特征元素总数 | 各 4194304 |
| 单 encoder 文件 / encoder 总量 | 128 MiB / 256 MiB |
| source snapshot / 记录数 / 单 body | 2 MiB / 256 / 64 KiB |

这不是通用 NPZ 阅读器：不支持 pickle、object dtype、多磁盘 ZIP、ZIP64 central directory、
NPY v3 或任意 metadata 扩展。原 NumPy save 的 ZIP64 local header 可用。

## 当前实际验证范围

本目录测试用固定原 `Adapter` 初始化并 `save` 一个明确 synthetic 的完整 checkpoint，
手动填写 synthetic Adam/cursor/permutation 值。未调用 train、predict、features、loss，
测试还将这些方法替换成失败钩子，防止保存/读取路径误执行计算。
synthetic encoder 有独立身份，并要求显式 `mode="synthetic-fixture"`；默认 reference 拒绝它。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s qualification/neuron-learning-closure-v13 -p '*_tests.py' -v
```

11 组行为测试覆盖原 save/load/state hash、五个成员分别变化、dtype/shape/finite/v/permutation、
cursor/epoch/RNG/config/optimizer/缺字段、危险 NPY 在 NumPy 前被拒绝、ZIP/原始及展开边界、
source/encoder/data 内容漂移、release 内容绑定、cut/release 中 bool/float 对整数 revision 的
类型别名拒绝，以及 CLI 成功/失败输出。
这些是本目录的 Python 内容验证结果，不是 V13 实际训练复跑、真实 MiniLM artifact 验证、
Joint 模型资格、Rust gate 或产品采用结果。现有真实 V13 checkpoint/encoder/data 提供后，
可用默认 reference 模式验证其具体字节；没有这些输入时不会生成真实模型 receipt。
