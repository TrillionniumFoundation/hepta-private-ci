# 固定教师路由参考

本目录实现一个固定的 Qwen 语义路由参考，输入为既有 V5 契约的三个字段，输出为六个操作或显式拒绝。它只分类，不访问数值数据，不执行工具，不修改数值图、Cell 结构或执行器，也没有训练紧凑模型或进行蒸馏。

任务契约和九个示例来自固定提交 `332d8156d081e22405450dd607023689f68f03e1` 的公开 V5 训练源码。只有一个 prompt；执行前冻结源码、prompt、协议和来源文件。独立评估方提供的输入必须仅含 `utterance`、`series_name`、`date`，客户端直接拒绝标签、family、行 ID 或其他额外字段。路由器侧未读取独立留出文本、标签或结果文件。

## 执行

先在允许本地 TCP 的隔离环境执行传输回归：

```bash
python3 -m unittest -v test_teacher_router
```

这些测试使用本地合成 HTTP peer，不访问模型服务或留出材料。scratch 环境禁止 socket 创建，因此本地仅两项纯解析／观察测试可运行；真实 HTTP 测试必须由父任务在远程环境执行。

`FREEZE.json` 已在交付前创建。调用方必须从交付记录固定它的 SHA256，不能在发现评估失败后重新计算哈希当作原候选。

```bash
python3 teacher_router.py \
  --input /absolute/path/serving.jsonl \
  --input-sha256 INPUT_SHA256 \
  --freeze-sha256 FREEZE_SHA256 \
  --output /absolute/path/new-teacher-run \
  --endpoint http://127.0.0.1:18081/v1 \
  --concurrency 4
```

模型固定为 `qwen38-flash-next-uc`；最多四个并发请求，每输入最多一个 POST、256 个输出 token、30 秒绝对请求期限、128 KiB 响应。模型字段是服务标识，并不固定内部权重或采样实现。客户端使用显式给定端点的标准库 HTTP(S) 连接，拒绝重定向，不执行透明网络重试。此实现是独立资格验证程序，不是生产 HTTP 策略或 agent owner 的替代品。

每个请求在网络调用前持久保存原始 body、操作身份和 attempted 记录。原始 SSE、HTTP 状态、provider response ID、usage、延时和失败信息均保留。只有同一 response ID 的 completed 事件及严格 JSON 枚举输出才视为完成。断流、超时、HTTP 错误、错误输出均为 `unknown_or_invalid`，不能记成正确的域外拒绝。

输出目录已经存在时默认拒绝执行。若进程中断，可对同一目录、同一输入及冻结参数增加 `--observe-only`；此模式只解析原有证据，不调用网络，不分配新操作，也不填补未开始的请求。它把观察结果写成新的 `observed-*` 文件，保留原始记录。已提交但没有完整响应的请求保持未知；幂等头不构成供应商去重保证。

## 评估与成本

`results.jsonl` 按原输入序号输出，每行提供 `raw_label`、`accepted_intent`、`accepted`、`status`、原操作／请求指纹、provider ID、usage 和延时。教师程序不接触评估标签，也不自行宣布语义门通过。退出 0 只表示所有请求具备有效终态输出；精确路由覆盖率、错路由、拒绝和 OOD 误接受由独立评估器计算。

沿用预先声明的门：合法请求正确覆盖率至少 80%，OOD 错误接受率不高于 5%。未知结果必须单列，并按失败计入合法覆盖；不能借未知断流提高 OOD 正确拒绝率。V5、V6 和确定性对照应读取完全相同的三字段输入文件，模型、参数和校准不得再改变。oracle／codec 是额外的非语言上限对照，不能向教师提供 task ID。

`SUMMARY.json` 统计所有请求及已知 token。缺失 usage 明确保留为未知；本机 CPU 只覆盖客户端。远端模型的 CPU、内存、训练和权重成本没有被测量，不能用本地客户端的小体积声称这是更轻的 Cell。任何成功结果只能说明这个预训练教师候选在该冻结样本上的路由表现，不能推导出蒸馏已成功、真实业务稳定性、结构独立收益或通用智能。
