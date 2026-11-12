# B/C 开发生命周期：正式 freeze 请求与一次性运行器

## 当前状态

本 bundle 只准备可审查的请求与源字节。**尚未派发 h 请求、freeze 或 actor；Python 语法、格式和运行验证均未执行。** 本次正式请求的唯一 stage 是 freeze，不包含 B/C 调度。未来 B/C 仍须 Root 核实际 freeze 原件后分别决定是否派发。

| 对象 | 精确身份 |
|---|---|
| Runner | driver.py.txt；Git blob d63ff1216eafcc5b4dfdd98c03a83972b268b25e |
| Runner SHA256 | e3d1e81c3f73cc748a197d31998c565e1afdbc5f879013f46d43edf408e0f3fb |
| 正式 h 请求 | FREEZE_REQUEST.json；Git blob 95156b8e5a021af195a9d6f07d4d68e58ad006cd |
| 请求 SHA256 | 7eb1d14b658ffbf940395d441050e952cf1e61148fad2915bd16659c7a7cac5a |
| stdin 原件 | FREEZE_STDIN.json；SHA256 0531a24d5b61d343dd8b338a2793bdf78c0b37fc0f8ee60cfffda70f75d1b91d |
| 固定首次 key | neuro4-rv-bc-freeze-862531d-v1（从未派发） |
| host / Python | ai395 / /home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python |
| 外层 freeze 上限 | 180s、CPUQuota100%、MemoryMax4GiB、nice5；实际普通账户检查由驱动执行 |
| 固定控制目录 | /home/qq/neuro-rv-bc-inputs-862531d11598-v1 |
| 独立 wrapper 输出 | /home/qq/neuro-rv-bc-development-862531d11598-v1 |

FREEZE_REQUEST.json 是完整 h_process_start 参数，args[1] 包含完整 runner 字节，stdin 包含完整原 wrapper 和 registration 字节；无需另取远程脚本或安装环境。实际请求中保留 PYTHONDONTWRITEBYTECODE=1，禁止 source cache 写回。driver.py.txt 与运行时新控制目录 driver.py 原字节相同，后缀映射仅为仓库证据文件命名。旧候选 runner blobs 是未执行的审稿前像，不得替代本表最终字节。

## 原输入、权限与零新增独立来源

保留原 native source 3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd、wrapper blob94e819d579232597de08a5c239a78e9d40768416、原 FROZEN SHA7679b083343d6de9d7b3e1f1acc4f3252b044de36deafadb289ff532c7de7497、checkpoint SHA c4ee4a0219117edeec6381b0bb01b896f9a182862298eba22d3c69a828c17096。原 wrapper 与 registration 单独放入本 bundle，并逐字包含在 stdin；registration SHA为 e8c386af635518c9ee8d73c62f8e217bd9f8bcbf78b1bbe36fb2477f9ba634c4。

B/C 各用一个原 development 来源、一个原 case/seed，各运行 tuned-fixed 与 conditional；总分母4，新增独立来源0。二者已在旧576运行中各完成12臂。训练谱系 study_id/fit_*、weights/receipt 不改；新实际 original_operation_id 由原 _roster 和 execute_steps 赋值。原模型 tuned_fixed=STOP、calibration.complete=false，所以四次预期均STOP；不改变模型、alpha、支持域或评分。minimum_observed_gain=0 仅影响 B 描述性标签，C 仍保留两臂。

当前没有新 FROZEN/plan/operation digest。PHASE_REQUEST_CONSTRUCTION.json 的四个 actual_operation_id 明确为 null；不能把候选登记当实际 effect 证据。OLD_EFFECT_IDS_DERIVED.json 则是从全 SHA 锁定原 REPORT 提取的完整576 ID集合，未按成功状态过滤；它是派生清单，不冒称原 REPORT 字节。

## Freeze 的实际代码路径

1. 先核请求中 runner/wrapper/registration 原字节 hash、wrapper Git blob；确认 mode=freeze。冻结模式的 audit hook 拒绝 subprocess、exec/fork 和网络。
2. 使用 O_NOFOLLOW 与前后 stat 核原 FROZEN、collection、checkpoint、COLD_LOAD、85项原 source/driver/analysis closure、weights/control/exposure 和完整3,108,442 B旧REPORT。原模型/预算、普通账户、Python实际路径、两个原 evaluation case 均须符合固定值。
3. 新控制目录和输出必须不存在、互不嵌套、不能别名到原 runtime/material/run-v2 路径。只有通过后才 create-only 物化 runner、原 wrapper、registration、freeze stdin原件及旧ID全集。
4. 已验 hash 的 wrapper bytes 通过 compile/exec 直接载入，同时保留真实 module.__file__；不再次从 loader/pyc 取执行内容。wrapper、registration、runner 三份新输入也加入前后实际版本/hash核验。
5. 原 wrapper.freeze 创建四份deployment、B_PLAN/C_PLAN和最终FROZEN。随后原 load_native/validate_partitions、两个原 validate_plan/check_inputs，以及原 macro_execution._roster 真实返回四个 operation ID。
6. 核四者互异，按原 digest公式回核，并与旧576全集判无交集；保存实际 EFFECT_ROSTER.json（两份 plan 的原字节 SHA、canonical digest、四个真实ID/输出路径、旧全集digest）。
7. 再次真实读取全部原输入及新执行源并比较字节与版本，记录 source-after。成功状态仅 FROZEN_VERIFIED_NO_ACTORS；任何失败保留原错误与已存在对象，不清理、覆盖或自动重试。

旧ID集合排序后每行一个ID加LF的 SHA256 为 8ff28fd3c2ee71ff0d38824f6f94c1dc29cd1a2b583ea1b1eb769db4f618cd4c。正式 freeze 会从原 REPORT 再读再算，不能只信本 bundle 的派生清单。

## 后续 B/C 与只读对账

PHASE_REQUEST_CONSTRUCTION.json 指明从正式 freeze 请求构建未来请求时唯一允许替换的字段；这些未来请求尚未生成最终外部FROZEN pin、未登记或授权。每个新请求有单独稳定 key，绝不把首次 freeze key 改参数再用。

B/C 必须同时持有实际外部 FROZEN raw SHA、原已完成freeze terminal、实际四ID清单与原code/asset pins。每阶段控制请求、source-before与START均create-only；控制request独占创建在终端记录try之外，竞争失败者不能写胜者TERMINAL。START另绑定实际request/driver SHA；实际wrapper/native START依旧沿原路径。已有任何阶段请求或START只能只读对账，不能再次调用。C额外要求B控制terminal为RECORDED且原输入未变，以及B原wrapper/native report digest一致、incomplete=0。

驱动阶段调用原 wrapper.run_phase，不注入host，不调用fit/collection/export；再用原 reconcile核保留对象。宏budget仍READ30s/finalizer5s/action40s/actor60s，每行外部scorer30s；每阶段最多2actor、未来外层600s。保存实际原native report返回值、原wrapper终端、全部原stdout/stderr与源前后核验。完整成本、energy/provider/一次性成本仍未知。

inspect/reconcile-B/reconcile-C在驱动audit中同时禁止写文件、子进程和网络；只能读已有对象。freeze确认不明仅对原key/参数核h状态，必要时另作明确只读inspect；任何START无终端仍UNKNOWN。原PLAN/RUN缺失造成reconcile错误时返回未决错误，不据此推断零effect；h请求超时不以新key重派。B不完整则C两行NOT_STARTED，计划分母仍4。

Python独占文件/fsync不认证断电恢复、跨boot exactly-once、持久owner CAS或Root授权。原native report可能保留3c94硬编码NoUpdate字段，它不是owner决定；本运行器始终HOLD_NOT_EVALUATED、owner_decision=null、production_admission=false。四次机械成功仍不等于READ价值、校准闭合、科学效益或独立B/C确认。

## 已做与未做验证

已核完整JSON请求的driver/hash、stage、stdin、固定key相互一致；已复核原 wrapper/native 路径。另一agent独立静态审查指出 loader/pyc二次加载缺口，最终版已改为执行已验原bytes，并加入前后版本核验。最终源与所有artifact按原字节进行Git读回验证。没有声称Python运行、freeze、4ID检查或4actor已经通过；真正值只会由获准后的实际原API产生。
