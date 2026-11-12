# run-v2 原入口资产只读核验

## 实际结论与边界

2026-11-12，ai395 原稳定诊断 key `neuro4-rv-v2-entry-assets-read-862531d-v1`、job `1a1cf673fde-2564-1a15` 实际结束：`state=succeeded`、`exit_code=0`、完整持久输出，stderr 0 B。原stdout 19,447 B，SHA256 `6d766ffeda9c1f48be08422f8fb3427ec5430a30a30fb63ccc2f7bf3b3e75d37`；它在保留原JSON数值字节的STDOUT.json中，不重序列化纳秒版本号。

执行的是发布wrapper blob `94e819d579232597de08a5c239a78e9d40768416` 的原始字节（SHA256 `e0800f6e1187a1b2bab532dbd8b1618d200a9cce786f0337d7c13da228beb82a`），核Git blob与SHA256后在内存载入，仅调用原`load_native`与`validate_partitions`。没有伪造本地wrapper部署路径，也没有调用会写文件的`freeze`、`execution_plan`或`run_phase`。原driver、modules、thaw、模型load、collection validator与留存execution plan的原`validate_plan/check_inputs`均使用真实磁盘输入。导入前验证83项原source inventory（82源码、1 receipt）及driver/analysis；共85条预导入核验记录。进程审计禁止文件写入、子进程和网络，未出现被阻止事件；研究actor、collection、fit、export、campaign调用均为0。

## 实际资产

原代码目录：`/home/qq/ctrl-real-policy-20261112-1333-v3`，由原campaign request绑定source `3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd`。本轮逐项核字节pin，未用一次git HEAD查询替代源码闭包。

训练目录：`/home/qq/ctrl-real-study-20261112-1333/run-v2/frozen`。

| 文件 | 字节 | SHA256 |
|---|---:|---|
| CHECKPOINT.json | 11489 | `c4ee4a0219117edeec6381b0bb01b896f9a182862298eba22d3c69a828c17096` |
| CHECKPOINT_PIN.json | 83 | `36a2a8280bbe6045bc4583a888ca0ef73b43ece9b29ed6a17229d2a4dc244fb1` |
| COLD_LOAD.json | 288 | `25484514789cde0458068b940d2a35d77869f60085b1e414417ba9624a4011ee` |
| COLLECTION_PLAN.json | 134361 | `8209340cb8a968ec9b58862782e1bc7ea1619fa82efa83fcc42530e83dfbad57` |
| EXECUTION_PIN.json | 93 | `2ccbee92a62752cc4045b239045adb0a9600785bf918ae1058ba731b487b685e` |
| EXECUTION_PLAN.json | 86017 | `6540ef60ebb14b1be648a43232f7bbde78bd093dd59e180a918a61dc89a007a6` |
| FROZEN.json | 189780 | `7679b083343d6de9d7b3e1f1acc4f3252b044de36deafadb289ff532c7de7497` |

留存execution plan的canonical digest为 `1a002fdff92d0c674dae5c741ba09bf7b42053856a7c1dd72eaad0a553323e7f`，对应已存在的48 context × 6 arm = 288计划项；本轮没有重新执行这些项。所有六份原deployment仍逐字包含同一外部固定checkpoint。

`FROZEN`与checkpoint SHA来自先前保留的外部pin；collection raw SHA来自该FROZEN；CHECKPOINT_PIN与COLD_LOAD文件raw SHA另与先前GitHub归档原件核对。source/weights/control/exposure SHA均从外部固定FROZEN传递。EXECUTION_PLAN/EXECUTION_PIN及原deployment另做实际留存对象的结构、谱系、canonical digest与checkpoint/context关系检查。它们的首次文件raw SHA是本轮观测值；STDOUT中这些行的`expected_sha256`记录最终重读时的稳定性比较，不应误称另一个外部授权pin。所有观测文件在原API校验后再次核完整字节与dev/inode/size/mtime/ctime。

真实weights为 `/home/qq/ndu-real-runtime-20261107-bc2efaf10cd0/pilot-run-v1/models/common-collector-content/weights.pt`，72,247 B，SHA256 `db6e3d05270163368d10176299a7d5be3ccee2d8e773fcfbb32454ff1c0f9f54`。control为 `/home/qq/ndu-portfolio-frozen-20261109-eb02e89/preparation/control-plan.json`，SHA256 `74066034f59241184a98e04c1171af08ba1ff7e4a91e77391b2b5a0c07b68426`。原exposure ledger SHA仍为 `6722edfc88e1089bcaf0fba9727c233416830fdc6682b461422d26bdfd4cb6af`。完整路径、pin与source闭包在STDOUT原件。

Python仍是原配置的 `/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python`（解析为CPython 3.12.16路径）；原FROZEN未给Python binary外部期望hash，本轮不将路径一致冒认其签名认证。

## 尚未满足的最小入口条件

1. 将原wrapper字节物化到新独立代码路径，并登记原字节hash；生成外部固定的正式request，包含上述repository/training_run/freeze/checkpoint、两个development阶段的完整case/seed roster与预先选定的`minimum_observed_gain`。
2. 在全部actor可读runtime roots之外，选新create-only output。由原wrapper `freeze`实际生成两阶段deployment、B_PLAN/C_PLAN及wrapper FROZEN，并保存原始hash；本轮没有生成这些对象。原B/C阶段仍需要自己的START/TERMINAL与真实调用，不能从本次load/plan检查推导已执行。
3. 本次仅从原16个已经暴露的development来源中取两个不同来源作为只读partition兼容性输入，实际源集为train24/cal18/B1/C1。该选择未注册成研究计划，不新增独立来源资格、owner授权或功效。
4. 原`check_inputs`通过不等于本轮重读了所有public packet或private reference正文。只对一个reference做stat（787 B匹配）；其正文与hash未重读。未来实际执行继续走原材料/隔离/观察前置，不得跳过。

原参数action40、READ30、finalizer5、episode wall60、alpha0.1、ridge0.001、latency weight0.01均未变化。模型仍fit24来源/cal18来源、`calibration.complete=false`、`full_cost_observed=false`。所有研究结局保持 **HOLD_NOT_EVALUATED**，`owner_decision=null`；这不是Root重启、普通owner裁决、独立B/C验证或效益通过。

## 原读取故障与取回

第一次直接process_read为MCP timeout，保留该工具错误；它不表示诊断失败，未重新派发进程。随后用同job只读async process_read，原SDK首包51,859 B、尾包9,987 B、status包912 B均完整解码并核SHA；stdout按0→16384→19447原字节游标拼接。原status确认无截断、完整持久、未超时、未取消。
