# 从初始权重拟合、冻结及双臂冷评的托管复验

在一台 AMD EPYC 7763 的四 vCPU 托管 runner 上，普通 Cell 和带学习路由的双 Cell Circuit 均从初始参数重新执行原始训练。每次得到的两份模型请求都与历史注册承诺逐字节对应。两个 worker 同时运行这两类作业，将训练加冷评的已验证模型对吞吐由每小时 **317.97** 提至 **535.79**，约 **1.685 倍**。该指标包含排队、创建进程、SGD 拟合、保存模型、关闭训练解释器、两臂冷加载和两道题的原件核对。训练内核单独耗时、真实用户扩展及最终采用率仍需各自的测量。

| 预登记区组 | 单 worker 秒 | 双 worker 秒 | 两个在途作业重叠秒 | 单/双耗时比 |
| --- | ---: | ---: | ---: | ---: |
| 先串行后并行 | 22.4927 | 13.2580 | 9.8325 | 1.6965 |
| 先并行后串行 | 22.7973 | 13.6230 | 9.9971 | 1.6734 |

8 个训练任务生成 16 个冷臂、32 个最终答案和 48 次原生模型调用。两种模型对共用一道合成未来题，每个模型对还运行一道合成保持题。父模型在未来题失败、子模型成功，两者都保留原能做的旧题。专用 namespace 在计算前后均只有回环接口，所有计数均为 0。两次并行区组的重叠包含模型载入和等待。每个 worker 档只有两个区组，跨硬件、网络条件、长期学习或纯训练内核的速度需要额外数据。

## 已观察到的复现边界

1. 原共享执行器在训练工序 02 时只有 1/8 个任务完整，另外 7 个收到 SIGKILL。工序 03 在执行器离线前启动，原临时材料在恢复后的任务目录、临时目录和共享内存仍不可用，其终态保留未知。
2. [第一次独立托管复验](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45179956043)的 AMD EPYC 9V74 runner 上，8/8 个原生拟合及配对冷评执行完成，4/8 个任务通过预注册的历史承诺。四次 Circuit 都产生同一个新承诺 `0f46f3ff…`。比较原始 safetensors 后，固定输出头和 LoRA A 一致，LoRA B 八个标量中七个不同，最大差为 1.1921×10⁻⁷。路由系数相同，Cell 和路由清单中绑定的模型哈希随之变化。该试验按原协议无合格吞吐值。机器间观察到的差异无法单独确定底层原因。[首次预登记](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b24f96d742e5c41462f5794d00a77599e1d28407)
3. [第二次独立托管复验](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45180759139)在预先固定的顺序中先以全新进程、原生 CPU 配置执行未计时 Circuit 拟合，第一项就重现了历史 `7d60577d…`。随后单独运行完整 8 个作业并读到上述计时。校准没有更改估分、身份或任务，备用的托管候选没有入选。[第二次预登记](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/38f7a5f15685a84bd06fe8b30a8bbcae8456a1d7)

## 原件和离线复核

| 工件 | 文件数 | 字节 | SHA-256 |
| --- | ---: | ---: | --- |
| HOSTED_RAW_01.zip | 303 | 279512 | `f5430bacba92c23278a8c3b7514751352f21494d67eb8547cf530313dfedb284` |
| HOSTED_RAW_02.zip | 335 | 310341 | `6db1ca259c8973a53824fd2ccc409f098326fa52a48d72f0749b04498d3b1d59` |

包内有每个任务重新生成的权重、分词器、路由、训练记录、两臂实际输出及其哈希、单调时钟、CPU 与网络元数据。标准库复核器对每个包分别读取 168 项模型清单文件绑定、32 个原始答案和所有区组时钟，再用规定的整数语义独立判分。对权重、答案、时间、网络记录各做一种有意修改，四项均被拒绝。以下命令直接对留存材料工作。

```sh
cd qualification/e5-worker-readback-20261123
python verify_hosted.py HOSTED_RAW_01.zip
python verify_hosted.py HOSTED_RAW_02.zip
```

完整逐区组结果见 [HOSTED_01_AUDIT.json](HOSTED_01_AUDIT.json) 与 [HOSTED_02_AUDIT.json](HOSTED_02_AUDIT.json)，逐权重差异见 [CPU_WEIGHT_READBACK.json](CPU_WEIGHT_READBACK.json)。本次真实登记用户、实际采用与新增支付均为 0。每小时实际获采用候选率仍为空值。
