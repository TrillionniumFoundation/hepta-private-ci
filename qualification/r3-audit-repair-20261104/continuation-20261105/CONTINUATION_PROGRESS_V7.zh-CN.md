# 持续审计与实际修复进度 V7

**23项原blocker现在为11项限定范围闭合、11项开放、B18科学验证暂缓。B08本轮按原退出条件闭合；整个候选尚未完成验收。**

本报告截至2026-11-05 17:53:52 UTC整理；每个原件保留自己的实际观察时间。此前10/12/1的[进度V6](CONTINUATION_PROGRESS_V6.zh-CN.md)和[证据索引V7](evidence-index-v7-registered.json)保留为历史。新[ledger V6](continuation-blocker-progress-v6.json)只改变B08的闭合分类，原23个ID及退出条件逐字不变。发展方向及后续完整工作计划见[计划V5](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md)。

## 1. B08已满足原退出条件

根审实际运行验证器并返回0，核对完整11,059,831字节原始日志、839,106字节JUnit、四个原测试正文、15个相关完整源码文件及5b/e78/eed的完整Git树。该原运行在ROG工作区的源码树为e78；工作区普通HEAD仍是cabc，不能将其写成5b。[根审闭合回执](reviews/b08-original-contract-root-closure-v1.json)和[独立四例检查](reviews/b08-original-exit-20261105/review-v1/four-case-evidence.json)保留逐名、字节位置与来源。

| 原用例 | 实际覆盖 | GNU原执行 |
|---|---|---:|
| recorder bounds pending calls and preserves overflow | 真实附加前后的None/Some、pending条数上限与溢出、exact replay及compaction清理 | PASS，0.014秒 |
| recorder bounds retained history and reports omissions | 512次真实记录与附加、32KiB保留上限及omission统计 | PASS，2.379秒 |
| chatgpt codex wire strips local metadata but openai wire keeps it | 端点/名称、格式和feature的16格矩阵 | PASS，0.012秒 |
| namespaced custom tool call preserves namespace through dispatch and replay | 实际SSE请求、原exact calls、flush rollout/load history、真实输出与namespace回放、escaped输入原序列化字节上限 | PASS，0.602秒 |

生产路径在构建prompt及发出真实请求之前附加pending calls；只读getter只读取已保留记录，没有制造“已附加”状态。原生产持久化协议未改变。端点矩阵的正确合同是ChatGPT Codex及非官方端点剥离本地私有字段，first-party OpenAI的原合法保留行为仍成立；不能概括成“所有provider都剥离”。原跳过网络宏的固定早退输出未出现。

这四例来自一次原所属范围的运行；该完整范围仍是3962通过、5失败、exit100。Windows三个原单元的各自固定源结果作为补充保留；Unix namespaced用例在Windows不适用。本次没有执行eed的GNU全范围，也没有将四例的通过升级成B15通过。此前Q02的收件计划不是额外原退出条件，不再以它无依据阻止B08闭合。

## 2. 17:53固定观察：Windows ACL修复已发布，原156项尚在执行

[Draft #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884)已发布`19d2fdfcaefbb41cdf2a72754d695d4b47cb3f14`，tree为`17ac791ce156d05d4d1cd13cddf9184e528293a1`。相对7e仅两个Rust路径变化，265行新增、36行删除；实际merge `69040075a846c7032a3bafc7a0b623e7c0257619`的tree为`75181bf7e4f119d08945003339b32aa0782ef41c`，两父源为eed和19d2，主产品14路径均保留。[精确发布回执](reviews/b11-identity-two-path-publication-v1.json)

原READ_CONTROL查询、完整ACL时直接返回及最终setter保留；只有需要修复时，持有旧句柄并读取完整非零128位FileId和volume，重新以既存对象方式打开具WRITE_DAC的新句柄，拒绝最终reparse并核对同一对象后写DACL。原无WRITE_DAC控制使用自有文件及当前同步测试线程的受限令牌，先证明查询仍可达，再要求生产修复在实际写权限打开阶段返回OS5；还原令牌发生在还原文件DACL之前。

新增物理控制分别使用真实文件和目录：持有旧对象、rename后重建原路径，要求替代对象和原对象DACL都不被误改，并证明原对象在新名字下仍可正常修复。其兼容范围明确：修复需要FileId/属性支持，最终reparse被拒绝；没有宣称祖先路径托管或并发ACL写入序列化已解决。[独立静态审查](reviews/b11-identity-v3-independent/independent-review.json)

原工作流未变。native6为run `42077117788` / job `127420172838` / attempt1；17:49的完整原API记录显示checkout及MSVC准备完成、原目标正在执行，尚无测试终态。原名单为156项，即旧155项加一项物理替换控制。此前native5的143通过、10失败、2忽略完整保留；新源不能继承这些结果。[首次快照](ci/b11-native6/first-snapshot-1743.json)、[17:49快照](ci/b11-native6/snapshot-1749.json)

精确反事实执行脚本V2已完成独审，当前仍DISABLED、NOT_RUN。它要求完整、非cache的原日志中四个相关阳性用例各自真实PASS，才移除唯一身份相等强制；只有实际替换对象被误改的固定marker、原597行断言、单一1FAIL/0ignored及XML101同时成立，才算有效负控。finally写回前重新验证完整源码、索引及锁，未知漂移保留不覆盖。原whole-target错误继续保持错误；反事实成功不能把整个B11变绿。[执行候选manifest](native-plan/b11-identity-counterfactual/counterfactual-workflow-v2/manifest-DISABLED.json)、[独审](reviews/b11-counterfactual-wrapper-independent.json)

## 3. CI等待链与资源边界

浏览器实际显示新blocking等待旧5b，旧5b又指向更早0e任务；但对应REST确认更早任务自09:42:55已取消，37个job全部终态。这只能证明显示状态之间存在差异，不能证明旧0e当前占用runner，也不能据此断定唯一根因为runner容量或一个已证实的锁故障。旧5b剩余三个未分配runner的job均为汇总，不执行产品测试。[直接UI观察及原API对照](reviews/post-v7-ci-waiting-ui-and-api-v1.json)、[完整跟进](ci/queue-followup-v2/review.json)

当前GitHub连接没有暴露取消工作流的操作，浏览器尚未登录；本轮未取消、重跑或改变这些任务。旧七个失败job中六个完整日志和四份Windows原ZIP已保留；cargo-deny日志接口仍失败，这一缺口没有被补成推断原因。

Linux完整门仍RESOURCE_PENDING。唯一ca1 firststart在任何源码修改、build/catalog/test之前因可用RAM低于原32GiB门停止；64GB磁盘、32GiB可用内存、jobs4不变。现有五台主机的已记录观察没有一台达该门，不代表它们永久不可用。没有具体新容量释放依据前，不重复启动或降低门槛。原完整目录、七个helper、源码/索引/锁/SDK守卫均已准备；真正测试完成后才按原顺序进行scoped fix和fmt。

## 4. Intel PTY与其它开放工作

当前eed的PTY源码、原30例及新增一个诊断收集控制已逐文件复核。原2/5秒预算、完整drain、child退出与FD断言保留；旧0e的Intel drain在2.023秒失败，只观察到Python启动，缺少read字节/errno，尚不足以证明Tokio调度根因。现有诊断适合下一次真实原失败取证，不能把测试诊断变化写成生产drain已修复。[B21独审](reviews/b21-intel-current-followup/independent-review.json)

成功日志保留脚本有一个必要的小补充：现有11目标名单没有PTY目标。新增一行保留原PTY成功日志的候选已静态验证，原11项顺序、复制及错误行为不变，也不增加测试执行；为保留当前eed原CI，暂未另推主ref，下一次必要产品发布时一并纳入。[精确patch](reviews/b21-intel-current-followup/retention-candidate-v1/retention.patch)

B02/B07/B09/B10/B11/B15/B16/B19/B20/B21/B23仍开放。工作依次推进原平台及严格权限边界、正常Root/Current/FinalUse/真实caller、外部系统独立接受；B18继续要求新的预注册2×2与D−B原采用门。研究分数、源代码存在、已有donor局部通过和CI任务成功都不能替代这些产品接受。

## 5. 17:53固定观察时的可交付与下一执行批

主产品仍为[Draft #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)的eed/ca1；本次审计提交只更新证据和计划，不修改产品源码或CI规则。已闭合范围为B01/B03/B04/B05/B06/B08/B12/B13/B14/B17/B22。

下一批先收齐19d2原156项完整结果，按实际失败修复并取得身份反事实；同步准备read ACL完成语义的小片及它独立的setup helper原目标，不能借库测试结果给helper授予资格。主平台CI取得终态后继续逐原范围收敛；只有新容量证据出现才启动Linux完整门。完整依赖顺序、23个原退出条件和各模块后续交付均在[计划V5](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V5.zh-CN.md)。

## 6. 17:54–17:58后续增量：147/7/2与精确反事实发布

原native6于17:54后取得失败终态，完整官方artifact `13438699284`已重建：2,045,739字节、14成员全部CRC/哈希/原字节一致，官方SHA256为`341e7b854d79329ee0c42113957f1d8c86bd6b74229fb6b4b2f1562c25ca8285`。根审还逐一核对实际merge6904/tree7518的77个原源码叶、原完整log/XML及两次互斥选择的harness摘要。**真实总数为147通过、7失败、2忽略，原whole-target仍失败，Bazel exit3。**[根审原件验证](reviews/b11-native6-root-original-verification-v1.json)

四个相关原阳性全部实际PASS。物理替换例分别对真实文件和目录输出`returned_ok=false`、两个对象均未被误改。剩余七项分为一项真实strict外部删除越界、两项ordinary-host Neither前提失败、四项共享mutex被污染后的下游未到业务断言；不能把后四项当四个独立隔离失败，也不能删除它们。

在该阳性前提和独审成立后，17:58:50实际发布反事实追加head `0f6148ea3fbe9d1263354791d5cc63c7e66d4628` / tree `f717a84a856413d87a3b718b0bcae3adbd16b643`。仅新增脚本并修改原workflow，301新增、0删除、0Rust变化。实际merge `b5c23d8943a0a36a14a962175cb2ec75d22d5553` / tree `29316e75554590382268dafa77869fab0394a264`的两个父源是eed和0f，完整10,586叶核对无意外变化。PR REST曾返回旧base.sha5b；实际Git对象确认eed父源，两类观察分别保留。[发布回执](reviews/b11-identity-counterfactual-publication-v1.json)

新反事实尚无实际执行结果。每次新运行还必须重新验证四个原阳性及源码、索引、锁；唯一负控须原固定物理marker、597断言、一个失败/零忽略、XML101和精确恢复全部成立。新流程不能把原full失败变成成功。第2节的DISABLED manifest保留准备时身份，本段发布回执明确其后实际使能状态；不能把准备状态或发布状态写成已通过。

主eed完整API快照17:53:59–17:54:00为19 workflows / 53 jobs：18成功、31排队、1执行中、2跳过、1取消、0失败。相比17:07只增加一个V8 x86_64 Windows ptrcomp-sandbox成功，仍只是API状态，未授予业务用例资格。blocking及architecture仍pending且各0jobs。23份完整原件无损保留，不倒改17:53:52的固定cut。[新快照](ci/eed-status-1754-20261105/summary.json)

当前立即动作是取得0f的原终态和精确负控，同时独立审查正常read ACL同步准备小片；后者使用setup helper原binary目标，库156项不会代它验收。正式blocker仍11/11/1。
