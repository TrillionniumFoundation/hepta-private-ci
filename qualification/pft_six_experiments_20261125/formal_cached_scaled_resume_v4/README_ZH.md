# Formal cached_scaled：固定 N8 冷恢复

本次唯一原生执行 **PASS**，补上旧 `plain_linear` raw 测试未覆盖正式 `ScaledReadout` 的验证缺口。原结果见 [RESULT.json](RESULT.json)，完整原输入、源码副本、状态与过程回执见 [归档索引](FORMAL_EXECUTION_01.index.json)。

## 实际结果

| 项目 | 已观察结果 |
|---|---|
| 固定候选 | `n8-s2101-value_risk-full-learned-m64-lr1e-05` |
| 模型 | `cached_scaled`，N8，20 维 readout，`slow_every=2` |
| 路径 | 完整12步，对比全新进程5步＋另一全新进程续7步；batch=2 |
| 七项比较 | logits、features、density、boundary、drift、cost、message：max absolute error 和 tolerance ratio 全部为0 |
| 原数值门 | `rtol=1e-11, atol=1e-12`；完整 config、step、source/runtime 身份同时核对 |
| readout | mean/scale 为已加载 buffers、scale 全正；四项前后不变，三个进程完整模型 digest 相同 |
| 规模 | 3次模型构造、3次forward、24个批次步／48个轨迹步；另4次动态状态反序列化 |
| 耗时 | wall 3.422189263秒，CPU 3.068182秒；原总上限180秒／150秒 |
| 优化活动 | 0 gradient steps、0 seed searches、0 retries；没有重新拟合 |

原 runtime：Python 3.14.4、NumPy 2.5.5、Torch 2.15.0+cpu，CPU threads=1、interop_threads=1。初态、完整终态、cold5、cold7 的五张量状态及完整身份均已保全；step5 的控制状态延续至下一次刷新。

## 原字节保全

- 原 RESULT：3041 bytes，SHA256 `1cdd16c9bea2fe0480930659b91d9297923922d5958b65ea5144906d23d128fc`。
- [FORMAL_EXECUTION_01.tar.xz](FORMAL_EXECUTION_01.tar.xz)：56340 bytes，SHA256 `5aafeb2c424f83641b86fc2ad9aa39f75417ab18475126be8bedd3b7e73fb6af`。
- 索引登记37个文件、解压文件总量261106 bytes；原37/37成员已独立逐项核对。
- 已执行 registration SHA256：`d71cbd729b44b4841b79b1c2efb1c3bf81a38d68a98f9c3fc2c8bd3030c81a2f`。
- runner SHA256：`2edbbd202003fd2dd31c4f0c141e89de2ff0889ea116e8d69f942e265d939983`。
- 归档完整保留原 registration、stimulus、六个helpers、旧静态README、原 raw 参考材料、全部执行状态与回执；没有重写原JSON或缩减源守卫。

正文 RESULT 是归档 `execution_01/RESULT.json` 的原字节镜像；其中工件相对路径以恢复后的 `execution_01/` 为根。旧静态README记录执行前状态，实际结果以原 RESULT 为准。

## 精简仓库布局

本目录正文仅保留 `run_formal_cached_scaled_resume.py`、`FORMAL_PROFILE.json`、本README、原 `RESULT.json`、原 `FORMAL_EXECUTION_01.index.json` 和二进制归档。完整 registration/stimulus/inputs/logs 通过归档逐字保留；六个既有helpers不作为新增源码重复发布。

源基线固定为 `f9b4cdb63261c5531ac255a4f7b270893c828323`，原目录前缀为 `qualification/pft_six_experiments_20261125/`。旧 `PARENT_PROFILE`、raw 测试、物理/科学源码均不改。

## 只读恢复与核对

1. 在新的隔离目录核对本归档字节数/SHA，按索引有界读取37个普通文件；拒绝绝对/上行路径、链接、重复路径和超出登记大小的成员；逐项核对 bytes/SHA后恢复。
2. 恢复原 `REGISTRATION.json`、`STIMULUS.json`、`FORMAL_PROFILE.json`，以及 `source/native_profile_v4/`、`materials/`、`execution_01/` 的原相对布局。归档不包含重跑许可。
3. 六个helpers也可从精确f9树独立重建到另一空目录；逐一取得以下文件，输出到 `source/native_profile_v4/<文件名>`，再按原 registration 的 source_pins 核验 bytes/SHA，并与归档同名文件逐字比较：

```text
bounded_process.py
numeric_runner.py
prepare_profile.py
profile_io.py
small_hcsn_profile.py
source_binding.py
```

每个文件的精确读取方式为 `git show f9b4cdb63261c5531ac255a4f7b270893c828323:qualification/pft_six_experiments_20261125/native_profile_v4/<文件名>`。只向新空目录写入，不覆盖恢复件、不运行formatter、不修改hash守卫。

4. 从同一f9树取得原 `actual_hcsn_v2/evidence_archives/formal_v2_training--n8-s2101-value_risk-full-learned-m64-lr1e-05.tar.xz`：67748 bytes，SHA256 `fc08810629102cdd97e2a81a6441bf9c7cca4d4826d84a6a909cc3dcb68691be`。保留为 `materials/archives/formal-candidate.tar.xz`；仅取其普通成员 `formal_v2_training/n8-s2101-value_risk-full-learned-m64-lr1e-05/candidate.pt`，放到 `materials/checkpoint/candidate.pt`。
5. candidate.pt 必须为33078 bytes、SHA256 `2eeda94ea29a02119b8d7b73b2f1c355e9a052a802a5867ca5092782adc44513`。恢复不需要调用torch.load。
6. 从同一f9树取得原 `actual_hcsn/runtime_capsule.tar.gz`：406079 bytes、SHA256 `7ebe8aed55ce2e209f8be5dd016b4b13a8bb3fe6243b918d9648dd9a7114fe96`，保留为 `materials/archives/runtime_capsule.tar.gz`；按原 source_provenance 和 `PHYSICAL_SOURCE_REQUIREMENTS.json` 恢复/核验25个物理源到 `materials/capsule/src/`，不得换用近似upstream文件。
7. common.py、optimized.py、protocol 和 provenance 已在本次保全归档的 `materials/` 中。最后对原 registration 全部 source/material pins 核对；不把材料恢复当作新的模型执行。

## 结论边界

本轮已消耗唯一执行，**不要重跑、重派、扩大预算或更新已执行registration/源码**。归档恢复与字节核对不会新增模型调用。

结果只支持这一个正式checkpoint、这一个无标签刺激和step5截点的冷恢复等价；不外推到其他checkpoint/时钟、连续时间重采样、模型效益、完整科学资格或生产准入。原结果的 production_adoption、real_cross_user_acceptance、scientific_qualification_transferred 均为false。
