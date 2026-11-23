# 私有 bootstrap 解码枚举的原生资格

两种私有枚举载荷在 43e5 的编译诊断中至少为 320 和 2936 字节。候选将两个载荷放入 Box，在原分支内取回所有权。编码函数、Serde 属性、公开签名、版本条件、错误分支和准入路径保留原字节。[唯一产品差异](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/43e5da1bb81369e4e999adfa8558f5ccb5460eb6...2b75c8df6b804b87dd8c3cbca8d8a4b37d1d97d4)

| 验证 | 原 43e5 | 候选 2b75 | 覆盖范围 |
|---|---:|---:|---|
| 三 crate 所有 targets 的原严格编译诊断数 | 115 | 114 | 两版编译退出 101。只移除 bootstrap 解码枚举声明处的原 Clippy 诊断，其余位置与消息相同 |
| 原物理准备 source closure | 12/12 | 12/12 | 未适配的历史 donor 触发原顺序检查。候选保留原匹配返回表达式 |
| 完整 CALLERS | 1,652 个边界通过 | 1,652 个边界通过 | 9,141 份 Rust 文件，826 个受保护文件。770,005 字节输出与 43e5 逐字相同 |
| 原普通 musl libtest | 2/2 | 2/2 | 原 profile hybrid 拒绝用例及原 successor 字段与限界用例 |
| 原 Linux UID0、独立非 Root 子进程 parent | 1/1 | 1/1 | 两个真实终态 StalePrepare 和 Revoked，每个经过 5 阶段 |
| 原生 parent 的只读 codec 观察 | 10/10 次 | 10/10 次 | 每次 2 次精确回编码、2 个编码错误输入和 16 个解码错误输入 |

原生作业使用真实 musl Agentd libtest、原双 bind、原 UID0 和原非 Root 子进程，保留全部生命周期断言。三个测试源采用两臂相同的测试期观察补丁，两臂各自构建出不同的 libtest ELF。严格编译直接检验未插入观察器的产品候选。[固定观察器](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/01fe13991bd95175a9f548574721c50fb2eda733/qualification/bootstrap-wire-proof) [三个托管作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45140670897)

V1 从真实组件产生的 sealed offer 定点读取，不移动共享文件游标。V2 的完整内存文档使用实际组件的 DeploymentData 原输入、一个组件文件的真实元数据，以及原仓明示为不受信 wire 的完整 successor 样本。两路均走生产编码与解码函数。V2 文档只在内存断言中使用。此次 V2 阳性覆盖线格式、版本选择、回编码和错误边界。完整 V2 权限链仍需实际 A 退出、保留原件、V2 登记和后续阶段。[原 V2 准备来源](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43e5da1bb81369e4e999adfa8558f5ccb5460eb6/codex-rs/hepta-agentd/src/authority_host_post_a_publication.rs#L83) [原 post-A 进程用例](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43e5da1bb81369e4e999adfa8558f5ccb5460eb6/codex-rs/hepta-agentd/src/ordinary_q24_post_a_process_tests.rs#L35) [历史 #6284](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6284)

## 复算

在本目录执行 `python3 verify.py . > replay.json`，再执行 `cmp verified.json replay.json`。验证器自行读三个原始 ZIP，核对编译各诊断、具名原测试、两个终态、两臂每臂 10 次观察和源码标识。source-proof.py 可对两份源码 checkout 和历史 donor 文件复算四处精确变换。源比较 SHA 与 guard 身份见 source-proof.json。原物理准备测试与未适配 donor 原失败的输出分别见 source-tests.log 和 donor-control.log。

完整 CALLERS 原输出可用 `gzip -dc callers.json.gz | sha256sum` 校验。SHA256 为 `2de991230d84e60c8d440278ceb189e0f4111ce8b7c200a934ffc7a31257d6c3`。callers-receipt.json 含命令与退出码。托管原 ZIP 的 SHA256 记录在 verified.json，GitHub 工件号为 strict 14802912693、base 14802019208、candidate 14802698832。归档包含测试日志与编译回执，ELF 的 SHA256 来自托管现场回执。

