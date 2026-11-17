# Run02 冻结诊断接口异常：独立只读审查

## 结论

确认存在 producer/diagnostic 的字典顺序契约 bug。
原 producer 使用经 canonical JSON 序列化再读取的 INPUTS，panel 顺序为 A_retention→B_exposed。
原 diagnostic 重新调用 load_context，panel 插入顺序为 B_exposed→A_retention。
两份字典内容相等、canonical digest 相等，但 diagnostic 用重建字典的顺序严格比较真实 rows，导致六臂全部 UNAVAILABLE。
这不是缺失真实候选、任务覆盖不全或科学 gate 主动否定模型收益的证据。

原始诊断及原源码、规则均完整保留。本审查没有运行模型、测试、verifier、C 或整个诊断。
本审查仅使用 stdlib 读取 JSON、解析源代码 AST 和计算哈希；语义成功字段仍是原 producer 观测，不是重新执行验证。

## 原件与固定身份

以下路径均相对 MacROOT 的 research-final-evidence-02，完整 SHA 保存在 INTERFACE_EVIDENCE.json。

| 原件 | SHA256 |
| --- | --- |
| research-diagnostic-02/DIAGNOSTIC.json | 662f575d3f01705fb13cb6e168ad5d7069a8ddcc81e484f0c515b63afd65236b |
| research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py | 28d82e170ab0720fb6b453275a80b4bf1eebc1e987ed1ae3bd935bb00a77a071 |
| research-diagnostic-v1-source-02/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json | f50ced9146611fc07c4638a35f204e94f1ebf0b5e6c4ab70ac9667095135c1bc |
| research-sft-02/INPUTS.json | 691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3 |
| research-sft-v1-source/research_sft_execution_v1.py | 704e7a7e157412d9ce8a7523c31ed635269ead41d40f1720c591dccc4d67f2cd |
| e1e2-operation-helpers-04/qwen_development_inputs_v3.py | 6bd1b2d71857c5b541ca63ce815cbb05660b75284fc7065e5766e43d910fea20 |
| e1e2-operation-helpers-04/qwen_development_io_v3.py | 4116cfc058cfbec9bdca4845e409d0c1c2071d9da9faa4b56f9d8aa6df5a2060 |

上述实际读取哈希与根交接及 FREEZE 绑定一致；四个 research 模块均按 FREEZE.research_inventory 核对通过。
本次未重新验证完整 ZIP 的 1,687 个成员或模型张量；不继承为全量归档复核。

## 因果链及可复核位置

1. helper04 qwen_development_inputs_v3.py 第 233 行按 B_exposed、A_retention 构造 panels。
2. helper04 qwen_development_io_v3.py 第 56–58 行 canonical 使用 sort_keys=True；第 98–104 行 write_new 写 canonical 字节。
3. 同 IO 模块第 88–95 行 read 使用 json.loads，保留落盘键顺序。
4. producer research_sft_execution_v1.py 第 241 行读经原 SHA 绑定的 INPUTS；第 133、147、173 行取得 panels、按 items 遍历并追加 rows。
5. diagnostic 第 588 行重新 load_context；第 589–595 行以字典内容相等及 canonical digest 核对，未统一运行时遍历顺序。
6. diagnostic 第 413–414 行由重建 panels.items() 展开 keys，并严格与真实 rows 比较，触发同一个 ValueError。
7. diagnostic 第 646–650 行仅在 evaluation 完成后才写 observed；故本次 retained_primary_observation_if_complete 为 null。
8. 第 653 行的 cold 校验尚未进入；第 665–667 行把异常保留为每臂 UNAVAILABLE，不替换失败 slot。

原规则 slot_admission 为 complete_primary_fit_and_evaluation_plus_exact_cold_identity。
“缺证据不可用、失败槽不替换、first/last 分开、原资格为 false”是有意的严格规则，应该保留。
错误发生在诊断器为正确原件构造了不一致的预期顺序，而不是这些规则本身需要放宽。

## 六臂、十二份主评估/冷评估原件

六臂原 reason 全部严格等于 ValueError('evaluation task order or coverage differs')。
每臂 replacement=null，retained_primary_observation_if_complete=null；三 fixed slots、两 baseline、独立 shadow 都受同一问题影响。
十二份 rows 都是 A 的六条再接 B 的三条，和各自 ORIGINAL_PANELS 及冻结 INPUTS 一致。
十二份均无重复 task key、无缺失/多余覆盖、原 panel digest 相同、嵌入 worker 的 evaluation 与独立文件相等，相关 worker EXIT 均为 0。

| arm | 原报告 A | 原报告 B | 冷报告计数 | 覆盖与实际 INPUTS 顺序 |
| --- | --- | --- | --- | --- |
| controlled_correction | 1/6 | 0/3 | 同主评估 | 完整、唯一、顺序一致 |
| final_answer | 5/6 | 0/3 | 同主评估 | 完整、唯一、顺序一致 |
| parent | 0/6 | 0/3 | 同主评估 | 完整、唯一、顺序一致 |
| retrieval | 0/6 | 0/3 | 同主评估 | 完整、唯一、顺序一致 |
| shadow_correction | 0/6 | 0/3 | 同主评估 | 完整、唯一、顺序一致 |
| trajectory | 4/6 | 0/3 | 同主评估 | 完整、唯一、顺序一致 |

这些数字描述已保留旧曝光任务的原观测，不能升格为独立确认、已采用收益或新 C。
原 diagnostic 的第一层顺序拒绝发生在后续原件检查之前；本审查不声称修复后所有后续 gate 必然通过。

十二份 EVALUATION.json 路径模式为 research-sft-02/workers/{arm}-{primary|cold}/evaluation/EVALUATION.json：

| arm | primary SHA256 | cold SHA256 |
| --- | --- | --- |
| controlled_correction | 7273751d0f6fdfaf56c8cfe3c45738cb8c2126d510baccae1e5a60a8474f0a54 | 1f2e10547eaf8acfb05d5529d1184abbcdf563e1f738ac418f0b259a01d3cf51 |
| final_answer | 194c11ce1fcfca32c62130eae2742897abde7bdc667c87cb4000ca22228a7911 | e053a88882bf106f224768991b082973c213199e171baac72e9c1b11eacadf15 |
| parent | fe6160807774a3b59fd122a6e6c96e30ebffbd9f0d71dc2594aee7645465f35f | 7d404f0df177d995ed5332e80958a0c5894491ae8ad9d4560e454ee292cbee07 |
| retrieval | 3ad30e5cc82a0d197cb61c4335390961e05a11cad82f7f8b1069ee8efd245900 | 18f35b95aaac1f6e7fce2beeddd6226389a036dd6bf637165fcf674a754f8957 |
| shadow_correction | 3b1d9395c0c819a410761eb5a849a1fed0723cfe74ae5ae0056a3d0e2f7b4df0 | d80ec7f23f99890657ec234d3a38adce5ee12f9ae1ed40ef63136b1d508ac6d0 |
| trajectory | 7f972d2488d86b9b8f4b97bcfba1db1ab231abceb47410bde29979bc40355fb9 | 26710611b6a332a571b800d37939b1cc178bc2cf4364ecea0fb88150ce911bd8 |

## 为什么 binding_errors 为空

diagnostic 第 614–618 行的 errors 列表只收集 collection_binding 异常。
各 arm 的异常在第 665–667 行写入 arms[arm].reason，没有加入该列表。
所以 binding_errors=[] 与六臂 UNAVAILABLE 同时出现符合现有代码，不能将空列表解释为全部臂通过。
顶层 operation_status 是原运行状态；RESEARCH_DIAGNOSTIC_COMPLETE_UNQUALIFIED 表示诊断输出已完成，不代表所有 slot 可用。

## 最小修复建议

保持原有 context 重建与全部相等、parent、readiness、runtime、admission 检查。
把已按 freeze.inputs_sha256 验证的 INPUTS 保存成 recorded_context，原检查通过后再令 context=recorded_context。
这样下游采用实际 producer 使用的冻结对象顺序；evaluation 的精确 rows 比较和逐 panel 顺序验证完全保留。

```diff
     context = contract.load_context(WORKSPACE, source, baseline)
-    require(reader.read(freeze["inputs_path"], freeze["inputs_sha256"]) == context
+    recorded_context = reader.read(freeze["inputs_path"], freeze["inputs_sha256"])
+    require(recorded_context == context
             and freeze["parent_digest"] == digest(context["parent"])
             ...
             "operation INPUTS or measured baseline differs")
+    context = recorded_context
```

不得改为 set 比较、只排序 report rows、移除同 panel 顺序检查、替换失败 slot，或放宽 candidate/cold gate。
后续协议可显式加入 panel_order 数组；这不是本次最小修复必需项，也不能反向改写 Run02 已冻结 INPUTS。

## 事后重算边界

修复候选必须在独立新目录，以新 source SHA、外层 posthoc manifest 和新输出身份保留。
原 rules 字节、rule_version、schema、slot 列表、scope、阈值与所有资格字段不变。
原 DIAGNOSTIC 的全 UNAVAILABLE 必须与任何后续离线重算并列，不能覆盖、替换或改成“原诊断当时通过”。
原 main 固定 research-diagnostic-02 输出，并用自身源码 SHA 验证原 rules；不可直接以新源码绕过或覆盖该入口。
实际重读需要独立外层入口，先绑定原 rules/source/INPUTS/原诊断和 patch，再使用修订后的只读函数；具体方案由 root 审查后执行。
此时仍不得运行模型、verifier 或新 C；若后续原件校验另有失败，照常保留，不保证 slot 晋级。
离线可用性修正不构成 Circuit 实测、独立选择、新用户/教师/样本、native adoption 或 PoUW 资格。

## 本次执行与产物

- 分析脚本：inspect_interface.py；只读取 59 个指定原件，不遍历全仓。
- 证据输出：INTERFACE_EVIDENCE.json；SHA256 2d96820bd794845872f9c88a96cb1437204c749950aebfca221fa1daea320d6b。
- 真实分析 PTY：dpty-a3818eb3fb8aa2460892f3dfcf47664984f54b47bf9d02b819e957641892ef4c。
- 已观察 exit_code=0、output_complete=true；这是 JSON/AST 静态分析完成，不是模型、verifier 或诊断重跑。
- 单独的修复候选与针对顺序问题的 stdlib 回归另存 operations/research02-diagnostic-order-fix-01，不能冒充本次原诊断。
