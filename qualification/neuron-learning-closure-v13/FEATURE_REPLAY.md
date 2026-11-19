# V13 原始输入、特征来源与完整纯计算参考

`feature_replay.py` 将固定 V13 原始 source snapshot、完整预处理数据集、MiniLM 文件、
真实训练 checkpoint 和纯函数操作输出连接到一次有资源上限的执行。
所有回执的 `authority` 都是 `DENY_ALL`。

这个 profile 是 **MiniLM 编码 → residual classifier 选路 → 12 种有限标准库操作**。
它验证固定计算与内容绑定；不代表 Joint 生成模型、普通 Hepta Cell/Agentd 接线、
通用递归状态转移、独立质量评测、学习增益、模型发布或下一任务采用已通过。
它是实际 CPU 执行回执，不是 W1 完整证明电路或无须信任执行宿主的密码学证明。

## 原始实现与输入约定

原始实现固定在 `aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1`：

- 原 `backend.FrozenEncoder` 持有真实 tokenizer、MiniLM ONNX session、attention mask、
  masked mean pooling 和 L2 normalization。八个模型文件继续使用原 pin。
- 原 `provenance_run.training_snapshot` 检查 source-bound feature archive、原 rows 和
  indices，保留 `skills` 优先、随后按 source ID 的原聚合顺序。
- 原 `Adapter.load`/`predict` 读取完整真实参数、Adam、RNG、sampler 和 cursor。
- 原 `tasks.public_input` 只把 text/payload 交给执行边界；原 `tasks.execute` 只接收预测
  skill 与实际 payload。原 goldens/labels 不进入 encoder、classifier 或 executor。

原四份 `.py.source` 不变。新增 `tasks.py.source` 和 `provenance_run.py.source` 也与
原 Git blob 逐字节相同，见 `FEATURE_PROVENANCE.json`。实际执行前再次核对六份源码
SHA-256，随后在独立 worker 中加载。`download_model` 的定义被原 backend 导入，
其下载函数不被调用；本入口没有下载、训练、SourceOwner 构造、发布或外部工具调用。

原始 source body 采用 `provenance_run.source_body` 的结构：`dataset`、`rows`、
`indices`、`event`、`feature_file_sha256`。`--inputs-root` 提供完整的
`<dataset>_rows.json` 和 `<dataset>_features.npz`。完整 dataset 保留原 batch size 32
和 padding 范围；不能只重算选中子集然后把不同 batch 的数值当成原特征。

source snapshot 仍使用 `{"cut": ..., "records": ...}`，每个 body 必须实际存在。
source cut/revision/body/hash、原始完整 rows、selected rows、indices、数据顺序、标签、
NPZ archive 和 checkpoint sampler fingerprint 都要一致。这个 profile 使用原 producer
的固定 scope；不接受任意 source 格式、合成 encoder 或 caller 提供的编码回调。

## 执行

```bash
python3 qualification/neuron-learning-closure-v13/feature_replay.py model.npz \
  --source-snapshot source-snapshot.json \
  --encoder-manifest encoder.json --encoder-root minilm \
  --dataset training-inputs.npz --data-id ORIGINAL_DATA_ID \
  --inputs-root original-inputs --release-manifest release.json
```

所需 Python 包沿原 V13 固定版本：NumPy `2.3.5`、ONNX Runtime `1.23.2`、
tokenizers `0.21.4`。执行时核对原 encoder manifest 的实际包版本与配置。
缺材料或依赖返回 `HOLD`/exit 3；内容漂移返回 `REJECTED`/exit 2；全部关系成立才返回
`VERIFIED`/exit 0。没有 synthetic fallback、误差容忍回退或伪造的成功 receipt。

结果保留：

- 实际 ONNX feed 的 `input_ids`、`attention_mask`、`token_type_ids`（按原 session
  实际使用的名称），逐批绑定 dtype、shape 和完整 C-order bytes 的 SHA-256。
- 原始 source 选择顺序、完整 dataset 及实际编码统计，含 padding 和 truncation。
- 完整 prepared dataset 的 **float32 C-order bytes 相等**；聚合训练 NPZ 单独比较
  **精确 little-endian float64 canonical bytes**，允许原 closure 支持的 float32/float64
  存储，但不会把跨 dtype 的相同数值写成原始数组字节相等。不存在 epsilon 门槛。
- 每一个原始请求的 public input 身份、预测 skill、实际 output 或执行错误。
  失败输出也保留；这些训练数据上的结果不充当独立质量评测。
- 完整 Adapter state 的 before/after hash。这个 frozen inference profile 要求不变；
  不把不变的 checkpoint 声称为已完成普通 recurrent Cell 状态更新。

原 `closure` receipt 仍如实报告其自身没有执行 encoder；新的 `features` 和
`reference_cell` 记录独立执行阶段，不能把内层旧字段改成另一套含义。

## 读取与资源边界

`closure_io` 用 `O_NOFOLLOW | O_NONBLOCK` 打开文件，随后对同一个 fd 验证 regular
file/大小并读取。encoder/数据集路径从已打开 root directory fd 逐层走，不跟随子目录
链接。读取后比较 inode、大小、mtime/ctime；同路径替换或原地改写不会被静默接受。
FIFO、目录、symlink 和读取过程中的变化会拒绝。unsupported host 明确拒绝。

执行在 private staging directory 中冻结受限字节，然后调用原实现。这里假设运行中的
Python/native packages、执行宿主和 private staging 未被拥有同等权限的攻击者控制。
摘要绑定实际内容，不能证明宿主的可信执行、实时 source frontier 或 publication authority。

默认上限只能收紧：

| 资源 | 上限 |
| --- | ---: |
| 子进程 address space / CPU | 4 GiB / 60 秒 |
| 父监督 wall deadline | 120 秒 |
| 入场材料复制总量 | 512 MiB |
| 原始 dataset 数 / 每 dataset 行数 | 8 / 512 |
| 每个 stdout/stderr 的接受上限 | 2 MiB |
| 子进程单个暂存文件硬上限 | 128 MiB |

这些是 **V13 离线资格 profile**，不是 Chain 的 2 GiB/4 秒原始服务验收配置。
父循环约每 10 ms 观察输出大小并终止超限 worker；2 MiB 是接受上限，不能声称进程在
两次观察之间绝不写过该值。`worker_output` 保留实际总字节、捕获字节、`complete` 和
完整捕获时的 SHA-256；不完整输出不能产生成功资格。原 stderr 和失败 stdout 保留在结果中。

父循环对自己启动的唯一 Python child 使用 `wait4`，记录完整 user/system CPU、峰值 RSS、
block I/O 和 context switches；正常拒绝、缺材料、超限和信号退出都计入同一分母。
`admitted_source_copy_bytes`/`staging_copy_bytes` **只计入场复制**，不表示 stage 重读、
NPZ、ONNX 和整个宿主的总 I/O。未观测到 child 时 CPU/RSS 为 `null`；能耗也是 `null`。
模型获取和调用方持久保存 receipt 的成本不在这次函数调用内。

catchable parent interruption/等待异常会先 kill/reap 该 child。`KeyboardInterrupt`
继续原样传播，不转成成功。不可捕获的父进程死亡、整机崩溃和普通 Cell durable recovery
不在这个 controller 的资格范围。`worker_termination: completed` 只表示 wait4 观察到退出；
还必须检查 `worker_exit` 和最终 `status`，信号退出始终 HOLD。

## 冷回执只读

```bash
python3 qualification/neuron-learning-closure-v13/feature_replay.py \
  --readback retained-receipt.json --expected-sha256 RECEIPT_SHA256
```

readback 必须由调用方提供已保留的完整 receipt digest。它只读取匹配字节，不导入
encoder/adapter/tasks，不重新调用模型、纯函数 executor 或外部操作。返回内层原始结果
和本次 readback 成本，明确 fresh execution 为 0。它不验证独立发布授权、实时来源状态，
也不表示下一任务读回采用了新模型；不能用自签摘要制造采用权。

## 验证与评审顺序

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s qualification/neuron-learning-closure-v13 -p '*_tests.py' -v
```

默认 suite 的 25 项包含原 11 项内容控制、5 项真实 fd/文件替换控制和 9 项 feature/
controller 控制。controller 夹具只替换 child command；实际 Popen、信号、wait4 与 reaping
在操作系统上执行。它们不是 MiniLM 的成功结果。另有真实固定材料 campaign 和独立进程
readback 的原始记录；见本目录的 `ACCEPTANCE_20261106.md`。

建议按三个可独立审查的实现阶段阅读：

1. `closure_io` 与现有两处读入口及真实 FIFO/symlink/原地修改控制。
2. `feature_replay` 的资源监督、失败计费、只读回执及真实 child 生命周期控制。
3. `feature_worker` 的固定原实现调用、source/feature/output/state 绑定，以及两份
   零改动参考源码。原始源码复制是 mechanical；新的控制逻辑单独审查。

未修改 Rust crates、Cargo/Bazel lock、CI 安全门、原 owner 的采用决策或运行时权限。
