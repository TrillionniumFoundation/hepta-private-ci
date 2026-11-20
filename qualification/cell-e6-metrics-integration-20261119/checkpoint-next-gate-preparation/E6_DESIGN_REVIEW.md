# Artifact cold-use 设计独立复核

## 范围与结论

这是对 `e6_head_use_design` 固定设计和原源码的只读静态复核。没有修改设计作者的文件，没有实现产品接口，没有签发许可，也没有运行编译、原生任务、模型或训练。来源及本次读取字节的 SHA256/Git blob 绑定在同目录 `E6_DESIGN_REVIEW_BINDINGS.json`。

设计正确保留了三个独立边界：Artifact authority 决定新用途许可，Selector 选择模型，Root 决定真实 D 操作及 FinalUse。现有 CURRENT 的过期语义、原学习期限、writer 退休和普通 NoUpdate 路径没有被设计成可绕过的开关。设计也明确承认真实用途政策、签发 custody、在线撤销来源和持久签发账本尚未接入。这个状态可以支持后续组件实现，不能支持“Adopt cold D 已通过”的结论。

本次发现两项需要在产品接口冻结前具体化的契约缺口。它们是尚未实现设计中的集成问题，不是本次已经复现的运行时漏洞。

## 1. 摘要依赖图还须覆盖已有 controller authorization 和最终完整输入清单

`DESIGN.md` 第 5 节、`API_CONTRACT.md` Layer 2 和 `WIRE_CONTRACT.json.descriptor_file_boundary` 已给出正确方向：选择前 D 描述不包含新 grant、后续 Selector 和最终 UpdateIntent，之后由完整输入清单绑定这些真实字节。问题是当前白名单仅明确列出这三个较晚信封，而已有冷 D 入口还要求单独的 Root controller authorization。

原 `authority_host_cold_next_task_enrollment.rs` 先用最终 intent、selected manifest、configuration 和 objective 调用 `derive_original_binding`，随后以该 binding 验证 `authorization.require_current`。原 `authority_host_cold_next_task.rs::derive_original_binding` 明确包含 `intent.digest()` 和 `intent.selection`，并另行包含 AuthBus objective 的签名字节和签名摘要。前置 AuthBus objective 与这份后置 controller authorization 因而不是同一份可互换的请求。

若后置 controller authorization 的内容被归入选择前 source/configuration 输入，会出现以下环路：D 描述依赖 controller authorization，后者依赖最终 intent，intent 依赖 Selector，Selector 依赖 grant，而 grant 又依赖 D 描述。同样，若晚期“完整输入清单”包含 final intent，之后又把该清单摘要填回这个 intent 的输入摘要，也会引入间接自引用。现有稿件没有证明一定采用这种错误接线，但它的三信封排除表尚不足以排除这种接法。

建议在实现前固定完整、带类型的摘要依赖图，至少明确以下顺序及对应实际文件角色：

1. 原任务/runtime/data、前置 AuthBus objective、接收方和 C 条件形成不可变的选择前任务清单。
2. 原 Artifact authority 的新 grant 绑定该清单；新 Selector 绑定 grant 与清单。
3. 最终 Root intent 绑定这两个结果和所有原 scope/C/D 条件。
4. 原 controller authorization 绑定实际最终 intent、selection、configuration 和 objective。
5. 最后的完整输入观察/接纳记录绑定此前全部真实任务和授权字节；它的摘要不得再反向成为那些已经签名对象的前像。

这些是拟议的类型边界，不是建议从现有输入中随意丢字段。必须仍然拒绝额外、缺失或变更的必需文件。应增加一个使用真实原数据类型的完整构造样例，以及逐一修改每类晚期授权文件的拒绝控制；目前没有执行这些控制。原代码来源是设计绑定的冷源 `6733159bd974ae6558e138112d81ca2f6da830e2` 的 enrollment，以及既有只读审阅中保留的 main 文件，后者原 `504c749622962ab574ddb11d6472adf2a2946982` 字节匹配信息单独保留，未假称公开对象。

## 2. “当前撤销状态”还须落实到退休后的真实更新来源和效应边界

稿件已经正确说明固定 trust 快照不等于 live revocation feed，任何 key/policy/withdrawal 变化都应拒绝。它还要求原 head tip、policy generation 和 withdrawal frontier 在每个操作中精确一致。这能发现被读取状态的变化；仅凭相同摘要本身，无法区分“仍然最新”与“消息源停滞、离线或旧状态被重放”。

这个缺口与原源码有一个具体交点：`owner_withdrawal_frontier.rs` 的原前沿由同一个 exclusive Artifact writer 持久发布；`read_original` 检查真实 CURRENT、未完成 staging 和前后字节一致。原 `owner_original_reader.rs` 再用已持有的 floor 拒绝回退。新设计同时要求旧 writer 真正退休，并且新只读路径不打开 fresh `LearningArtifactOwnerService`。因此，生产接线必须说明旧 writer 退出后，谁仍有真实权限发布或认证后续 dataset withdrawal，以及新 key/policy 状态如何传到实际 reader。一个永远不再更新的旧物理文件不能成为“没有新撤销”的证明。

建议冻结可实施的状态来源契约：其独立 authority 与 scope、签名或原 owner 通道、单调 epoch/sequence/floor、实际观察时刻或 session/challenge、新鲜度上限及离线拒绝条件。也可以用持续在线的原 authority 操作提供这些事实；不必为了设计而新造一套 JSON 权限。无论采用哪条路径，都不能由 D 请求方自行提供自洽 trust 或旧快照代替原状态。

还要定义每个不可逆效应的授权判定时刻。前后检查可以在效应后发现撤销，却不能撤销已发生的外部效应。若要求严格线性化，必须有实际 owner 的原子 fence/同步机制；若采用有界状态有效期，应如实声明和验证该语义。已发生的 Attempted/Issued/Published 原件必须保留，后检查失败只能停止后续效应，不能声称本次没有发生。稿件第 8 节和 CU-27/CU-28 已有保留真实状态的正确方向；剩余工作是把撤销来源和判定时刻连接到实际接口。

## 已核实的正向边界

- policy 自身哈希正确不会授予权限；产品构造必须来自原 Artifact authority 的独立 provisioning，默认缺失即拒绝。
- 新 use grant 不成为 writer、通用 CURRENT 或 FinalUse，也不能把测试 key 安装成生产默认 authority。
- 原 `ArtifactSelectionVerifierV1::new` 除了后续 producer/selector ID 的 `RoleCollision`，还拒绝 Selector 公钥与任意 Artifact writer/head 公钥相同，错误为 `AuthorityKeyCollision`。因此“只换 ID 就可用同一 owner key 充当 Selector”不是本次发现。更广泛的组织或 custody 独立性属于部署事实，不能仅由不同签名证明。
- 已有 source-grounded 设计、34 项 planned controls 和整个 Adopt 冷父验证是不同证据等级。设计本身记录 executed controls 为 0，本次复核没有提升这个数值，也没有改变旧 NoUpdate 或未来 Adopt 的资格。

## 本次动作计数

产品源码编辑 0；设计作者文件编辑 0；签发 0；编译 0；原生任务 0；模型调用 0；训练更新 0；远程 owner 0。仅做本地读取、原字节摘要核验和本复核原件归档。
