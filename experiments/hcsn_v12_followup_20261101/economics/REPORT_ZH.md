# V12 实际模型执行经济性：固定源码与待执行 CI

本阶段将已经冻结的 16 个 v10 模型接入已实证的 Linux cgroup 计量路径，
不再以分配夹具代替模型。history、GRU、SSM、有限 path filter 使用同一
historical AV 输入、共同 head 和实际 READ/固定及价值策略；filter 另外
执行同权重、同有限物理律的 uniformization/HMM 数值实现，共 20 个 task。
这不是新训练，也不是完整 He–Xiong 核或新独立录制确认。

`model_runtime/export002/CI_MANIFEST.json` 冻结 16 份 NPZ、head、原始 prepared
AV packets、law、来源 PT 身份、原 manifest 和 fresh Torch 参考。部署端
只安装 NumPy 2.3.5、SciPy 1.17.0，不安装或导入 Torch。原端 720 次 NP/Torch
执行和本机 20 个 NumPy worker 的语义证据属于 model_runtime 的独立交付。

`PROTOCOL.json` 预定 canonical 正序、完整反序两轮，共 40 个 fresh worker、
1,440 个实际 episode。每个 worker 在单独新 cgroup 中，从出生、gate/exec
启动、校验和加载输入/权重，到真实策略执行、输出压缩序列化及退出。
测量父进程保持纯标准库，避免前一模型的 NumPy 状态先被 fork 继承；每个
worker 退出后，另启动已等待的标准库 verifier，成本单列并包含在外层
lower-bound campaign CPU 内，不能再与内层 CPU 重复相加。

RSS 资格采用明确受限的 **单 kernel task profile**：只在唯一自有空 parent
启用 cpu/memory/pids，读回 `memory.swap.max=0` 与 `pids.max=1`；拒绝
`pids_localevents` mount。前后要求同 inode、current=0、实际 peak=1、
events.max=0、swap current=0，及唯一根 wait4、正常退出、真实 gate 成员
确认和全部清理。线程同样受 pids 控制器的 TID 约束，详见
[Linux cgroup v2 官方文档](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)。
组织迁入本身可以突破 max，因此还保留实际 peak=1、可信无外部迁入的
profile 前提；不能只写一个 max 文件就宣称完整进程族。

只有该 profile 全部真实通过，才将根 wait4 highwater 记为该单 task 模型
worker 的 family RSS 峰值。它包含出生时继承的轻量父页和入组前 gate
bootstrap；不含组外观察器、verifier、媒体准备或历史训练，也不推广到
任意多进程生产服务。其他情况 RSS 必须为 null，并使专用 CI 真实失败。
已冻结的 v10 meter 原字节不改，RSS 晋级条件只在新的 profile 和审核中
判定，没有将各进程 maxRSS 求和。

cgroup 收费峰值、组内 CPU、根完整 worker CPU、外层 meter wall 和该 RSS
分别报告。共享库/文件页可能已向其他组收费，前组删除也可能向祖先重记；
源码/二进制身份校验会预读文件，两个排序仍共享 host/page cache。因此
收费峰值不是独立冷 RSS 排名，两个样本只作描述性顺序敏感性记录，不做
drop_caches/reclaim，不宣称采用成本优势。能源和缺失的历史准备成本仍
为 null；setup、父测量与 verifier 的边界另列。

质量核验沿用冻结门：类、动作、候选计划、请求及实际费用 exact；输出
概率和候选 probability/score 使用原 `rtol=1e-10, atol=1e-12`，实际输出
SHA 只验证自身字节，不伪造异机最后位一致。CI reference 没有逐值携带
hidden/path 的跨 host 状态门；这些状态的 NP/Torch 验证保留在本机原始
paired traces。资源测量 green 不能晋级原前端质量、D−B 或生产采用门，
全部科学采用标志仍为 false。

本地已实际完成：

- 五项 fail-closed 控制通过，包括错误 head 在建组前拒绝、缺硬件原始
  凭证拒绝、重复模型/额外 TID/denied-fork 不得晋级 RSS。
- sparse source 重建只复制冻结 source 和 4.6 MB bundle，无整仓依赖回退，
  primary 无 Torch 环境实际执行一颗 GRU 的 24 个 episode，独立 verifier
  通过。完整 output/trace、导入来源与费用凭证保留在 `sparse_smoke001/`。
  该 probe lower-bound CPU 为 1.237109 秒，只是源码/依赖及语义验证。
- 独立只读复核闭合 roster 重复、`.so.*` 二进制封印和 push path 过滤缺口；
  新审核还要求 40 个真实 release 时间严格递增，核对实际正/反执行顺序。

新 workflow 只在 `research/hcsn-v12-followup-20261101` 的 model_runtime、
economics 或该 workflow 变化时触发；control/frontend/根报告单独追加不
重跑模型。它固定真实事件 head、精确 sparse checkout、只读权限和完整
包含隐藏源快照的 `always()` artifact。根/既有 job cgroup 不改，无凭证
上传。源码、输入 Git blob/SHA、Python 和 package 内 `.so/.so.*` 身份
保存；未声称封印全部 OS/驱动/硬件。

当前 cloud 没有可写隔离 cgroup，没有重复 EROFS 探针。以上本地门均不
等于真实硬件测量；待发布后由该 CI 实际证明 40 worker、1,440 episode、
单 task RSS/收费峰值/CPU、冻结质量和完整下载归档。原科学采用门继续 HOLD。
