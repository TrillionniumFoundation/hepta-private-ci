# Run02 controller 对账 v2：增量静态复核

## 结论与范围

**v2 已在 postrun 准备阶段补上上一版所缺的 owned 完整回执链与逐 LAUNCH 终态覆盖，未发现本次增量的静态阻断。**它继续保留 controller lost/incomplete 原观测；没有将这些状态改写为 controller exit0。实际 Mac launcher 的远端引导源码也确实在 exec owned02 之前应用 freeze.environment。

本次只读取并比较固定源码，未读取活动 Run02 输出、原 controller observation 或任何运行结果；未执行 preparer、runpy、launcher、wrapper、归档、模型、tests、verifier 或 C。以下结论不表示研究已结束、GPU 环境已实际设置、诊断已运行或零模型调用已获得实际终态证明。

## 1. runpy 的执行边界

v2 先核对 Desktop archive03 的完整 SHA 为 251e08cae5fb55df3872ab45619e1b22d0177a0c8d1a0b8b200ddcfd237ab462，再使用 runpy.run_path(..., run_name="hepta_research_archive_readback")。

该固定 archive 源的顶层只有标准库导入、常量与函数定义；调用 main() 的唯一顶层入口在 if __name__ == "__main__" 中。所指定 run_name 不等于 __main__，因此此路径不会执行 archive.main、生成归档或加载研究/诊断模块。v2 随后仅调用 owned_receipts、read、canonical、checksum、process_observation；这些固定函数读取回执、文件哈希及 /proc 状态，没有模型、tokenizer、训练或业务 verifier 调用。〔P2·remote；A·模块顶层及相关函数〕

## 2. owned 完整链与原 launch 的绑定

v2 保留原 wait_returncode=0、原 child/wrapper PID 不存在、study freeze SHA 和同一 Linux boot 的检查，再调用固定 archive 的 owned_receipts(owned-research-sft-02, "research", prior["argv"])。

该函数验证 INTENT/STARTED/EXIT 的 schema、role、operation_key、相同 argv、INTENT→STARTED→EXIT 的 SHA 链、child_identity 一致、整数 wait_returncode、exit_source="subprocess.Popen.wait"、真实 stdout/stderr 字节，以及 child/wrapper 的 fresh stopped observation。v2 另外要求真实 wait=0，并把 owned intent 的 freeze_sha256 与原 launch freeze 实字节相等、entry_sha256/wrapper_sha256 与 prior 对应字段相等作为继续条件。〔P2·remote；A·owned_receipts/process_observation〕

这些约束绑定实际原研究操作；owned wait=0 仍只表示协调器真实返回，不被用来宣称各 fit 或业务任务成功。

## 3. 逐 LAUNCH 覆盖与 closure

新循环遍历 research-sft-02/processes 下每个现存 */LAUNCH.json，已不再只遍历已有 EXIT：

- 验证 LAUNCH 的 argv 类型与 automatic_retry=false。
- 要求 EXIT.json 和 INTERRUPTED.json 恰好存在一个；缺失或同时存在都会拒绝。
- 要求 terminal 有正整数 PID、整数 exit_code；EXIT 进一步核对 receipt seal 及 stdout/stderr SHA。
- 对 terminal 指向的实际 worker PID 调用固定 process_observation，并要求 stopped=true。
- 记录 launch 路径/SHA、terminal SHA、原 exit_code 和 fresh stop 观测。非零 worker exit 保留原值，不会改成成功。〔P2·remote worker 循环〕

“全部覆盖”指所有现存 LAUNCH，而非预定十三阶段均已执行或成功；失败 primary 导致 cold 不启动仍按原协议保留。该覆盖不能被解读为新增样本或新增成功。

检查全部通过后，v2 以 create-only/fsync 写 RESEARCH_TARGET_CLOSURE_READBACK_02.json。它包含固定 archive validator SHA、owned EXIT SHA/真实 wait、双进程停止观测、worker 身份/终态、原 controller status 与 controller_status_rewritten=false。closure 的实际大小和保存时 SHA 被加入 postrun freeze.immutable_inputs；原 observation、研究 FREEZE/RESULT 和 owned 三段回执及双日志继续进入 immutable_inputs。owned02 在实际启动前会逐项复核这些大小/SHA；最终 archive03 仍独立重新验证并保留此链。〔P2·remote；W·main；A·writer_evidence〕

## 4. 环境传递的源码事实

实际 Mac launcher 的远端引导先核对 postrun freeze SHA，再执行 f=json.loads(raw); os.environ.update(f["environment"])，随后 os.execv 固定 HOME Python 和 owned02 的 postrun 角色。execv 继承该远端进程的环境；owned02 随后 os.environ.copy()，仅覆盖固定缓存路径，没有覆盖 CUDA_VISIBLE_DEVICES。因此，从这两份固定源码衔接看，freeze 中的 CUDA_VISIBLE_DEVICES="" 会沿该启动路径传递给 postrun 子进程。〔L2·remote；W·main/run_owned〕

这补齐了上一版“owned wrapper 自身不应用 freeze.environment”的调用方上下文。它仍是源码判断，不是实际子进程环境或调用计数回执；不能提前报告 GPU 已屏蔽或诊断零调用已完成。

## 5. 增量边界

精确文本比较确认：与 b51fe2f1… preparer 相比，外层 Mac 代码、postrun argv 和 freeze 构造行不变；新增的是固定 runpy validator、完整关闭链 readback 与 closure immutable 绑定。control_observation 仍只赋值一次，worker 的 child/body/v/channel/stop 不覆盖它。实际 archive03/owned02 源码未由本次复核修改。

create-only 目录/observation/closure/freeze 仍可能在后续检查失败前留存；出现失败需先对账原件，不能盲目重试。最终导出、每个实际步骤的状态和所有资格继续由既定原件与规则决定，本静态复核不替代它们。

## 源码身份

根目录：/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a。P2 与 L2 本次完整读取；A/W 使用上一轮已完整读取、且与 reschedule 部署清单匹配的固定字节。

| 标记 | 相对路径 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| P2 | operations/prepare_research_postrun_reconciled_v2_02.py | 8139 | 1fee4e0e8cf0ce842ea1ef5e23857e8431c73100a351645de82de406cfc8ee35 |
| L2 | operations/launch_research_postrun_02.py | 1022 | 7306a67056882bee21dda8628a623df25c4e4a2b602ec9233169a4ac516d69a4 |
| A | research-reschedule-source-02/operations/archive_qwen_research_v1_03.py | 20170 | 251e08cae5fb55df3872ab45619e1b22d0177a0c8d1a0b8b200ddcfd237ab462 |
| W | research-reschedule-source-02/operations/launch_qwen_research_owned_v1_02.py | 9063 | 205a72dbe8adab915c8f7c9225a3d4effb0f399f80ba167cd5786213aa7eda00 |
| P1 | operations/prepare_research_postrun_reconciled_02.py | 5849 | b51fe2f1e6646e1737ab98ff37d06414a6d3ba716892bb5edd1de9ba776b7efa |
