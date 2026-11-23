# E2 后继恢复可行性：材料可复用，完整闭包与剩余总成本仍未确定

**建议的最小下一动作是独立的有界“材料资格核验与官方依赖目录冻结”，暂不重启安装。** 旧证据已足以定位 10 份通过官方完整 SHA 的 wheel，共 **2,500,004,536 bytes**；这些材料有真实复用价值。Torch 的部分数据也有可解释的 offset，但没有一个完整 Torch wheel 通过官方 SHA。更关键的是，完整 Python 依赖闭包从未冻结成功，现有资料不足以声称“只补最后约 157 MB 就能编码或训练”。

本报告只读取本地留存证据并做区间运算；**新增主机读取、下载、安装、材料复制、CPU 编码、模型调用、native evaluation、优化器更新均为 0**。原恢复窗口、失败、部分材料、清理超时和科学预算状态保持不变。没有执行下文提案。

## 1. 当前能严格给出的依赖表

完整机器可读表为 `CATALOG.json`，便于逐项审阅的表为 `CATALOG.md`。每一项都区分：官方 URL、官方精确 size、官方 SHA、完整已核材料所在 host 与路径、只有 stat 的候选材料，以及仍未知的字段。未知值明确写为 `null` / `unknown`，没有按 0 计算。

| 类别 | 数量或现状 | 证据含义 |
|---|---:|---|
| 核心包 | 5 个固定版本 | Torch 2.9.1+cu128；Transformers 4.57.3；Tokenizers 0.22.2；Safetensors 0.7.0；PEFT 0.18.0 |
| Torch 默认 Linux 直接必需依赖 | 23 个 | 7 个一般 Python 依赖、15 个 NVIDIA 包及 Triton；来自已核官方 Torch METADATA |
| 已知包位总计 | 28 个 | 5 个核心包加上述 23 项；不代表已解析完整传递闭包 |
| 已获官方整轮 SHA 的材料 | 10 份，2,500,004,536 bytes | 9 份在 desktop 原 recovery wheelhouse，cusparselt 在 ROG；旧 ROG 上那 9 份转移副本仍待目标端重新 hash |
| 已知包位中仍缺官方 size / SHA | 17 项 | 不能计算整个 runtime 的精确剩余下载量 |
| HF 包的传递依赖闭包 | 未冻结 | 原 resolver 没有跑完，未留下完整 OFFLINE_PLAN / hash lock |

已核的 10 项是 CUDA nvrtc、runtime、cupti、cuDNN、cuBLAS、cuFFT、cuRAND、cuSOLVER、cuSPARSE 与 cuSPARSELt。每项精确版本、官方 URL、全 SHA 和文件大小均在目录表中。

已知但未获完整官方身份资格的项包括 Torch；四个 HF 核心包；NCCL、nvshmem、nvtx、nvjitlink、cufile、Triton；以及 filelock、typing-extensions、setuptools、sympy、networkx、jinja2、fsspec。后三类中有一些仅取得了包 metadata，不能当作已经下载完整 wheel。

**NCCL 是值得优先定点核验的候选。** desktop 截止记录有一个 322,348,229 byte 文件，且日志随后开始获取 nvshmem；这支持“它可能已经下载完”的工程判断，但旧证据没有保留该 wheel 的官方 SHA 和官方精确 size，也没有记录实际完整文件 SHA。若后继核验匹配，它可能不需要再下载。当前仍不能计入已核 10 份，也不能把 stat 大小冒充官方 catalog 值。

nvshmem 截止留存 38,901,760 bytes。日志的 `124.7 MB` 只是显示精度有限的总大小，无法从中严格减出精确剩余字节。ROG 的 NCCL 下载失败只报告约 `5.8 MB/322.3 MB`，本证据集中没有可定位的对应保留文件，不能把那约 5.8 MB 又计入可复用覆盖。

### “相同 exact runtime”的限制

五个核心版本和三处 runtime 模块字节身份已被冻结，必须继续保留。但过去的父训练记录没有在本证据集中冻结全部传递依赖版本。即便仅看本次失败恢复，两条 resolver 日志也已出现不同选择：desktop Torch index 选 filelock **4.2.4**、setuptools **78.1.0**；ROG PyPI seed 选 filelock **4.2.12**、setuptools **84.2.1**。这些是失败恢复时的选择，并非旧父模型训练环境的完整历史证明。

因此后继阶段可以要求“冻结核心身份与模块字节不变，并显式冻结一个可满足依赖的新完整闭包”，但不能把它写成已经恢复了历史上每个 transitive wheel 的完全相同字节。遇到冲突须明确交 root 审阅，不能静默更新版本或绕过 runtime 哈希门。

## 2. Torch 区间：去重后尚缺多少

目标官方 wheel 为 **900,881,648 bytes**，SHA256：

`7cb4018f4ce68b61fd3ef87dc1c4ca520731c7b5b200e360ad47b612d7844063`

逐段 offset、8 个原前缀的本地 SHA、7 个 suffix 的体积及剩余区间详见 `TORCH_RANGES.json` / `TORCH_RANGES.md`。

| 覆盖层次 | 已观测去重 bytes | 剩余 bytes |
|---|---:|---:|
| 原 8 个已记录本地 SHA 的前缀 | 364,923,806 | 535,957,842 |
| 上述加 ROG 7 个 suffix 的终态 stat | 718,051,132 | 182,830,516 |
| 再加入 desktop 前缀中唯一未覆盖的部分 | 743,891,674 | 156,989,974 |

最后一行只有在后继定点 hash、重叠字节比较以及最终官方整轮 SHA 都通过时才有复用资格。desktop 的 167,587,840 byte 前缀与 ROG 已覆盖区间重叠 141,747,298 bytes，唯一新增区间是 `[86,769,664,112,610,206)`，即 **25,840,542 bytes**。不能把整个前缀加在 ROG 总量上。

两个原 operator 都在读取内容前核对了 HTTP 206 和精确 Content-Range。原 8 个 prefix 还有事后本地 SHA，可用于核对留存文件身份；官方没有提供独立的分段 checksum。7 个 suffix 只有终态 stat，其中 03 记录了正常读完与 fsync，其他段没有完成回执或完整新 hash。因此不能把全部 743,891,674 bytes 称为已通过官方 SHA 的训练材料。

## 3. 真实时间依据与能推断的范围

这些是已经发生的观察，不是完成时间承诺。统计区间含有并发与部分重叠，不相加成新的端到端耗时。

| 旧操作 | 留存或完成的数据 | 实际观察时长 | 终态 |
|---|---:|---:|---|
| ROG 首次 8-range relay | 364,923,806 bytes | 303.439795 s | read timeout；仅原段 01 完整结束 |
| 一次 R2 suffix 阶段 | 353,127,326 bytes | 796.691036 s，计至持久取消终态 | 截止仍不完整，exit -15；含旧 15.602991 s 清理超时 |
| 单个成功 suffix 03 | 70,798,238 bytes | 755.954638 s | 真实完整接收与 fsync，但非官方单段 hash |
| 直接依赖预取阶段 | NCCL 仅约 5.8 / 322.3 MB | 259.246704 s | 网络超时，显式 0 retry；阶段也含 metadata 与本地网络复制 |

前两项按“阶段内最后留存的 payload 字节 / 阶段 wall”计算分别约 **1.203 MB/s** 与 **0.443 MB/s**；这个平均数不是每个 range 的速率，也没有给慢段完成时间提供保证。单个 70.8 MB suffix 实际耗时约 12.6 分钟，足以说明“首个 1 MiB 几秒钟”不能推成稳定吞吐。

先前 1 MiB 探针只用于观察源之间的差异，本报告不按它推算完整剩余文件的 ETA。无论给 1,800 秒还是 3,600 秒的新窗口，现有证据都不能保证 runtime 恢复成功；未知依赖字节还使任何“总剩余时间”缺少完整分母。

## 4. 最小可审的后继执行 scope（提案，未执行）

建议先做一个**独立 300 秒上限**的材料资格与 metadata 阶段。新 claim、新 deadline、新目录与新终态必须同时保留旧恢复记录，不改写旧 INSTALL_CLAIM 或重开旧 owner。

1. 只读取 ROG、desktop 上已记录的 **28 个明确材料文件**，不扫主机：10 个已核整轮子原件、8 个原 Torch prefix、7 个 suffix，以及 desktop 的 Torch 前缀、NCCL 和 nvshmem。总 hash 读取 cap 5,000,000,000 bytes。核对旧片段 SHA、记录缺失的 SHA，并逐字节比较 desktop 与 ROG 的重叠部分。
2. 只获取官方 PyPI / PyTorch release、index 与 wheel metadata，不下载 wheel body。按 Linux x86_64、CPython 3.12.3 展开完整标记条件与传递依赖，最多 64 包、128 个 metadata 请求、16 MiB 响应总量，0 自动重试。保留每个 URL、响应 SHA、wheel 名称、官方 size / SHA、Requires-Dist 与选中版本。未知、不兼容或超过限制直接 BLOCKED。
3. 先核 NCCL 的完整候选，避免再次下载可能已齐全的约 322 MB。所有 partial 只在身份核对后获得“可参与最后组装”的资格；整轮官方 SHA 仍为最终条件。
4. 交付完整闭包（或明确缺失清单）、精确非重叠缺口与下一次获取所需总字节。保留五核心版本、三个模块字节门、原 tokenizer / framework / parent identity。此阶段不导入框架、不 CUDA、不安装、不复制材料、不编码、不调用模型、不更新参数。

只有阶段 1 成功并经 root 审阅，才形成具体下载执行单：每个官方 URL / Range、字节上限、并发上限、一次性获取策略、全 SHA 与全局 deadline。ROG 的 Torch 部分当前条件性缺 6 段；若 desktop 唯一新增片段可复用，可缩到 5 段。整个 runtime 的最终字节 cap 现在不能填写，因为 17 个已知包位的完整官方身份和 HF 传递依赖仍未知。

获取阶段也只写新 owner 目录；完整材料全部校验通过后，才做一次纯离线 resolution / 安装计划，并在新 venv 中使用显式 hash 固定的完整集合安装。框架导入、CPU 编码与训练继续服从各自已审核 scope；尤其不得因为材料恢复成功就自动花费 16 次科学更新。

`PROPOSED_SCOPE.json` 给出上述机器可读边界。当前建议推进的是 metadata 与资格核验这一步，没有证据支持跳过它直接重新运行旧 pip 安装。

## 5. 证据文件

- `CATALOG.json` / `CATALOG.md`：所有 28 个已知包位的身份、官方完整 hash 与 unknown。
- `TORCH_RANGES.json` / `TORCH_RANGES.md`：半开区间、局部 SHA、去重覆盖与条件性精确缺口。
- `TRANSPORT_OBSERVATIONS.json`：源阶段、真实时间、计时资格与平均数的计算值。
- `SUMMARY.json`：未执行状态、旧成本引用与 0 科学执行。
- `PROPOSED_SCOPE.json`：新阶段提案，未执行。
- `SOURCE_MANIFEST.json`：本地旧证据输入逐文件 SHA；没有新增网络事实。
- `FILES_MANIFEST.json`：本报告逐文件 SHA。
