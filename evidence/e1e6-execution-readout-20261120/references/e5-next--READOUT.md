# E5 下一步可行性：原准入不能由 encoding fit 推导

**结论：保持原完整上下文定义、动作编码、来源顺序和数值预算全部不变，现有材料不能让原 1/4/16 前缀获得准入；推进这一目标需要独立冻结的表示实验身份。** 这不表示所有来源都不可表达：attrs 在原 v1 已有单项完整静态准入，但位于 ordinal 11，不能跳过前面的来源充当增长曲线。

本次只读绑定最终 `faeed277149701a316085a0453b05480df528655`，来源顺序 `9dade6e90f6227dded45afa1c8462758a511a699`。9 份源码/发布文件直接对本云该 commit 的 Git tree 核验，另保留 9 份原证据 SHA；见 `SOURCE_PINS.json`。

## 为何七项 fit 仍零项 static

`retrieve_once.py` 明确生成部分视图，仅选择主失败诊断、部分完整任务单元及至多四组 runtime 单元，不证明依赖闭合；独立 `run_targets.py` 因而明确输出 `v1_static_context_closed=False`。原 `count_tokens.py` 的静态准入 `all(...)` 同时要求该字段、完整动作重建及全部字节/token 门。七项只满足后者。**预算、optimizer 映射和 B/C 的 null 不在这个静态 all 中；它们是另行未闭合的训练协议，不能误称为这次静态零的直接原因。**

| 决定性原件 | 实际证据 | 对后续的约束 |
|---|---|---|
| 首源 loguru，ordinal 0 | 按已冻结 v1 规则完整渲染的 36 份 fixture 共 82,736 B，已超过 65,536 B；实际 prompt 168,122 B / 61,642 prefix tokens，另有 84 个静态 blocker | 即使修正全部静态解析 blocker，原可见上下文仍超预算。v2 的 2,851 + 236 = 3,087 positions 只证明部分视图加完整动作可编码 |
| rich，ordinal 2 | 当前完整 compact action 含 EOS 为 622 tokens，大于 384 | 只调整上下文不能缩短同一个已冻结动作；不得截断或只保留部分 edits。即使绕开 closure，原四源前缀仍失败 |
| attrs，ordinal 11（第 12 个来源） | v1 完整静态上下文与动作共 1,277 + 138 = 1,415 positions，单项 static true；training false | 可保留这一真实单项表示成功。v2 反而漏选其 edit owner，不能事后替换 view、重排来源或推广为前缀/训练成功 |

上述 loguru 字节下界针对**原冻结的全 fixture 可见契约**；它不是对所有可能上下文设计的不可行性证明。对某个固定 v2 view，仍可另做 before/task-only 的闭包证书审查；本次没有产生此类证书，也没有把 false 改为 true。

## 具体可改边界

1. **上下文契约层：** 参考 `e5_source_codec_v1/{visible_context,context_graph,task_fixture_paths}.py` 的闭包与完整 fixture 规则，在新的候选身份下定义可验证的局部依赖边界，或明确采用部分视图、完整原生 verifier 的契约。原 `v1_static_context_closed` 语义及历史结果保留，不能换名后当成同一准入。
2. **检索与动作层：** 对应 `e5_bounded_retrieval_v2/{POLICY.json,retrieve_once.py,compact_wire.py}`。任何新规则必须统一、只依赖 before/task；先冻全部 16 位置和输入，再独立构造完整监督动作。需要改变 rich 的动作表示时，也单独版本化；保留 4096 输入、3584 总序列、384 target、单次更新与原两条 32-unit 曲线。不根据已曝光缺失 edit owner 补选视图。
3. **执行接线层：** `e5_bounded_target_v2/run_targets.py` 继续区分完整重建、编码 fit 和上下文准入。首次训练前再明确原预算内的 optimizer-unit、计算/验证计量及独立 B/C 绑定，不能用一个材料拆多次更新或用额外调用填补。

本次无源码修改、模型/训练/native/tokenizer 执行、宿主访问、下载、新来源或未来面板读取。原 290 个 native testcase 是留存的验证材料，不能作为学习成效。
