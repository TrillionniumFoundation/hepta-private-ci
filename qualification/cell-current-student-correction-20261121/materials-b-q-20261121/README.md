# E2：Stage B 失败与独立 Stage Q 材料资格证据

本目录补充实际执行与审查原件。**Stage B 保持 FAILED；随后独立运行的 Stage Q 完成 44 个 wheel 和 3 个模块的静态材料资格检查。** 本范围内安装、框架导入、编码、模型调用、权重更新和新任务读取均为 0。材料完整性通过不等于运行环境已经可用，也不是训练收益。

本次只在 `qualification/cell-current-student-correction-20261121/materials-b-q-20261121/` 新增证据。追加基点为 `cd50c98d4fe3979286d5491b6f0f1d037c61bd88`；既有训练代码冻结提交 `dc3397c9e09e29861a0a4fe2267e8ef19e55db01` 不变。B/Q 实际执行脚本分别由下表的候选和 PLAN 哈希绑定；本证据提交头不能替代其执行身份。

## 实际结果与版本

| 项目 | Stage B | Stage Q |
|---|---|---|
| 候选 | `f660cebdc91782270d91f6f7d6b1ceb4f9cfebf86c435a59bfb07f12c63590dc` | `68cc076e36ad312b6bc84cc3c823cb47eb4a1c34d372bf5b651332a44053d020` |
| PLAN SHA256 | `463791a997709d44fef360af24c387022f869e00464d23ce595af571cb841a4f` | `d5c521bc626938f421a37a5f85724970d1aed7582c9706f1e12fd269cca4f365` |
| 唯一任务 | `1a1fceaf02c-ffbe-1e42` | `1a1fd015ecb-ffbe-1e6f` |
| 原外层终态 | FAILED / exit 2 | SUCCEEDED / exit 0 |
| 新 HTTP 请求、body | 37；504,322,940 B | 0；0 B |
| 完整 wheel 资格 | 35；第 36 个 metadata 检查失败 | 44 |
| 完成模块门 | 0 | 3 |
| 原始开始至 H 确认终态 | 218.03680582 s | 15.975219895 s |
| 本阶段时限 | 获取 1500 / 工作 1740 / 总计 1800 s | 工作 540 / 总计 600 s |

两阶段的外层输出均完整、耐久且无截断，没有 timeout。B 的 37 个下载子进程均确认 exit 0，desktop SSH 确认 exit 2；Q 的 desktop SSH 和外层均确认 exit 0。这里只确认各自拥有的执行进程，不声称全主机没有其他进程。

## B 失败的具体原因

B 的 31 个完整下载响应为 200，6 个区间响应为 206；原精确区间、identity 编码、ETag、逐请求终态和完整回执均保留。B 完成全部 63 个 extent，耐久写入 4,109,714,899 B，记录 LAN 材料传输 1,367,820,465 B。下载及组装完成没有被误报为 44 个 wheel 资格完成。

失败发生在 `setuptools-78.1.0-py3-none-any.whl`。实际 ZIP 有 514 个条目；旧选择器对任意深度的 `.dist-info/METADATA` 后缀计数，得到 **17 = 1 个顶层发行包 + 16 个 vendored 发行包**，因而报出 `wheel METADATA absent/ambiguous/too large`。这是选择器错误，并非工作时限耗尽。

实际顶层 metadata 为 6,599 B，Name 为 `setuptools`、Version 为 `78.1.0`，SHA256 为 `4444a6b549a8ebb02e1739f4375af7756c841f96f0c31077a183273c7462bd10`，与先前冻结计划完全一致。诊断只读中央目录和该 metadata，记录 93,378 B 有重叠的应用层读取，没有重新哈希完整 wheel 或重跑原资格检查。

B 原失败状态、实际错误、先前审查拒绝、原 19 项控制和后继 20 项控制全部保留。第一版控制通过后仍发现的 `B-REMOTE-003` 也保留；后继才补上 desktop 早退时停止进一步 HTTP 派发的观察。

## Q 的独立通过范围

Q 只将 metadata 选择条件限定为顶层发行包。完整文件 SHA、大小、METADATA SHA、Name/Version、重复 ZIP 条目拒绝和 3 个模块哈希门均保持原条件。原 B 源码及回执没有修改。

Q 对已有 44 个文件重新执行完整静态资格检查，记录 4,109,714,899 B 完整文件逻辑读取和 581,682 B 选定解压成员读取。三个模块为：

- `torch/utils/checkpoint.py`
- `transformers/masking_utils.py`
- `transformers/models/qwen2/modeling_qwen2.py`

全部文件、metadata 和模块哈希与原冻结计划一致。44 对 desktop 开始/完成事件、44 次父进度事件、文件身份、两端 RESULT 和终态均已独立逐项核对。Q 持有 guard FD 到整个清单检查结束；这些是 Q 的新观察，不补造 B 未记录的末 8 个 wheel 历史身份。

Q 成功后仍为 `runtime_ready: false`、`automatic_next_phase: false`。它允许另行审查安装范围，不会自动执行 Stage C 或训练。此包不包含 C 草稿或任何将来结果。

## 控制、传输和收证成本

| 范围 | 原始记录 |
|---|---|
| B 第一冻结候选的离线控制 | 19 项；unittest 0.085 s；完整进程 0.3180015010002535 s |
| B 后继冻结候选的离线控制 | 20 项；unittest 0.140 s；完整进程 0.3803000189946033 s |
| Q 离线控制 | 8 项；unittest 0.020 s；完整进程 0.23531802599609364 s |
| B HTTP 获取确认 | 105.05073035298847 s，包含父层 post-fsync 确认 |
| Q 材料 post-fsync 确认 | 15.916429675999098 s |
| B 独立只读收证 | 原件读取 1,774,297 B；最终 receipt fsync 前 0.6515349739929661 s；内部 SSH 0.47176889597903937 s |
| Q 独立只读收证 | 原件读取 631,014 B；最终 receipt fsync 前 0.39642890001414344 s；内部 SSH 0.35870601097121835 s |

控制均为原来一次运行的夹具结果，归档中的重复副本不增加运行次数。打包没有重跑控制或任何远端任务。内部时间区间重叠，不能相加为总耗时；这里的字节是标明用途的逻辑操作，不是物理网络或磁盘总成本。

B 原 92,119 字符命令被 64 KiB 工具限长在准入前拒绝，没有创建材料执行任务。随后只改变命令传输形式，上传原 bootstrap 92,014 B 并完整读回；原 37 请求、504,322,940 B 和 1800 s 预算未变。Q bootstrap 单独上传并读回 130,370 B。源传输准备的完整墙钟时间仍为 UNKNOWN，不能当作零成本。原 B 首次状态观察的 SSH 传输错误单独保留，不归因为材料任务失败。

## 如何复核归档

本次新容器 `BQ_EVIDENCE.tar.gz` 为 **4,273,652 B**，SHA256：

`1dbfbfdc1ed84410d3a17726624f3a6777dcde621e6b53499fb8520c6daf8193`

Git 中保存 12 个真实二进制连续分片，每份不超过 360,000 B，低于既有 512,000 B blob 门；没有 ignore 或 allowlist 变更。Git API 的 base64 只是上传编码，仓库内分片是原始二进制。

在本目录内，用常规工具恢复到新目录：

```sh
cat BQ_EVIDENCE.tar.gz.part* > BQ_EVIDENCE.tar.gz
sha256sum -c SHA256SUMS
mkdir restored
tar -xzf BQ_EVIDENCE.tar.gz -C restored
cd restored
sha256sum -c MEMBER_SHA256SUMS
```

容器有 786 个普通文件成员：784 份既有本地文件，以及新生成的 `MEMBER_INVENTORY.json` 和 `MEMBER_SHA256SUMS`。784 份文件共 10,721,354 B，对应 555 种不同 SHA256 内容；数量包含审查快照和同一原日志的保留副本，不代表 784 次实验。每份原文件可按原相对路径逐字节恢复。归档内脚本仅为历史证据，无需执行它们来核验哈希。

保留范围为 B proposal、初稿、两版完整候选及控制、短命令传输审查，Q 39 成员候选及 manifest，B/Q 全部已收取的本地小原件、H 原始回复、收证器、独立审查，以及 root 的 `STAGE_B*` / `STAGE_Q*` 原件。不存在的 wheel/body/安装目录没有被替造；不重新收入此前单独发布的 Stage A metadata 包。

两个既有完整读回容器也作为原文件保存，不能与本次新容器混称：

| 原容器 | 字节 / 成员 | 原 SHA256 |
|---|---|---|
| `STAGE_B_ORIGINALS.tar.gz` | 464,161 B / 439 个成员 | `b898725dc77bd2455203b72cf265661a4f28ea3eb30bfaf25325687d9a942d95` |
| `STAGE_Q_ORIGINALS.tar.gz` | 258,601 B / 31 个成员 | `f43ccf72bc47e32d57c9f2d7a1ff0df4bf0adf65d1b7fd6ce0630d3b58fe96b0` |

B 容器含取证派生成员；Q 的 31 个成员为 28 份执行原件、2 份传输原件和 1 份新清单。这些容器成员数同样不能作为测试数。
