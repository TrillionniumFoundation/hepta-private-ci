# 真实 tiny-sd 单批训练与独立进程复载

本轮固定执行源 `fdbbfdbe582b2de80077236c8f2f0ab8fcbe76c3`，tree
`78b4a64fc4b8fb19c68d6947b47dd4c1fb7481e9`。在 ai395 上仅启动了一次
development fit；没有重新运行 R1 或开启确认性四臂训练。

## 已实测通过

既有 tiny-sd 原始模型、配置和输入先核对完整 SHA256。对已暴露的 R1 bee
开发图片，真实执行 FP32 VAE 编码、文本编码、epsilon denoising MSE、backward
和一次 SGD 更新。更新的 11,524 个参数仅属于 UNet `conv_out.weight/bias`；
其余 356 项 UNet state、248 项 VAE state 和 196 项文本编码器 state 全部不变。
实际 loss 为 `0.0031462120823562145`；没有把单个 loss 当语义质量或收益。

保存 safetensors 参数、SGD momentum、RNG、完整前后张量清单及固定来源。
另一个实际进程重新装载原模型和候选，输入批次与更新后噪声预测哈希完全相同，
随后通过实际 pipeline 完成 12 步、256×256 RGB PNG 生成。输出不是独立评分。

| 项目 | 固定 SHA256 |
| --- | --- |
| checkpoint manifest | `08baf9f92dd3df7872968503006638495f8f8dc8242eee1e401df91e14e0bc6a` |
| 实际参数 delta | `60d71a954f7a92a4c8b2c8d5a9a2127269863662d3bce9c8e4a6cf0d7674da73` |
| fit 终态回执 | `4e1752d9c6830d74807856685594c55fcfbd0e46033b10bff03f4da332d2e74f` |
| cold replay 终态回执 | `5c09efc61064d34fa12f8d7f569040a92cb9ba4836966c4554e7930274a1a1af` |
| 生成 PNG | `6ee1ef2482613ff28071bc5e2bf24389f65192924ed0b960e6b68e53347364f1` |

## 实际成本

| 独立物理子进程 | 全进程 CPU 秒 | 全进程 wall 秒 | 峰值 RSS bytes |
| --- | ---: | ---: | ---: |
| 单批训练、校验与保存 | 11.459588 | 10.581983571 | 2,846,990,336 |
| 冷装载、数值重放与 12 步生成 | 32.325550 | 20.601632982 | 2,916,818,944 |

两个互不重叠子进程共 43.785138 CPU 秒。表中外部包络包含子进程 import、
退出和写盘，不再叠加内层 `RESULT.json` 的包络。supervisor CPU、包打包成本
另列。块 I/O 操作数保留，但不能自动当成实际磁盘 bytes；文件大小是逻辑保留量。
能耗、网络流量、历史模型获取、工具分派/传输、agent 与发布完整成本仍未知。
本轮测量不能替代 32 seeds / 96 trainable fits 的总预算或推断完整研究净收益。

## 独立审查和真实原件

`REVIEW.json` 及三次原始日志保留第一次 12 pass / 1 fail 的拒绝后部分修改
缺陷。修复后，最终固定源的六文件隔离快照 13/13 通过；不累加重复测试计数。
独立实现审查来自共享工作区的另一 agent，不是独立评价 custody。

`EVIDENCE.tar.gz` 含 23 个原始运行文件及 `EVIDENCE_INDEX.json`，包括完整
checkpoint manifest、delta、optimizer、PNG、stdout/stderr、plan、源码和终态。
归档 256,488 bytes，SHA256
`6c004f7c3e822c7c161ad4e918f0f07a0da9b55f1d5ae3b03d341a258d02890a`。
已按固定版本分块读回，并逐一复核全部原始文件大小与摘要。

## 仍然开放

这是一个真实生成器更新和复载机制闭环。完整 `REAL_TRAINER` 还需实际控制器
标签、完整 fit、配对初始化和冻结组四臂执行；新来源簇、独立评价权限边界、
数值总预算及强基线、质量下限和功效、完整候选选择身份仍未完成。
这份开发候选不能替代确认性候选，不能改变 incumbent，也不产生产品晋级。
