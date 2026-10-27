# 分阶段审阅顺序

这是一组相互关联但可分别审阅的研究修复。提交按实际依赖拆分，避免把数千
行实现和大量机器结果当作一次不可区分的更改。原生产路径未修改。

| 阶段 | 内容 | 审阅重点 |
| --- | --- | --- |
| 1 | Joint evidence 数据、模型、行为测试 | 事件去重、共同边际、未知支持、prior/likelihood 分离 |
| 2 | Joint evidence fit/evaluate/audit | 测试前冻结、来源分组、实际 UTF-8 交付、独立公式 |
| 3a | 原生 durable event guard、port/profile | 原 checkpoint 绑定、重试无重复 tick、恢复/fork 一致性 |
| 3b | 原生 owner host | 单个完整 host 协议边界与原 owner 的调用 |
| 4 | 原生 build/client/training/forecast | 依赖与原源码身份、learned eligibility readout、完整 future value |
| 5 | 原生实际实验与 guard probe | 先交付再反馈、后续动作、准入/资源拒绝、所有恢复成本 |
| 6 | 原生独立 audit | 网格完整、实际媒体重读、native replay、外部收益 |
| 7 | Joint training 数据、协议、目标与测试 | actual exponential moment、真实 argmax、监督 proxy 边界 |
| 8 | Joint training 选择与执行 | 相同信息/计算预算、clean replay、validation-only 选择 |
| 9 | Joint qualification 与 original oracle | 新来源、封印、真实媒体、旧 16-plan 上界 |
| 10 | Joint independent audit/statistics | 独立解析/收益、oracle 网格、CE/CI/gate 重建 |
| 11 | 自然来源与公共数据接口 | 固定官方来源、group split、公开/私有记录分离 |
| 12 | 自然语音与 cache | 实际 encoder 复用、生成字节、全成本 |
| 13 | 自然语音 cascade | 真 validation quota 执行、强固定基线、同调用配额范围 |
| 14 | 自然票据 decoder | 缺失标签 mask、candidate support、真实答案与标注图 |
| 15 | 自然视频 generation 与边界测试 | 无 target↔endpoint 泄漏、决策前不免费算 flow、真实像素 |
| 16 | 自然输出独立 audit | 源视频重建、独立评分、全部 batch 成本 |
| 17 | 自然证据安全归档/恢复与测试 | 全逻辑路径、内容地址、模型依赖明确、冲突不覆盖 |
| 18 | 只读 cross-review 工具 | 与作者 scorer 不同的控制核算实现 |
| 19–22 | 四条工作线协议、说明与不可变机器记录 | 先核 freeze / hash，再读 RESULT / AUDIT；负门槛必须保留 |
| 23 | 跨工作线 peer findings | 发现、修复时间、实际运行证据、尚未覆盖范围 |
| 24–25 | 总报告、架构、验收与证据索引 | 六项状态、已证实部分与开放问题一致 |
| 26 | 发布后 CI 原始证据拼写例外 | 13 条精确整行匹配，原文件 hash 不变，其他代码与文本继续检查 |

代码阶段尽量保持在约 500 行以内。原生 host 经最终 rustfmt 从紧凑源码展开
为 515 行，单独一个提交以保留完整的协议边界；guard/port/profile 另有提交。
结果阶段的大 JSON 是已执行实验的完整机械记录。最重的 source-manifest
文件为约 25,000 行原始 document annotation/identity；不应逐行当手写逻辑
审阅，应结合 SHA、分组/来源审计和对应的实际文件读取程序。

建议先读总报告和验收状态，再按上述顺序看实现，最后检查准确执行快照、
原始输出及独立审计。上游旧研究提交是基线，不在本轮重新宣称为新成果。
