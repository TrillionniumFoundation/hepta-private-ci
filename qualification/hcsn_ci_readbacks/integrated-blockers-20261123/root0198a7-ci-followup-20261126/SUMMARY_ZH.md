# HCSN 专项 CI 与原始工件闭合回执

本轮三条已注册专项 CI 全部成功，四份原始 ZIP 已独立校验。当前整仓与科学/生产采用仍为 HOLD；本记录不将专项成功扩大为整仓通过。

## 精确结果

| 范围 | 源码与原运行 | 已取得证据 | 准入边界 |
|---|---|---|---|
| CPU短恢复 | 47b6fd0b；run45786572069 | adapter18+6+6方法执行；6组连续性、26次optimizer、两负控通过；原ZIP664成员CRC/SHA全通过 | 新完整训练重放0；HOLD_NO_GO；历史总计UNKNOWN |
| 标准可微CI | 47b6fd0b；run45786572001 | 两lane各385方法/2074文件；final gate success；两原ZIP各101成员全核 | PASSED_DECLARED_FIXTURES；36 LBFGS外层step只属neural-control组件 |
| N256宿主metadata | 32153753；run45786899259 | 1child、1观察+5负控=6validator；原ZIP18成员全核 | 所有model/training/dynamic/expm调用0；runtime/resource/all_closed仍false |
| 旧整合格式门 | b3a925d4；run45788732557/job139813600029 | 原merge576435fd执行cargo fmt与clean-worktree两步success | 仅此格式门；不是整run或当前4ffa全部通过 |

## CPU恢复与原件保全

CPU原诊断在Python3.12.3、Torch2.8.0+cpu、NumPy2.3.5、mpmath1.3.0环境执行，whole_wall=474.582060267秒。六个fit各有4次本轮验证调用，另有两个负控调用；总数26来自原SUMMARY，不是生命周期总数。六行均complete/full_state_equal=true，omit-Adam被检测、publication前crash被拒绝。原SUMMARY SHA为996b81717c35fdec5329d3d61a931395dec01272abf7254953b38d99572929f3，与原日志逐键一致。

独立下载首次在120秒超时，留下3095512B残片。原02下载20个完整范围，4范围两次尝试失败；03保留全部尝试与原字节，利用合法且相容的3241723B前缀，仅补952581B、6个子范围，传输55.338319375秒。拼装后核完整SHA、664文件CRC/SHA及全部输入前后不变。此次只做字节与JSON处理，0模型、0optimizer、0Torch/pickle反序列化；不把原SUMMARY中的数值比较当作本地再次执行。

| 原artifact | ZIP字节数 | 完整SHA256 | 独立成员核验 |
|---|---:|---|---:|
| CPU15102894027 | 27939824 | c95c36dd66d56e708c96bbbb7f28acbb431db8b7fc2925e580817f6d884c60dc | 664 |
| Diff source15101457428 | 440221 | a3be4a3356331411b9c3ba9ac1ffd8d4806f4497a6d2ecc8d0c73ef8776a4686 | 101 |
| Diff event15101207857 | 440277 | 7d21a25f92d4f7109d687668c7fd9262e55b6270eaea56326ff909ee2baf1d17 | 101 |
| N25615100974608 | 28989 | 881930596a525c4fa5e6f073f1dfeaed02cf8bebb56c8f10478d0425f2505b36 | 18 |

CPU完整READBACK为304334B/SHA b367311a325c4d44ce48585d757833c68b571d6bf578844fab48a7bc61dcdde8；SUMMARY为51150B/SHA32d6450289add3776950013040eebddaca9121795cebc90a2fcec7cef40d36fd。26份选定JSON均解析成功。原HTTP响应头和全部传输原件保留在main；公开本私库证据包包含完整ZIP、原始残片、终局、源码、逐文件/尝试身份，不复制可能带临时签名的响应头。

## 当前整仓真实阻塞

最新已读取#6799为4ffa56f6d0be94e68d23d1bfe72aa2cbfd50d479，原blocking run45794035631/attempt1尚无成功终局。Windows shard3 job139821215079在09:55:09UTC真实failure：四个Cell控制断言收到CommitUncertain、四个Queue hook等待/拒绝超时。原执行merge3f6bcb32b554be590874617884e9ee627b6404de与head共同tree为3f29023cc2dae076979dbcf3c62c10d98d488258；完整596428B日志SHA4ccc926645e11bf88fba606d230f0bd8c8f528434604f8111f3b8bb4c52ed0c3已封存。

Windows目录sync路径受cfg(unix)保护，不能将本次失败归为目录同步被拒绝；actor_loss一例已到达admit之后的故意panic，现有1秒RPC预算耗尽。其他Cell例仍需区分普通文件I/O与调度；Queue现有两个简单Python controls通过，但未覆盖完整session shell/JobObject/JSON stdin链。已吸收的旧Python/rejection修复不重复列作新修复。当前正在独立准备保持原期限、断言、生产锁的调度与fixture阶段诊断候选，未声明Windows问题已修复。

## 保留的采用边界和历史

原25项账本及65件原档在提交0253557735f4507b9124714597bafd5d2714f06c继续有效。本轮只更新其15/16/24项的专项托管与保全终局，并补旧b3a原格式成功；原51bed失败和所有先前观察保留，不覆盖其他root历史。

E1–E6训练16/16已耗尽，E6compile剩余额度不变；不重派已经成功的短CPU诊断、N256 metadata、Torch、Harrier、Arctic、Laya或完整训练。N256数值执行、一般时变自由边界、全网稳定性、独立规模/多模态泛化、同等质量全网权重编辑替代BP及端到端加速尚未取得统一资格。Windows生产隔离、严格构建、CTRL/Group真实来源和原500ms门各自保留。all_repository_blockers_closed=false。

## 阅读原件

EVIDENCE.index.json给出本包分片、全包和逐成员SHA；按part编号顺序连接可恢复FOLLOWUP_EVIDENCE_01.tar.xz。CHECKPOINT.json为完整机器可读结果。所有原运行、源身份、成功/失败日志、四份原ZIP和本次独立保全记录均随包保存；打包与发布本身不执行实验。
