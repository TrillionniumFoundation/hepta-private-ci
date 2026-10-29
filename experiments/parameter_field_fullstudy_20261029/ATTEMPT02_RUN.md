# Attempt02：冻结入口与续跑条件

当前状态 **ADMISSION_BLOCKED**。本说明对应固定科学协议、操作修订和原路径布局；不是已经完成实验的证明。先看 [EXECUTION_STATUS.md](EXECUTION_STATUS.md)。

## 已登记身份

| 登记 | SHA256 |
|---|---|
| OPS_ATTEMPT02.json | `583b3f8c7866b2d2a289e32cc9162472fd23ddc0b7897d0066863fd427173dd3` |
| A attempt02 freeze | `39dee8b18a258cfd5ddf526333a259ebf9093ffb7d4ef34ffe2e643ffda73346` |
| C attempt02 freeze | `124e2263b2f4cce56a69bb98156536a983080974a54e6b6a3a9eaa0130737d23` |
| Controller freeze | `c7e3e66fab26d744e100f2bd667b2089e216b05a07d2caf4f012c1c574e7572b` |
| Initial queue | `a983f2113261999a2e8c9c972a9fc88346987831b456392e27e66ffd07dd6d67` |

上述 freezes 注册源码提交 `487c42dbe90eaa983496afbd35edde5eaf55fe66`。后续提交的文档、状态报告或独立 finalizer 文件不改变这些已冻结代码。

## 当前环境中的实际入口

只有当前资源门允许时才能启动。不要裸执行 worker 命令：A/B/C/R 和 endpoint 会等到 controller 已把本 PID 与内存预留写入 ACTIVE_WORKERS 后才导入 Torch。

```bash
env PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime:/dev/shm/hepta-field-fullstudy-20261029/source \
  python -B -m experiments.parameter_field_fullstudy_20261029.launch_v2 \
  --root /dev/shm/hepta-field-fullstudy-20261029/attempt02 \
  --queue /dev/shm/hepta-field-fullstudy-20261029/queue_attempt02.json \
  --freeze /dev/shm/hepta-field-fullstudy-20261029/source/experiments/parameter_field_fullstudy_20261029/registrations/OPS_ATTEMPT02_SOURCE_FREEZE.json \
  --amendment /dev/shm/hepta-field-fullstudy-20261029/source/experiments/parameter_field_fullstudy_20261029/OPS_ATTEMPT02.json \
  --amendment-sha256 583b3f8c7866b2d2a289e32cc9162472fd23ddc0b7897d0066863fd427173dd3
```

初始队列为 A-17、A-29、A-43、C，最多两个 worker。每个 job 的 actual freeze SHA、协议 SHA、阶段/seed、完成路径与操作修订都要匹配。现已完成一次无 Torch 的完整静态身份校验，但实际 RAM 准入拒绝；因此上面命令尚未启动新的训练。

如果 controller 在零科学 worker 的情况下持续 300 秒无法准入，会写 `controller/ADMISSION_FAILED.json` 并退出 75。资源改善后可以在同一命令末尾添加 `--resume-admission`；它只接受同一 queue/source/ops SHA、没有任何科学 job START、没有活动 worker 的纯准入等待，旧控制器记录会被保留。已经启动过科学工作后的失败不能用这个选项当成无状态重试。

## 后续有序阶段

1. A 三组全部完成后，核对全部 parent/branch/head/path artifact；用实际 A head/hash 完成 B、W、R 的各自输入/source freezes。
2. B 使用原 A heads，运行固定 16 个新 schedule 与五种方法。没有重新拟合、调参或增加 seed。
3. W 使用固定 parent，R 重构全部 576 个 terminal。R 可用两个槽，但不与其他科学 writer group 混跑；W 单独执行。
4. A/B/C endpoint scorer 的 freeze 必须绑定对应实际 attempt02 training parent、完整 checkpoint 人口和操作完成凭据。B 仅在此后打开 qualification；C 仅在此后打开 final。
5. 完整结果汇总使用原 verified loaders 和原 `analysis.summarize`；完整汇总需要进入已准入的分析进程。BLOCKED 状态报告不导入 Torch，也不打开效用 artifact。
6. 全部控制器与 worker 停止后，才登记 finalizer freeze。其 `artifacts` 与 `required_scientific_seals` 必须绑定全部科学完成清单；逐路径真实恢复验证只证明容器字节身份，不能替代科学完成门。

当前 B/W/R/endpoint/finalizer 的实际输入 seals 尚不存在，不提供虚构哈希或可绕过这些门的占位执行冻结。源码已经实现；实际完成状态继续由生产者生成的凭据决定。

## 环境变化

如改用其他路径、执行环境或储存介质，需要新的明确操作登记与对应 source freeze；原科学协议、样本、动作、head 训练规则、CI 和阈值继续固定。原模型、observer、MNIST 资产需要逐文件匹配已有恢复清单。外部 raw 数据保存仍遵守既有目的地授权，不能通过新 runner 隐式绕过。
