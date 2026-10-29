# RR-SNN V4：交付与复现

本轮全部预先声明的矩阵已完成。当前冻结候选没有通过主效用验收，原始数值门槛也未通过；隔离精度修复单独通过已存储脉冲事件／任务记录比较。生产与全局理论资格仍未成立。

## 结果入口

- [完整中文报告](REPORT.zh-CN.md)
- [机器结案记录](results/closeout.json)
- [全模型效用与配对结果](results/aggregate.json)
- [完整资源主表与敏感性表](policy_benchmark_results/summary.json)
- [独立报告审核](report_audit/independent_final_report_review.json)
- [实际新目录恢复收据](report_audit/fresh_directory_restore.json)

主报告和结果在不可变 commit `c210500bd975a100c2723b83ac17891c397f4b0c` 已发布，后续交付检查没有改写它们。完整实验与真实 Cell、dot、生产未来窗口、完整仓库 CI、广义新颖性或全局 QVI 证明不同；`all_blockers_closed=false`、`production_activation_allowed=false`。

## 两个互补原始证据包

两个文件需要一起使用；源码、正式生成报告、图和审阅记录由 Git 提供，没有重复放进 raw 包。

| 文件 | ZIP 字节 | 原始文件数 | 原始载荷字节 |
| --- | ---: | ---: | ---: |
| [RR_SNN_V4_Core_Raw_20261029.zip](https://chatgpt.com/library?file_id=libfile_ee2829448e808191baadc855491e0f81&account_id=personal) | 77386526 | 3086 | 91251786 |
| [RR_SNN_V4_Resources_Raw_20261029.zip](https://chatgpt.com/library?file_id=libfile_c6a224f547c88191a196832e246fce5c&account_id=personal) | 1500989 | 143 | 6784040 |

Core SHA-256：

```text
239e3ba9f786929135a505d001148df5cb82116d0422e8e483f9da37ca272792
```

Resources SHA-256：

```text
3a993c1060e2e4ff7ec769513d99bc7773acb0ce0e3a97183d8c6e03d3105e82
```

Core 包含冻结数据、80 个检查点和训练收据、960 主评估、60 原数值比较、60 修复回放、概率原件和原生证明／测量原件。Resources 包含 80 个资源条件、实际失败尝试、存储迁移与运行时记录，以及恢复审计补齐的历史 JSON。元数据分别为 `RAW_MANIFEST_core.json` 和 `RAW_MANIFEST_resources.json`，不会相互覆盖。

两包均已实际保存成功并逐成员复读核验。上传身份与哈希见 `raw_archive_receipts/core_uploaded.json` 和 `raw_archive_receipts/resources_uploaded.json`。本轮没有再次从远端下载整个包；实际恢复使用与上传收据哈希一致的本地原件。

## 实际完成的新目录恢复

恢复固定来源为 `fa46e1413cdf10402892bd6ca84bf4fbeeae9c9c`；[来源映射](resource_audit/final_restore_published_paths.json) 的 179 个 Git blob 已与不可变远端树核对。最终交付提交在此基础上增加收据和说明。

一次实际恢复创建了 **3,412 个文件**：179 个 Git 文件、3,229 个原始载荷文件及4个包元数据文件。两包所有成员的尺寸和 SHA 均核验；四个原生 ELF 的普通权限保留为 0755。随后从新副本实际执行：

```bash
python -m rrsnn_v4.build_closeout --verify-only
python -m rrsnn_v4.delivery_behavior_diagnostic --verify-only
```

两个入口均 exit 0；解析和实际执行的模块都来自新目录。恢复根目录、子目录和文件的类型／权限／时间戳保持一致，文件尺寸和内容 SHA 未被改写。恢复收据 SHA 为 `66c7120d7842b72e96debd6f223489bf38f6a2686e91edfab44afa1bf6f572cf`。

这是**同一软件环境的新目录恢复**，没有把它称为全新环境重建、重新训练、生产运行或再次远端下载验证。实验环境版本见主报告。

## 重复只读恢复

从包含本文件的最终 Git 提交取得源码，下载两个 ZIP；使用主报告中的相同运行时版本。在仓库根目录执行下例，将归档路径替换为实际绝对路径。目标目录及收据文件必须不存在，父目录须已经存在。

```bash
PYTHONPATH=research python -m rrsnn_v4.restore_delivery \
  --core-archive /absolute/path/RR_SNN_V4_Core_Raw_20261029.zip \
  --resources-archive /absolute/path/RR_SNN_V4_Resources_Raw_20261029.zip \
  --published-paths research/rrsnn_v4/resource_audit/final_restore_published_paths.json \
  --source-commit fa46e1413cdf10402892bd6ca84bf4fbeeae9c9c \
  --destination /tmp/rrsnn-v4-restored \
  --receipt /tmp/rrsnn-v4-restore-receipt.json
```

恢复工具校验调用方提供的 Git 映射，来源 commit 与映射必须先独立核实；checksum 不能代替来源身份。此处提供的映射由本轮远端树核验记录绑定。重新训练或计时应使用另一个工作目录和新的运行收据，不覆盖本轮原始结果。

原生历史构建配置保留实际执行时的机器路径。跨机器重建须按锁文件、精确上游源清单和原配方重新准备依赖，并在独立工作区调整路径；不能把历史配置或所存二进制当成跨平台生产资格。
