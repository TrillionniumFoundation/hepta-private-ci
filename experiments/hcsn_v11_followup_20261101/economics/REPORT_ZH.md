# V11 独立 CI 计量：真实硬件路径待执行

本阶段基于冻结 v10 提交 `89d5bc70fed536948949e5ed91d3b5c097fd127a`，
仅新增专用研究 CI 与独立标准库审核，不修改 v9/v10 源码或本机控制器。
工作流为 `.github/workflows/hcsn-v11-cgroup-economics.yml`。
冻结 v10 的远端映射现已成功：PR #4590，远端 head
`eaaf9d97107b35fb831ecc30bc6b70a10b458ab2`。原发布回执逐字节复制到
`../baseline/v10_publication_result.json`，没有改动 v10 原文件；附有 SHA
和本地/远端 source 映射。

只允许指定研究分支的 push，及同仓同名来源分支的 PR 触发。Ubuntu job
最长十分钟，只有 `contents:read`；未引用仓库 secrets，checkout 不保留
凭证。checkout 固定事件真实 head SHA，PR 不将 merge-ref 当候选身份；
使用 blob filter 与精确 sparse checkout，避免下载整仓证据。checkout v4
和 artifact v4 均固定本次官方 tag API 返回的完整 commit SHA。

`ci_driver.py` 用 sudo 提供的 runner root 权限，在 `/sys/fs/cgroup` 下
创建唯一自有空 parent，只在该空 parent 启用 cpu/memory。没有修改 root
或既有 job 组的控制器，也不移动 job 的进程。缺少父级委派、控制器不可写
或无权创建时必须真实失败。清理仅针对该自有 parent，核对 inode，终止
其后代并要求空组删除；最后写入 `CI_RESULT.json`。

在该 parent 实际调用未改动的 v10 `runner_campaign.py`，执行正常四进程、
收养四进程、非零 payload 和带后代的超时四组。独立 `audit_ci.py` 只读取
identity 与原始 campaign 文件，重算源码 SHA/Git blob、解释器身份、进程
生成/收养关系、CPU 与收费峰值、退出和清理条件。父 parent 的最终删除在
审核后执行，必须在下载后的 `CI_RESULT.json` 中另外确认。取消的 push
attempt 与后续 PR attempt 不可合并冒称一次成功运行，也不能把取消成本
记为零。

artifact 使用 `always()` 保存成功和失败的原始输出、全部 tested source
快照、源码/输入 Git blob 与 SHA、checkout 身份及 Python 二进制身份。
不会仅因七项本机 gate 检查通过就让硬件 job 变绿。现有 v9 收养夹具的
实际父身份仍须通过原始记录验收，未预设结果。

本地实现 commit 为 `b9d0d3d4a9ea573c9b666584c35b1d263625e8d2`。
`LOCAL_VALIDATION.json` 记录六项 prelaunch 检查全部通过：真实已提交源码
身份、错误 head 在创建组前拒绝、缺少实际证据的审核拒绝、actionlint、
Prettier 及 diff 检查。另有继承的 v10 真实 gate 控制 7/7 通过、零跳过；
原始日志为 `GATE_CONTROLS.log`。本机没有重跑 EROFS 硬件探针，没有执行
成功内核 campaign。最后仓库 formatter 的独立结果另存。

严格口径保持：cgroup `memory.peak` 是层次内存收费峰值，并非完整进程族
RSS 连续峰值、物理唯一页或完整部署内存；共享/已有页面可能由其他组收费。
CPU 计数也不含组外 gate 启动、父计量器或历史准备。完整族 RSS、可归因
焦耳与历史成本继续 HOLD，实际 CI 完成之前连该隔离收费指标也仍未通过。

root 将发布本分支触发实际 CI，并检查精确 head 的四组原始 artifact。
本文件是可复核的预执行交付，未声称 GitHub Actions 已成功。
