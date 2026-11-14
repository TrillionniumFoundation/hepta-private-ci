# 审阅补件：保留原证据，补独立校验

本目录只读取已保存的 d1 数组/聚合量、执行手造源测试和规划计算。
没有重建 TRAIN、构造 validation/正式数据、生成新预测、训练模型或运行确认。
旧 `result.json`、`audit.py`、`audit.json`、历史日志和冻结协议均保留原样。

## 参数 delta 的独立重算

审阅指出，原 audit.py 只检查记录的 delta 为正；这不能算独立核验。
`supplement.py` 现从三份 base 和十二份 final NPZ 的实际数组重新计算
六个内容参数组的 `sqrt(math.fsum((final-base)**2))`，不使用模型/训练函数。
执行前写定比较容差 rtol=atol=1e-12。72 项均严格大于零，和原记录的
最大绝对差 1.7763568394002505e-15。每个模型的 decoder/decoder_bias 与
对应 base 完全一致。输入文件哈希、每项实际重算值与差异见
`saved-array-audit.json`。原 audit 的不足由此补齐，并未追认它原来做过重算。

## 测试日志身份

原 `handmade-final.txt` 是提交前 worktree 的 31 项执行记录，方法名含
`test_invalid_weights_and_no_formal_entrypoint`。随后提交前清理把该方法改名
为 `test_invalid_weights`，并移除其中只检查静态 `hasattr(run, 'evaluate')`
的部分；数值断言未因此加强。旧日志当时没有绑定完整测试源字节哈希，
所以不能把它描述为“精确冻结字节的 31 项日志”，也不伪造该历史哈希。

现在重新执行相同三个模块的 31 项手造/learning/accounting 源测试，退出 0。
新 `frozen-source-tests.txt` 含实际 argv、cwd、HEAD、freeze source commit 和
测试文件 SHA256。执行前后均逐文件比对原冻结 receipt，所有原冻结源码
一致；新日志中的测试名就是冻结文件里的名字。新日志独立保存，旧日志
不改名、不覆盖。它不构造任何实验 split。

## 结论限制的更正与强调

- 相对 endpointwise best A，N-stratified greedy 差值为 seed11
  -0.000651042、seed23 -0.000651042、seed47 -0.000325521，三个均略负。
  原报告的“一个 seed 略正”仅指相同 stratified A 比较，不能推广到 best A。
- 三个模型 seed 共用同一个 TRAIN 诊断 panel 和 sampler seed=97013。
  每个方差点只用十二个 minibatch；三次下降不是三次独立抽样复现。
- A 也受益。sampler×objective 差中之差均值只有 +0.000211998，三个值
  -0.000029368、-0.000720472、+0.001385835；不宣称 NDU 独享方差收益。
- N 同时改变相对 CE 的梯度尺度和方向，未隔离 curvature 的因果贡献。
- IID seed11 完整服务均值 A/N=121075.240/75087.021 ns/request。
  这一个波次不能区分真实输出编码成本与执行时序；同架构不提供归因。

补件脚本记录的审计主体父进程 CPU 0.168957958 秒、测试子进程 CPU
0.665752 秒。主体计时从模块导入后开始，非全部工具启动/R&D总CPU；不补造
未测部分。它们均单列 R&D，不作为模型训练预算抵扣。后续确认设计见
`CONFIRMATION_PROPOSAL_V1.md`；它是供父会话合并三路设计的草稿，没有执行授权。
