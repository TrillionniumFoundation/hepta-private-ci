# ACT caller 检查预算修正：单行候选，尚未发布/执行

候选 commit 5fc34e1ac0f1cf7e98162c210414ad72845a6b4c，tree 35d5a86106db8ced1c71ff447546cb9375f1ee47，唯一 parent 7d31bf9677748330ae17efe964de48d98ba5e542。GitHub commit 原文已核只有 .github/workflows/hepta-act2-notes-seed-product.yml 一行 120 → 4800；没有移动 ref。产品、checker、CALLERS、保护文件、六个测试方法和失败处理字节均不改。

## 原始失败

v1 job 1a1cf8ed400-2564-1a56 在官方 V8 checksum 下载 RemoteDisconnected 前置失败。连接诊断随后同 Python/同 URL/无代理取回 HTTP200、262B、官方 SHA6774b42c…，没有源码或 TLS 修复。

v2 job 1a1cfa11c7d-2564-1a72 的原 V8 resolver 实际 exit0/23.801552831195295s，随后 rustc verbose exit0。原 caller receipt 明确 timed_out=true、returncode=-9、exit_code=124、elapsed_seconds=120.05062907584943、0字节原日志；总 TERMINAL 为 FAILED，13,722 tracked files 前后相等。编译、六个Rust方法、format未开始。该超时不能推导完整 caller 会通过，所有原失败保持原样。

实际 V8 pair 由原 resolver 下载/校验；其记录和两个实际文件的 file_info 均与官方发布一致：archive 29,366,352B / a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583；binding 39,884B / 7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506。不以任意外部包或环境 override 代替原校验。

## 预算来源的精确区别

| 固定来源 | 可核事实 | 不能外推 |
| --- | --- | --- |
| #6127 base b028 / ACT workflow blob96732bf75ef5ca0594250473755273d132de7c11 | 原workflow没有caller步骤；120s由本轮8514新增 | 120s不是最初#6127既存语义或科学阈值 |
| 7d31 architecture workflow c1490cedf609e35ab0b2115f5e01c5987583c353 | job60min；调用 hepta_ci_exec 未写 timeout 时原默认3600s；无独立caller步骤 | 不能声称该文件有4800s caller门 |
| 7d31 gap-agentd workflow18a6d4e1108482653ff7560d9e64d91649e41236 | process job90min，直接 just test；无独立caller步骤 | 不能把整job预算写成caller预算 |
| owner620 workflow72d4b247d90dde972ac592b2d568cd6e470f97ff | caller job100min，原循环self-test300/verify4800；源码注释说明未缓存曾25min | 该文件不在7d31树；这是已有专用caller预算的工程先例，不是同源运行证据 |

owner620 的 typed helper e23bb8…与7d31逐字相同；verify主脚本 c66fb1…与7d31 d7a698…不同，因此不借用其结果。本修正保留原7d31 checker及参数，给完整库存扫描一个有界执行预算；没有删除、跳过、替换任何边界或把失败改成功。

## 候选 v3 请求

DRIVER.py 相对已审 d5f9311b…仅将 caller timeout literal 改为4800；PLAN只随新commit/tree、对应workflow pin和独立output目录变化；request只随上述字节与新key变化。build3000s、两个test各1800s、minimum1/5、每名PASS恰一次、0失败、源码前后、原逐字receipt、format和retries0均保持。整个任务仍5400s、2线程/200%CPU/32GiB。各阶段预算不会延长全任务上界。

新key：neuro4-act6243-native-5fc34e1ac0f1-862531d-v3。输出：/home/qq/neuro-act6243-native-862531d11598/5fc34e1ac0f1-v3。此请求 **NOT_DISPATCHED**；须由root发布候选并核对新的hosted运行状态后才一次受理。没有额外完整caller诊断。若新完整caller产生逻辑错误，原失败仍阻止后续build；不得把本次预算修正当验证已通过。

所有结果只属普通账号验证。owner_decision=null；不赋予Root/生产资格，不证明学习收益或独立研究确认。
