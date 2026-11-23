# 一次独立的 B 后续使用

该入口用于同一私有研究中，已经完成 A 来源登记、B 冻结后盲评并发布原始配对的参与者。原始配对、B 的后续使用请求和 B 的结果反馈各有自己的用途。一次后续使用固定到一个已选权重清单、一个新任务和一次实际的冷进程。评测费、学习奖励和独立的业务效果证明各有自己的证据来源。

## 运行条件

在开始新研究时，私有 intake 应固定支持四种用途的原生 Linux 命令的绝对路径和 SHA-256，保留登记时的原件。在同一个项目内使用同一份二进制读回全部事件。早期只支持训练和评测的二进制仍与其旧登记绑定。这里没有旧研究的原地换包迁移。研究端的 owner 模式需要 A、B 的独立登记、各自的原始用途授权、A 的来源材料和冻结后 B 的到达顺序。工程测试用的注册身份与真实参与人数单独记账。

以下命令从仓库根目录执行，先将 PYTHONPATH 指向 scripts。HOME_DIR 指该研究的私有 intake 目录，ADMISSION 是已发布的配对登记摘要，MATERIALS 保存原始权重和词表。不要在公共 PR 或工单上传任何真实任务、答案、效果材料或人的凭据。

1. 原始托管方执行 `python -m cell_experiments.paired_consumer HOME_DIR ADMISSION MATERIALS select`。程序重新运行父子冷评，核对每个输出，用未来任务改善并保持父模型旧成功来选定子模型。请求绑定此次选定结果。
2. B 提供后续任务。原始 owner 在该研究的私有 inbox 保留 `consumer-task-<TASK>.json`。TASK 是规范化任务对象的 SHA-256。任务包含模型可见的 input，以及可选的 messages。模型可见 token 与先前面板或已登记训练输入重复时会被拒绝。
3. 运行同一入口的 `request-scope TASK`，将该 JSON 私下交给 `hepta-paired-consent --print-statement`。B 在已登记的人机界面中查看原始材料并亲自提交对应声明。原始 host 用独立的 AuthBus delivery、受保护的 Root socket 和 pidfd 执行 `run TASK DELIVERY ROOT_PID SQLITE_HOME ROUTE_JSON`。启动方继承 fd 3 与 fd 4。只运行预览命令不产生登记回执。
4. B 收到原始答案后决定接受或拒绝，提供相应的结果材料。owner 保留私有文件 `consumer-effect-<EFFECT>.bin`，EFFECT 是文件原始字节的 SHA-256。通过 `outcome-scope TASK EFFECT accepted` 或 `outcome-scope TASK EFFECT rejected` 生成第二份声明。B 在原界面独立提交。owner 再运行 `report TASK EFFECT DECISION NEW_DELIVERY ROOT_PID SQLITE_HOME ROUTE_JSON`。
5. 使用原来的受保护通道分别执行 `verify-request TASK ROOT_PID SQLITE_HOME ROUTE_JSON`、`verify TASK ROOT_PID SQLITE_HOME ROUTE_JSON`，读回两次声明、相同 B 的研究内身份、生成进程、所用模型和输出。一次运行在 STARTED 之后中断且结果未落盘时保留现场；同一个请求没有第二次生成的授权。

本地输出中的 `outcome_evidence=participant_report` 表示 B 对具体结果的报告。独立业务效果与付款状态均须根据对应的原始系统单独核实。此入口从不提交链上交易。

## 复验

在仓库根目录，使用由本工作区 Cargo.lock 构建的 `hepta-paired-consent` 作为末尾参数，运行 `python3 qualification/paired-consent-process-20261123/test_statement.py BINARY` 和 `python3 qualification/paired-consumer-integrated-20261123/test_integrated_contract.py BINARY`。带模型的端到端工程测试为 `PYTHONPATH=scripts python3 -m unittest cell_experiments.test_paired_consumer`，使用原研究的 Python CPU 依赖和权重。测试会单列合成身份。

原始实现见 [研究分支 #7039](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7039) 和 [研究分支 #7041](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7041)。
