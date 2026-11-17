# Run02 posthoc 顺序修复候选：交接与执行边界

## 当前状态

本目录已准备最小修复源码、diff、原件绑定和独立外层入口。
仅完成 stdlib 回归与源码 AST/绑定检查；整个原诊断或修订诊断均未在本阶段运行。
root 审查后负责实际启动、核验与导出；不得把本目录的准备状态算作重算完成。

原始审查见 ../research02-diagnostic-interface-review-01/REVIEW.md。
原始 6 臂 UNAVAILABLE、空 available_slots、binding_errors=[] 原样保留；它们不是“没有实际候选”的证据。
所有新结果仍属旧曝光 A/B 的事后说明，科学确认、Circuit、native adoption、PoUW 资格为 false。

## 最小差异

仅修改 diagnose 的 context 绑定：
先保留 contract.load_context 的重建与所有原内容/parent/runtime/admission 检查；
将原 SHA 约束的 INPUTS 保存为 recorded_context；
检查通过后 context=recorded_context，使用与 producer 相同的落盘顺序。
evaluation、adapter_identity、cold_identity、process_result、规则、scope、原 main 等 20 个函数 AST 未变。
没有 set 比较，没有排序或重写原 rows，没有移除同 panel 顺序检查，没有替换失败槽。

| 文件 | SHA256 |
| --- | --- |
| qwen_research_diagnostic_v1_order_fixed.py | ce0b68cd98673bf15f170d1da7c42670f65320ba5c9d3cacc2f1c28696273821 |
| ORDER_FIX.diff | 29c614601ac0e63d2c2d64bd0c99d817d41bdda065ae3982a1052d28dec819ad |
| POSTHOC_FIX_MANIFEST.json | 3373b6677feacba7206a0b5b545c2dc4cd743b9be12d5e23cdf22e2b1ceed7bd |
| REGRESSION.json | 2e531b414b72382e7afb265179088158142d0de287caba0a69d54e42dfbef62e |
| run_posthoc_readonly.py | d78fd9c8b4c2349303a187a8cd715385c0e42bccd3180a60aea45bd891cd125a |
| POSTHOC_RUN_MANIFEST.json | 147d90e993733c3c998210c55548c15d339a87d661a72bc49b1968bda3936e1c |

## 已实际运行的回归

test_order_fix.py 从真实冻结源码提取 context 绑定、evaluation 的身份/顺序检查前缀和 cold_identity；
在内存 fixture 上运行，不导入实验模块，不运行 semantic verifier。
6 项测试全部通过，含以下拒绝对照：

- producer 的原 canonical roundtrip：原 context 顺序错误被拒绝，新绑定接受正确实际顺序。
- 缺行、多行、重复追加、重复替换、同 panel 内调换任务仍拒绝。
- candidate 身份与 generation 预算改变仍拒绝。
- INPUTS 原哈希失配、重建内容不等仍拒绝。
- cold manifest、PID、primary 回执身份或 cold 标志失配仍拒绝。
- 除 diagnose 外模块节点全部 AST 相同，修复字节只来自声明替换。

回归 PTY：dpty-50779e2a569032996365645cfabeb533766b71e462011d96459de82d42fa488b，exit 0 / output_complete=true。
这是针对接口错误的回归，不证明后续所有真实原件 gate 都将通过。
外层入口只做了 AST 语法检查与 immutable 绑定冻结，尚未执行其 main 或 diagnose。

## 外层入口的身份与约束

runtime workspace 固定为 /dev/shm/hepta-cell-experiments-v3-20261116-0c078a。
本目录 runtime 位置固定为 operations/research02-diagnostic-order-fix-01。
新输出固定为 research-diagnostic-posthoc-02，存在即拒绝；不覆盖旧 research-diagnostic-02。

外层 manifest 绑定原 source、原 rules、study FREEZE、INPUTS、原 DIAGNOSTIC、候选、diff、外层入口、修复 manifest 和回归原件。
原 study FREEZE SHA 为 50a6ad4c3e8088100cc84a047f0556b92294eb3e44dc644e62e2976137c2770a。
原 INPUTS SHA 为 691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3。
原 rules SHA 为 f50ced9146611fc07c4638a35f204e94f1ebf0b5e6c4ab70ac9667095135c1bc。
原 DIAGNOSTIC SHA 为 662f575d3f01705fb13cb6e168ad5d7069a8ddcc81e484f0c515b63afd65236b。

入口不调用原 main，不篡改 __file__，不将新源码冒称为原 FROZEN_PRE_FIT 源码。
原 validate_rules 使用实际原 source SHA 28d82e170ab0720fb6b453275a80b4bf1eebc1e987ed1ae3bd935bb00a77a071；
新源码和 patch 另由 posthoc manifest 绑定。
调用修订 diagnose 后执行 Reader.recheck，再生成新 INPUT_BINDINGS、DIAGNOSTIC 与 POSTHOC_RECEIPT。
内层保留原 schema 和规则，新增明确 posthoc 来源字段；外层收据明确原规则来源、衍生源码及 patch 身份。
失败写入新 FAILED.json，原件保留，不自动重试或承诺 slot 晋级。

CUDA_VISIBLE_DEVICES 被设为空；torch/transformers/peft 的导入被拒绝。
审计 hook 拒绝子进程、网络执行和新输出目录外的写入；原 Reader 的 C/confirmation/sealed 路径拒绝保持不变。
这些是本 Python 入口的防误执行约束，不宣称 OS sandbox 或新的生产权限边界。

## root 审查后的启动参数（本阶段未执行）

先将六个运行所需文件按 manifest 路径复制到目标：候选源码、ORDER_FIX.diff、POSTHOC_FIX_MANIFEST.json、REGRESSION.json、run_posthoc_readonly.py、POSTHOC_RUN_MANIFEST.json。
原 runtime 原件必须仍在原固定路径且哈希一致；缺失即失败，不转换路径或降低验证。
使用原固定环境解释器 /home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python；
参数为 -I -B、固定 run_posthoc_readonly.py 路径，以及 --manifest-sha256 147d90e993733c3c998210c55548c15d339a87d661a72bc49b1968bda3936e1c。

实际重读完成后，必须同时保留旧诊断、新输出、外层收据和独立核验。
同分/成功并集仅是旧任务上的描述性原件汇总，不是学习路由、匹配全成本或新增独立能力的证明。
