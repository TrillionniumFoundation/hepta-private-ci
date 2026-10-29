from pathlib import Path
import datetime, hashlib, json, re, stat
ROOT=Path.cwd()
OUT=ROOT/'work/ci-follow/cold-release-runtime-and-Cell-loader-readonly-audit-20261026-001'
for name in ('report.md','audit-receipt.json','input-pins.json','dependency-inventory.json','source-anchors.json','manifest.json'):
    if (OUT/name).exists(): raise SystemExit('refuse overwrite '+name)

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
def pin(rel):
    p=ROOT/rel; s=p.lstat()
    if not stat.S_ISREG(s.st_mode): raise ValueError('input not regular: '+str(p))
    return {'path':rel,'bytes':s.st_size,'sha256':sha(p),'type':'regular'}
def write(name,data):
    p=OUT/name
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n' if not isinstance(data,str) else data)
    return pin(str(p.relative_to(ROOT)))

capdir='work/ci-follow/cold-release-role-cap-local-independent-review-20261026-001'
hepta='work/ci-follow/Hepta71a-initial-model-read-owner-independent-source-review-20261026-001'
ci53='work/ci-follow/rog-model-I09-I10-53fb727-independent-readonly-20261026-001'
chain='work/ci-follow/pn1-public-component-source-SSH-prefetch-20261026-001/ownedsource'
raw='work/ci-follow/cold-release-runtime-and-Cell-loader-readonly-audit-20261026-001/fixed-small-original-data'
paths=[
 capdir+'/report.json',
 'outputs/runtime-release-readiness-2026-10-25.json',
 'work/ci-follow/smollm-runtime-declared-inventory-rog-20261025-001/attempt1.stdout.json',
 'work/ci-follow/smollm-runtime-declared-inventory-independent-readback-20261025-001/independent-summary.json',
 'work/ci-follow/smollm-runtime-record-content-rog-20261025-001/attempt1.stdout.json',
 'work/ci-follow/smollm-runtime-record-content-independent-review-20261025-001/independent-receipt.json',
 'work/ci-follow/smollm-runtime-record-content-independent-review-20261025-001/capacity-interface-addendum.json',
 'work/pn3-persistent-repair-feasibility-review-20261025/review.json',
 'work/read-only-lan-filesystem-capability-20261025/receipt.json',
 'work/ci-follow/lan72h-setup3-terminal-root-observation-20261026-001/failure-observed.json',
 'work/ci-follow/lan72h-component-driver-20261025/review-v5/plan-approved-setup3.json',
 'work/ci-follow/lan72h-component-driver-20261025/review-v5/node.py',
 'work/ci-follow/lan72h-component-driver-20261025/review-v5/stage.py',
 'work/ci-follow/lan-cell-pilot-preparation-20261025T161151Z/source/trillionnium/crates/trnm-data-availability/src/cell/cache_budget.rs',
 'work/ci-follow/lan-cell-pilot-preparation-20261025T161151Z/source/trillionnium/crates/trnm-data-availability/src/bin/trnm-cell.rs',
 hepta+'/independent-receipt.json',
 ci53+'/independent-receipt.json',
 ci53+'/reviewed-fixed-source-text/1-after.txt',
 ci53+'/reviewed-fixed-source-text/0-after.txt',
 'work/ci-follow/pn1-ec0-public-component-source-admission-20261026-001/clean-source-admission.json',
 chain+'/scripts/llm_runtime_pilot.py',chain+'/scripts/llm_neural_read_worker.py',
 chain+'/scripts/llm_inherited_runtime.py',chain+'/scripts/llm_cell_release.py',
 chain+'/scripts/run_llm_cell_native_handoff.py',
 chain+'/config/pon/model-family-smollm2-135m-v1.json',
 chain+'/docs/development/TRNM_AI_NATIVE_BLOCKCHAIN_DEVELOPMENT_PLAN.md',
 raw+'/smollm_neural_profile.rs.txt',raw+'/smollm_cell_wire.rs.txt',
 raw+'/11-actual-run-full-raw-manifest.json',raw+'/12-actual-I09-result-and-limits.json',
 raw+'/13-execution-material-manifest.json',raw+'/14-actual-execution-final-freeze.json',
 'work/ci-follow/cold-release-runtime-and-Cell-loader-readonly-audit-20261026-001/fixed-source-and-I09-original-read.stdout.json',
 'work/ci-follow/cold-release-runtime-and-Cell-loader-readonly-audit-20261026-001/fixed-source-and-I09-original-read-receipt.json',
]
for name in ('smollm_cell_material.rs.context.txt','smollm_neural_driver.rs.after.txt','smollm_neural_read.rs.after.txt','smollm_neural_session.rs.context.txt','smollm_neural_session_owner.rs.context.txt','smollm_initial_host.rs.after.txt','selected_initial_smollm.rs.context.txt','final_use_authorizer.rs.context.txt'):
    paths.append(hepta+'/source-data/'+name)
inputs=[pin(p) for p in paths]
cap=json.loads((ROOT/capdir/'report.json').read_text())
rt=json.loads((ROOT/'outputs/runtime-release-readiness-2026-10-25.json').read_text())
i09=json.loads((ROOT/raw/'12-actual-I09-result-and-limits.json').read_text())
frozen=json.loads((ROOT/raw/'14-actual-execution-final-freeze.json').read_text())
req=(ROOT/ci53/'reviewed-fixed-source-text/1-after.txt').read_text()
names=sorted(set(re.split(r'[ =@]',l)[0] for l in req.splitlines() if l and not l.startswith((' ','#'))))
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
source_scope={
 'controlled_native_I09':i09['source'],
 'Hepta_source_only_current_review':{'head':'71a8850fb30e57c77ff58dc08cb6cc78f53ad1c8','tree':'37cec9fd1966249cf8dec2e869d4f737795609c6','ordered_parents':['727f1f25c68385e7b8d50223c11593ba4a6477f6']},
 'Chain_runtime_source_local':{'head':'ec0acdff5717b8f584b26f30f1162bd9bf1cc888','tree':'49de9450a7738b15f3dc63b808f957ce49804df2','basis':'retained clean-source admission and exact local file hashes; later53fb review verifies its seven-path delta has no model/loader runtime source changes'},
 'Chain_new_CI_requirements_source':{'head':'53fb654b532ed8e737e0dea635a31dce3b73b3cc','tree':'d82ba0c7bbaea04200f11d38f6e9c4dccac81f78','source_only':True},
 'original_LAN_profile':'lan72h-630f871-20261025-setup3; separate original eight-material transport profile, not an I09 cold-runtime owner'
}
write('input-pins.json',{'schema':'cold-release-audit-input-pins-v1','sealed_utc':now,'source_scope':source_scope,'pins':inputs,'no_large_original_wheel_library_weight_or_DB_bytes_delivered_or_rehashed_here':True})
anchors=[]
def anchor(rel,lo,hi,claim):
    a=(ROOT/rel).read_text().splitlines();anchors.append({'input':pin(rel),'start_line':lo,'end_line':min(hi,len(a)),'claim':claim,'exact_lines':a[lo-1:hi]})
anchor(raw+'/smollm_neural_profile.rs.txt',15,93,'config.python is a path; execution_profile_digest binds six project source/family identities, model/action digests and threads4; no interpreter/package/native-runtime closure')
anchor(hepta+'/source-data/smollm_cell_material.rs.context.txt',81,129,'sealed verified byte material starts only with original resource/control/FinalUse owner; not held namespace or installation')
anchor(hepta+'/source-data/smollm_cell_material.rs.context.txt',180,207,'exact role-specific file bounds; eight base300MiB, three adapter2MiB')
anchor(hepta+'/source-data/smollm_cell_material.rs.context.txt',316,330,'exact11mandatory roles; arbitrary runtime files cannot silently be added')
anchor(hepta+'/source-data/smollm_neural_driver.rs.after.txt',124,211,'source verification and path config; private staging and original owner; actual Python command explicitly sets three offline/GPU environment values')
anchor(chain+'/scripts/llm_neural_read_worker.py',63,87,'actual material verification, package import, path-based local model loading and original parent adapter load')
anchor(chain+'/scripts/llm_runtime_pilot.py',473,499,'actual torch/transformers/safetensors imports depend on configured runtime')
anchor(chain+'/scripts/llm_runtime_pilot.py',534,554,'actual local-files-only HF tokenizer/model loads from material path, verifies tensor/tokenizer profile; dtype f32 uses BF16 weight file')
anchor(hepta+'/source-data/smollm_initial_host.rs.after.txt',265,324,'original authenticated CURRENT, selected material and Unix FinalUse/resource/journal owner remain mandatory')
anchor(chain+'/docs/development/TRNM_AI_NATIVE_BLOCKCHAIN_DEVELOPMENT_PLAN.md',956,977,'existing PN3/I09 controlled profile and unchanged35s boundary; I10 and runtime closure remain open')
anchor(chain+'/docs/development/TRNM_AI_NATIVE_BLOCKCHAIN_DEVELOPMENT_PLAN.md',2318,2332,'new-engine finite I09 actualPASS, original overallI10FAIL; gain and ordinary closure remain separate')
write('source-anchors.json',{'schema':'cold-release-audit-verbatim-source-anchors-v1','anchors':anchors,'not_execution':True})
inventory=[
 {'dependency':'platform / CPU / ABI / selected markers and extras','observed':'CI requirements declare Linux CPython3.12 x86_64/aarch64 wheel choices; prior installed metadata assumes Linux CPython3.12 x86_64 with no extras','missing':'actual complete runtime ABI/base-image/glibc/loader/CPU-feature identity, exact marker environment and selected-extras closure; per-platform loader validation','closed':False},
 {'dependency':'interpreter and Python standard library','observed':'configured venv bin/python resolves to /usr/bin/python3.12; observed executable8020928B SHAe50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f; pyvenv.cfg metadata captured','missing':'original interpreter distribution/provenance, symlink/ancestor closure, complete stdlib/base prefix/extensions/loader hashes and fresh offline transport/use','closed':False},
 {'dependency':'original wheel archives / install recipe','observed':'new53fb CI file pins31unique distributions and32 requirement records (two architecture torch alternatives) with allowed wheelSHA256; installed29distribution RECORDs separately captured','missing':'retained original archive bytes and sizes for the chosen actual platform, acquisition/installation provenance and reproducible offline installation in the release owner; newCI source does not confer this','closed':False},
 {'dependency':'installed Python package files','observed':'23990RECORD rows /20378existing paths /922881591B;18731declaredhashes match,0size/digest mismatch;3612missingpyc remain originalFAILED contract','missing':'unlisted-file inventory, immutable atomic runtime namespace, handling of .pth/sys.path/site/user environment and explicit pyc policy under a reviewed versioned contract; existing failure is not relabeledPASS','closed':False},
 {'dependency':'native extension/shared-library closure','observed':'44filename-native candidates547041392B, including libtorch_cpu.so432269632B; both are subsets of installedpathname total','missing':'actual ELF dependency graph/interpreter/DT_NEEDED/RPATH/RUNPATH/dlopen and transitive system-library/CPU ABI binding, including dependencies outside venv; name heuristic is not this graph','closed':False},
 {'dependency':'model backbone/tokenizer/config','observed':'eightbasefile exact roster including269060552B model.safetensors; I09run002 materialization checks and native real load/forward PASS in a preinstalled runtime','missing':'fresh complete runtime acquisition plus real load using the same admitted whole release and held authorized namespace, durable custody/repair and independent-domain proof','closed':'FINITE_I09_DATA_AND_LOAD_ONLY'},
 {'dependency':'bounded adapter/contracts/profile/project scripts','observed':'threeadapterobjects +sixsource/family pins; actual generation3 parent-file/contract/backbone/tokenizer/Ready checks and signed load/query/deniedquery/unload in I09','missing':'original I10 selected installation/CURRENT update, ordinary next-task route and three real predecessor-linked installed rounds; projectsource pins do not bind interpreter/site-packages','closed':'FINITE_I09_ONLY'},
 {'dependency':'runtime-generated files and mutable caches','observed':'old measured noRECORDhash rows include1618pyc; old missing3612pyc retained; originalHF/local loading is offline for model reads','missing':'explicit bytecode/import/hub/temp/compiled-extension/generated-file policy, same-owner accounting for extraction/install/scratch and old/new runtime overlap; no ambient cache dependency permitted in fullcold acceptance','closed':False},
 {'dependency':'Cell transport / materialization / retention','observed':'newSQLite3.51.3 I09:11objects269chunks272190131payloadB,4.2576826509975945s within35s,0initialconsumerchunks,one loopback supplier','missing':'runtime_root payload transport, whole held namespace, release-wide destination/temporary/DB/WAL/SHM/old-version ledger, persistent custody repair/recovery and WAN independently administered campaign','closed':'FINITE_LOOPBACK_MATERIAL_ONLY'},
 {'dependency':'installation and ordinary-use authority / process terminal','observed':'original resource/control/FinalUse owners required;3bindings2nonces,denialbeforeforward; I09simpleownedchildwait4/reaped terminal observed','missing':'I10selectedinstallation explicitly unavailable:overallexit1/180.167288273s; no ordinaryAgentdnexttask/threeinstalledrounds/gain/whole-funded-U/independentWAN qualification','closed':False}
]
write('dependency-inventory.json',{'schema':'complete-cold-release-gap-inventory-v1','source_scope':source_scope,'observed_installed_distribution_versions':rt['packages'],'new_CI_requirement_unique_distribution_names':names,'new_CI_requirement_unique_distribution_count':len(names),'new_requirements_are_not_runtime_release':True,'inventory':inventory})
report='''# PN3 / I09–I10 完整冷加载只读审计（2026-10-26）

结论：**NO_GO / 完整冷 release 尚未闭合**。这些容量数字不构成一个已经证实的通用矛盾；它们属于不同 profile、角色与计量。已闭合的是一个使用预装 Python 运行时、从单机 loopback 获取固定十一项模型材料后，执行原签名加载/推理/拒绝推理/终态卸载的有限 I09 观察。完整运行时交付、I10 授权安装、普通下一任务与三轮收益均未闭合。本审计没有运行模型、构建、测试、安装、provider 探针、服务变更或新 campaign。

## 1. 五个数字分别约束什么

| 数值 | 原 profile / 角色 | 度量与边界 | 同一 owner 如何计费 |
|---|---|---|---|
| 922,881,591 B（约 923 decimal MB / 880 MiB） | ROG 已安装 CPU venv 的 RECORD 内容调查，29 distributions | 20,378 个存在的记录路径的文件长度之和；不是 wheel 压缩大小、完整解释器根、去重/物理占用、VM、RSS 或 FSIZE | 若作为新 release 的 installed tree 存于同一受控 host root，实际保留字节须进入该 owner 的聚合账。旧观察不构成这个新 admission |
| 432,269,632 B | 同一旧 venv 的 `torch/lib/libtorch_cpu.so` | 一个已安装共享库的文件长度；已经包含于 922,881,591 B，也包含于 44 个 native candidates 的 547,041,392 B | 不得再次加总成额外 432 MB。它没有自动成为 I09 的一个合法 base 角色 |
| 512 MiB = 536,870,912 B | 原 630 / setup3 每个 `trnm-cell` cache | logical quota 为 chunk bytes+每键32B 与 manifest wire+每键32B；另有独立 main-DB 文件/page image 的 512MiB 上限。两者不是两个可相加的配额 | 同 cache 必须同时满足 logical 与 mainDB 限制；WAL/SHM 不因此免费。每个 cache 独立受限，多个 cache 同时仍计入 host 总量 |
| 300 MiB = 314,572,800 B | `hepta-smollm-controlled-cell-release-v1` 固定十一材料中的八个 `base/*` 角色 | 每个 regular file 的未压缩长度及实际流哈希上限；另三个 adapter 文件各2MiB，sidecar64KiB | 不是整个 runtime/release、VM、RSS、AS 或所有任意文件的上限。不能把432MB共享库塞进不变的八角色，也不能为修绿放宽旧角色断言 |
| 2 GiB = 2,147,483,648 B | 原 `lan72h-630f871-20261025-setup3` 每个 data host 的受控 root | cooperative forecast/postchild `sum(stat().st_size)`；包括两个 slot 的 cache DB/WAL/SHM、输出、二进制、事件和 metadata。不是硬 quota、FSIZE、VM、RSS 或宿主空闲盘 | 保留 slot 与新的 cold candidate 重叠时同时计费；metadata64MiB在该总额内。原 profile 明确不做 model loading/complete runtime release |

详见 `cold-release-role-cap-local-independent-review-20261026-001/report.json`（本包 input-pins 精确绑定）。每个 role 的 cap 保留原值；本审计没有把不同 profile 拼成同一次失败，也没有提供新预算。

原 Pocket4 `provider-0133` 的 **UNKNOWN 1GiB 是 NETWORK response reservation**，不是磁盘占用实测。SSH255、目录缺失或当前可达均不能释放该 charge、推断原 native 终态或构造“2GiB 减 1GiB 磁盘”的伪冲突。原 setup3 总 FAIL / child UNKNOWN 不变，同管理员 LAN 不满足三独立管理员 / 故障域 WAN。

## 2. 哪些依赖与行为已经有真实证据

- 旧 runtime 调查读取 23,990 RECORD 行；18,731 个原声明 SHA 匹配，实际 size/digest mismatch 为0。但 3,612 个原未给 hash/size 的 pyc 缺失，原 `all_captured_targets_contract_pass=false` 保留。1,647 个存在但 RECORD 未给 digest 的项目（1,618pyc +29 RECORD自身）另测到41,867,102B；这些观测哈希不是原 wheel 哈希。原 wheel archives 没有留存，未绑定所有 unlisted files、解释器/stdlib、完整原生库图或原子 namespace。
- 53fb 的新 **CI unit** requirements 源文件固定31种 distribution（torch x64/ARM64两行替代项，共32条记录）与 allowed wheel SHA。它在 CPU CPython3.12 Linux 两架构的 unit scope 有价值；它增加 cryptography/cffi/pycparser，并非旧29distribution已安装环境的逐字快照。它没有提供轮子原字节/大小、解释器/stdlib、安装峰值、完整ABI或实际 cold release。不能从 requirements 声明继承一次新的模型/安装 PASS。
- **原 I09 run002**：Chain `4c8c2ee70d8aba1fc959900741e89335ddcd71f8` / tree `1cd27084a7fef9e4d6e4984a5780cf4c3951e72c`，Hepta `8d25c5d71f7401a383b4c80046c8b26811abe394` / tree `7d1aa7abb787610b03cd8a319a3f905f33acb2ea`。全新 SQLite3.51.3 caches 获取11对象 /269chunks /272,190,131payload B，消费者初始0chunks，含 cache-only materialize 与终态读回 **4.2576826509975945s < 原35s**。一个 loopback supplier，自然退出在 native 前。消费者与生产者 DB 各272,613,376B，这是两个实际文件，并非一个去重副本。
- 原 selected native case `real_cell_release_original_signed_load_query_and_terminal_unload`：1PASS /10.357s /0retry，131项为 selector exclusions。编译+命令131.049s不是10.357s case 时间。模型 generation3，真实 forward 67,453,520ns、48input tokens、原观察RSS1,149,550,592B。RSS不是磁盘或Whole-U/并发进程树峰值。3 authorizer bindings只产生2 durable nonces，第三个拒绝发生在 forward 前；原冷 journal 重开与原 wait4/reaped 卸载观察保留。
- 这一 controller **180.167288273s / exit1 FAIL**：`I10 selected installation UNAVAILABLE`。整个 native receipt仍UNVERIFIED，不得用有限 case PASS 覆盖它。无 CLI/Agentd E2E、CURRENT 安装、普通下一任务、三轮安装升级或收益资格。原97文件818,673,612B只在远端原目录保留。本次只读取原4份小型 manifest/result/freeze JSON与精确71a两份小源码；没有重新独立读取97原大件、权重、数据库或远端库字节。

完整依赖清单及31种CI依赖名称在 `dependency-inventory.json`，原安装29版本保留于该文件。

## 3. 真实 Cell loader 与权限路径

现有 `verify_controlled_cell_material_v1` 先验证固定11角色的TCM1/TCR1、SHA、实际流、family/source/profile/operation/参数等，返回私有字段的 `VerifiedCellMaterialV1`。它的 `start` 必须接收既有 control journal、ResourceGrant、FinalUse authorizer/runtime owner，继而调用原 neural read port。**字节校验不创建 selector/CURRENT、安装或执行密钥。** 原代码也明确 caller负责 private staging，这不是 held-namespace capability。

真实 worker 路径依次执行 material verification、现存 Python package imports、`AutoTokenizer/AutoModel.from_pretrained(local_files_only=True, trust_remote_code=False)`、真实 parent adapter load、Ready pin核对。八个base含269,060,552B BF16 safetensors，载入为原f32计算profile，不应把计算内存当文件配额。driver启动 `config.python` 指定的绝对路径；现 profile digest固定六个项目源码/family、actions及模型/contract digests、threads4，**没有绑定解释器、site-packages或系统动态库**。driver明确设置三个offline/GPU变量，原源不构成一个完整 hermetic import/runtime 根。运行时缺失应失败，不能借 ambient site/user/.pth/PYTHONPATH/库路径或在线下载冒完整 release。

Rust原consumer及worker会重验材料，但 HF 仍按路径重新打开；源码说明依赖受控private staging，而非整个 ancestor/material namespace跨检查到实际打开的held证明。下一步应在该已声明边界内补 admitted runtime/namespace，不能把一次hash校验当通用可变目录安全证明。

71a 的 selected-initial retained-owner API 源级保留原 authenticated CURRENT、不可续期 selector window、Unix FinalUse、journal、exact1model/1request/8GiB grant及120s启动/2s读取/250ms claim/1500ms I/O。它还没有普通Agentd生产调用者；与Cell download/I10安装没有自动拼接。request Completed 不等于 OS child退出；必须继续用原显式 shutdown/owner terminal/wait链。71a static fixture 的两字段修补不在本报告中升级为 actual compiler/native/model资格。

## 4. 在原 cap 内能否安排

**单cache不够存下整个922,881,591B安装表示**不证明流式获取不可能。若 runtime被版本化为多个可验证chunks/objects，受控materializer可以在验证、落到同一已admit目的namespace并建立实际持有责任后，按原cache eviction规则退休已消费缓存；不能在只得到一个hash或消费者仍可回读时提前退款。每个时刻仍同时计入当前缓存、DB/WAL/SHM、installed/staging、archive/extraction scratch、metadata、旧/新version、已unlink但仍held的对象和UNKNOWN。原 logical cache上限并不单独证明整盘峰值。

仅作不准入的算术：旧安装表示922,881,591 + I09十一材料272,190,131 =1,195,071,722B；再加一个全额512MiB的**文件表示假设**是1,731,942,634B，距2GiB仅415,541,014B。这不含完整解释器/stdlib/system libs、全部实际DB/WAL/SHM、旧version、archive/extraction/metadata/unknown，更不能同时又把512MiB当logical quota和physical file重复或漏计。旧runtime已经包含libtorch432MB与native547MB；勿再次相加。没有这些未知实测和峰值计划，不能宣称fit或不fit。

原 setup3 frozen forecast1,964,390,944B只余183,092,704B，连再加一份269,060,552B权重都超85,967,848B。这个既有 **NO_GO_FOR_ADDITIONAL_REAL_WEIGHT_PERSISTENT_RUN** 保留；它是冻结forecast，不是当前disk使用或既有run实际越限的证明。完整runtime不能借原campaign未分配的额度启动。原campaign roots是tmpfs；已有ext4 parent观察不证明硬quota、持久root或断电恢复。新的persistent namespace只有在原所有cap内完成同一owner持有/总账/恢复admission后才可使用；不能叫它“缓存外安装区”便免计费用，也不能删/重启UNKNOWN owner腾预算。本审计未创建该root、迁移文件或验证恢复。

所以：**有条件可行的工程方向是有界chunk消费+同owner全量目的根计费+有证据的退休/持久修复；在现有实测输入下，尚没有可以批准实际完整cold load的峰值预算和完整release对象。** 不需先换共识或增模块；沿既有PN3/I09–I10闭合。

## 5. 交给现作者的最小接口与顺序（建议，均NOT_RUN）

| 顺序 / 既有边界 | 最小可审接口 | 保留的条件及验收 |
|---|---|---|
| 1 / I09 release声明 | 在现有release/profile的显式版本下加入 `runtime_root` 身份：实际platform/ABI/marker/extras；解释器+stdlib/base-image；原wheel字节hash/size/provenance；安装文件及native/system动态依赖；import/.pth/pyc/generated策略。对接现 `SmolLmNeuralReadConfigV1`/execution-profile binding，禁止只接受无权路径或六projectsource代替runtime。 | 不静默改旧11角色/300MiB、旧digest或验收。原版本继续拒绝额外roles，runtime新契约必须显式review；单object超过cache时以现chunk方案有界消费，不豁免上限。实际manifest及所有字节齐全前拒绝运行 |
| 2 / M09 fetch与materialize | 原fetch/materializer消费runtime manifest与原材料，返回只由本地原owner构造的admitted、private、held runtime+material namespace。接入同owner destination/cache/DB/WAL/SHM/scratch/oldversion/UNKNOWN reservation与persistent-retention ledger；每一退休由真实终态/持有解除证明。 | 首先完整peak/sourcebinding admission，再创建有限目的根。错误、crash、换目录、缺库/缺wheel、cacheevict时仍需回读、full-disk/权限拒绝均failclosed且不能refundUNKNOWN。持久/repair不得只留临时DB或digest清单 |
| 3 / 原真实loader/FinalUse | 将已admit根的内容身份与loader实际open/import namespace绑定，明确可使用的interpreter/stdlib/native libs/环境；继续原signedResource/FinalUse/CURRENT窗口、参数、Ready和actualforward检查。对未知ambient或线上fallback拒绝；继续原shutdown/真实child终态。 | 新鲜目的端起始没有环境/模型cache，离线只能使用release。记录全部 acquisition/installation/firstactualforward 的 bytes、time、peak与source/runtime/parent身份。原35s十一材料cohort单独保留，完整cold计时另报，不能把预装环境结果冒cold |
| 4 / I10与普通任务 | 接原selector/evaluation/artifact/TaskFlow/资源owner的真实安装接口，再下一任务从原CURRENT读回实际安装parent；不是把VerifiedCellMaterial转换成安装权限。 | 三轮必须逐轮actualparent→train→evaluate→跨节点download→authorizedinstall→nextordinaryread；机械闭合与实际收益分别判定，零收益保留拒绝升级。原撤销/reorg/latecancel/denial/ownerterminal与预算断言不降格 |
| 5 / PN5原验收 | 在完整release/custody/repair已经闭合后才用既定三个独立管理员与故障域72hWAN方案。 | 同adminLAN、loopback、成功checkpoint不能替代；Pocket原UNKNOWN/1GiB NETWORK charge和FAIL完整保留。量测确认goodput/coldload/repair/recovery原cohorts，不从名义TPS推断 |

本次独立审阅完成，目标工作仍ACTIVE：complete cold release、ordinary installation、三轮收益、Windows原隔离与四路资格、独立WAN均保持未完成，merge_ready/task_complete=false。精确输入、源行、原失败和本次唯一小型只读SSH收据由同目录JSON绑定。
'''
write('report.md',report)
receipt={
 'schema':'cold-release-runtime-and-Cell-loader-readonly-independent-audit-v1','sealed_utc':now,
 'decision':'NO_GO_COMPLETE_COLD_RELEASE_AND_ORDINARY_INSTALLATION_NOT_QUALIFIED','audit_completed':True,
 'source_scope':source_scope,
 'scope':'retained primary source/raw metadata and one bounded SSH read of two exact71a small source blobs plus four exact known original I09 JSON records; no model/build/test/install/provider probe/service/source/output/CI mutation',
 'five_measurements':[
  {'name':'installed_RECORD_pathname_sum','bytes':922881591,'compressed':False,'complete_runtime_root':False},
  {'name':'libtorch_cpu.so_subset_of_installed_sum','bytes':432269632,'add_again':False},
  {'name':'per_cache_logical_and_separate_mainDB_image_limit','bytes_each':536870912,'not_two_additive_allowances':True},
  {'name':'per_I09_base_role_regular_uncompressed_file_limit','bytes':314572800,'eight_exact_roles_only':True},
  {'name':'original_setup3_per_datahost_controlledroot_sum_st_size','bytes':2147483648,'not_hard_peak_quota_VM_or_FSIZE':True}],
 'finite_I09':{'original_result':pin(raw+'/12-actual-I09-result-and-limits.json'),'exact_selector':i09['native_selected_case']['selector'],'case_pass':1,'case_seconds':10.357,'payload_bytes':272190131,'material_count':11,'transfer_seconds':4.2576826509975945,'original_material_seconds_limit':35,'preinstalled_runtime':True,'loopback_supplier_count':1,'overall_status':'FAIL','controller_exit':1,'controller_elapsed_seconds':180.1672882730054,'I10_selected_installation':False,'all_original_limits_and_failures_preserved':True,'new_independent_rehash_of_remote_large_originals':False},
 'original_runtime_contract_false_preserved':True,
 'original_unknown':cap['original_unknown_preservation'],
 'original_persistent_NO_GO':cap['original_persistent_repair_feasibility_preserved'],
 'conditional_resource_analysis_only':{'known_installed_plus11material_bytes':1195071722,'plus_hypothetical_one512MiB_file_representation_bytes':1731942634,'arithmetic_margin_before_unknown_dependencies_DB_scratch_oldversions':415541014,'not_an_admission_or_actual_peak':True,'no_offcache_install_root_refund':True,'no_UNKNOWN_retirement':True},
 'remaining':['versioned complete runtime_root and actual selected-platform archives/interpreter/stdlib/nativeABI/systemlibs/import closure','real cold acquisition+offline actual loader using only the admitted release','same-owner cache+destination+temporary+held+oldversion accounting, persistent retention/repair/recovery within original caps','I10 original authorized selected installation and ordinary nexttask readback','three actual predecessor-linked ordinary rounds, mechanism and benefit separated; reject no-gain adoption','original Windows four-lane native isolation qualification','three-independent-administrator/faultdomain at-least72h WAN'],
 'operations':{'new_small_readonly_SSH_calls':1,'new_large_remote_byte_reads':False,'model_or_provider_execution':False,'build_or_test':False,'installation':False,'source_or_CI_or_ROG_or_outputs_mutation':False,'new_campaign_or_unknown_cleanup':False,'local_new_report_files_only':True,'search_noise':'An initial overly broad local rg numeric search produced truncated hash-heavy output; no source/CI/native effect. Narrow exact paths were used for substantive evidence.'},
 'task_complete':False,'merge_ready':False,
 'artifacts':[pin(str((OUT/n).relative_to(ROOT))) for n in ('report.md','input-pins.json','dependency-inventory.json','source-anchors.json')]
}
write('audit-receipt.json',receipt)
files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='manifest.json']
manifest={'schema':'readonly-audit-evidence-manifest-v1','sealed_utc':now,'files':[pin(str(p.relative_to(ROOT))) for p in sorted(files)],'no_product_source_or_original_evidence_overwritten':True}
write('manifest.json',manifest)
print(json.dumps({'report':pin(str((OUT/'report.md').relative_to(ROOT))),'receipt':pin(str((OUT/'audit-receipt.json').relative_to(ROOT))),'manifest':pin(str((OUT/'manifest.json').relative_to(ROOT))),'input_count':len(inputs)},ensure_ascii=False,indent=2))
