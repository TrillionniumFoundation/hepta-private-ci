# 实际运行环境、来源与完整证据

本目录继续既有 `closure_20261025` 工作。旧来源、候选、结果和失败保留原身份；新实验另行登记。没有把已经打开的 MNIST 来源重新命名为独立确认集，也没有重新生成旧输出来替代保存的证据。

## 原模型与原生依赖

从此前完整证据中恢复了 200 个共享文件、661,362,822 字节，逐 SHA-256 验证后才使用。包含三个本轮固定种子的 V6 生成器及 teacher、公开 sensor、独立 observer、原训练/选择表和 MNIST 来源记录。恢复清单在实际工作区 `ndu-next-assets/shared/RESTORED.json`；原共享完整归档 SHA 为 `f4360ba4625a52274120ffd7f50101efccedf58e05a403d189ba160b3ace565e`。

原生执行恢复了原仓库提交 `9595221c21f1fe0775295a9c8756a1ba4d69ea49` 的 428 个明确依赖文件，逐文件验证，重建 22 个相关 crate。实际 owner 源来自 `985a52e84cdaed7c8d4c363f30bc8841c5e3730c`，没有为了本实验改写 owner 的准入或授权语义。每次研究执行器构建另存具体源码、依赖 rlib 身份、命令、编译器和最终二进制 SHA。

实际使用 Rust 1.95.0、Python 3.12.14、CPU Torch 2.14.1、ffmpeg/ffprobe 6.1.1。完整 Python 包版本和环境限制见 [RUNTIME_VERSIONS.json](RUNTIME_VERSIONS.json)，安装需求见 [requirements.txt](requirements.txt)。这些记录能识别本次执行环境，不等于已经提供一个包含操作系统和所有动态库的便携容器镜像。

## 新来源分配与统计单位

图像来源为作者提交 `94061367ec2e099ea18c553c75727ecf849ddb9b` 的 QMNIST/XNIST。压缩原文件、许可证、作者 README 和下载回执已经完整封存；见 [SOURCE_EVIDENCE_ARCHIVE.json](SOURCE_EVIDENCE_ARCHIVE.json)。完整归档保存原字节，不仅保存下载链接。

| 固定角色 | 来源对数 | 独立书写者数 | 用途 |
|---|---:|---:|---|
| QMNIST control | 512 | 128 | 实际策略、反馈及成本比较 |
| QMNIST native calibration | 96 | 12 | H1 新准入头校准 |
| QMNIST native execution | 96 | 24 | 同准入原生策略比较 |
| QMNIST media | 128 | 32 | 真实四模态接入确认 |
| QMNIST joint | 128 | 32 | 两个联合训练目标比较 |
| XNIST H1 qualification | 1,000 | 1,000 | 原准入门槛独立资格 |
| XNIST action value | 512 | 256 | 新 signed critic 独立确认 |
| XNIST H2 calibration | 100 | 100 | 两步准入头的新校准 |
| XNIST H2 qualification | 1,000 | 1,000 | 两步模型独立资格 |
| XNIST H2 execution | 128 | 64 | 完整两步原生比较 |

分配本身不是运行完成记录。各角色是否实际开放、是否通过门槛，以对应协议、完成记录和报告为准。QMNIST 留有 10 位未分配书写者，当前 XNIST 分配后留有 85 位；它们没有被用于结果驱动的追加确认。

[SOURCE_AUDIT.json](SOURCE_AUDIT.json)、[CROSS_SOURCE_AUDIT.json](CROSS_SOURCE_AUDIT.json)、[METADATA_AUDIT.json](METADATA_AUDIT.json) 和 [NATIVE_H2_SOURCE_AUDIT.json](NATIVE_H2_SOURCE_AUDIT.json) 分别保留 writer、数字身份、重复标记及准确像素 SHA 的排除检查。新 H2 的选中图像另外与全部原 MNIST 70,000 张和全部 QMNIST test 60,000 张逐像素 SHA 比对。准确像素排重不等于证明不存在任何视觉近似，也不证明未知外部训练历史没有使用过这些公共数据。

重复视图、未来采样、动作枚举和训练 seed 都留在原来源组内，不用来增加独立样本数。联合四模态任务有 32 位书写者、24 位说话者；共享说话者的书写者属于同一连接组，正式 bootstrap 单位为 24 个连接组。固定三个 seed 的面板结果不外推为整个训练 seed 总体。

音频使用原 Speech Commands v0.02 的真实录音。输入拟合、旧 observer 开发、各轮新资格、正式 media 和 joint 的说话者分配分别保存。V3.1 的新输入头与新 ASR 组合若共用同一 300 条、147 位说话者的资格 cohort，它们是相关的两个终点，不能被称为两次独立实验。外部 ASR 的未知预训练来源重叠没有得到保证。

## 成本和资源事件

运行于共享、受限的 8 GiB 环境。每次重要阶段保留整个子进程的 wall、CPU、峰值 RSS、退出码和资源事件，同时区分在线执行、离线枚举、私人评分、模型加载、实际 codec 和核验。请求均值不能替代完整实验成本；共享机器测得的尾部也不能冒充独占生产服务的 SLA。

先前并行音频资格尝试发生的三个 OOM kill、部分已生成结果和退出码 137 已保留。后续大模型任务根据实际资源串行安排；某次顺利运行不会抹掉这些失败。运行日志中的资源计数是累计数，必须比较阶段前后增量。

空间回收只针对已由完整归档和逐文件 SHA 验证的历史重复缓存或明确的临时副本。原模型、不可重现的当前输出及唯一完整归档不作为普通缓存删除。回收记录保留在工作区相应 JSON 回执中。

## 证据封存和版本解释

完整归档含原模型候选、实际输出、评分、动作提交、失败运行、源码快照、协议、分析和过程回执；大资产可引用另一份已经逐 SHA 验证的完整输入归档。具体包含范围及外部依赖在每份归档回执中列明。归档完成后重新读取所有成员并核对字节数和 SHA，内部 `MANIFEST.json` 保留每个原文件的路径和身份。

H1 校准阶段有一个已经记录的历史源码映射：当时的 `collect_qualification.py` SHA 为 `7ad1a5aea42a8f97021e1d51d5acbee248bc0a3010090523149f755a1a54a3d3`，原始执行快照仍在校准输出目录。随后未执行的资格分支适配了新 XNIST loader 名称，最终资格及原生协议绑定最终版本。封存核对使用准确历史快照，不改写旧协议，也不把所有阶段伪称为同一源码版本；详见 [native/AUDIT.json](native/AUDIT.json)。

源代码、紧凑报告和归档身份进入既有私有研究分支。大型内部原始证据保留完整本地归档；此前向另一持久存储上传的自动审批拒绝仍有效，本轮没有换一条上传路径绕过它。归档回执里的 `upload_performed: false` 如实记录这一交付边界。
