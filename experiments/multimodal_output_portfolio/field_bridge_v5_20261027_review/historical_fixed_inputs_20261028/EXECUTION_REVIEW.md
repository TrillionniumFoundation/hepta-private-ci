# V5 固定输入 CPU dispatch 诊断：独立科学复核

**诊断执行与证据复核通过；历史原始文件缺口、原科学 FAIL 与准入阻断保持。** 本复核只读取已封存文件，没有导入 Torch、准备输入或调用模型。

登记 commit：`8e09fee8a59f2de40acbb2595f01f648fe8b1ed8`。第二轮 SUMMARY 为290,781 B，SHA256 `cf13fa5f2ea53f0b1e14321f6f6239ed11d5ac60c919a5d89c5ec0fd8a1b2d41`。

## 控制与预算

- 独立重算36个绑定输入、64个冻结依赖、6份登记源码以及全部输入NPZ、raw NPZ、评分分解与forward parity文件的身份。
- 20份输入 NPZ、140个数值数组共49,520,640 B；加文件容器与 manifest 的快照为50,739,261 B。五个条件绑定同一 manifest 和聚合输入 SHA，source/order/condition/boundary、公开输入、target 及 latent noise 全部固定。
- 两个 unset 共40个 batch，对原 forward 的4个返回字段进行了160项记录齐全的 bitwise parity；两次 raw/components/forward-field 文件逐字节一致。两次 unset 也逐字节复现首轮 raw/components 及当前 V5 raw NPZ。
- 本轮140次 generator调用/17,920例，400次 observer调用/51,200个 digit例。独立入口计数为encode140、decode140、observer400；准备阶段模型调用为0。
- 首轮实耗80/320，累计两轮220次 generator、720次 observer；没有训练、optimizer 或 backward 调用。
- 12项磁盘门槛记录一致；最终parent/preparation metadata共896,513 B，小于16MiB。

## 全部条件结果

以下差异数是完整 utility 数组中不相等的标量数，包含 reward/audit 两个 observer；没有加入数值容差。

| 条件 | vs当前 task/clean差异数 | vs历史 task/clean差异数 | vs历史 task最大绝对差 | vs历史 clean最大绝对差 | 历史raw身份匹配 |
|---|---:|---:|---:|---:|---|
| unset_before | 0/0 | 24/4 | 8.1434845922157e-07 | 5.863606930001097e-07 | 无 |
| default | 26/2 | 34/6 | 6.176531315293943e-07 | 5.863606930001097e-07 | 无 |
| avx2 | 28/2 | 36/6 | 8.501112461756222e-07 | 5.863606930001097e-07 | 无 |
| avx512 | 0/0 | 24/4 | 8.1434845922157e-07 | 5.863606930001097e-07 | 无 |
| unset_after | 0/0 | 24/4 | 8.1434845922157e-07 | 5.863606930001097e-07 | 无 |

DEFAULT相对unset改变13个task像素和1个clean像素；AVX2改变14个task像素和1个clean像素，非零像素差均为±1。两者在全部2,560行的logits/probability hash上产生变化，但caption和所有离散observer指标保持一致。AVX512与unset的记录完全一致。

保持当前uint8像素、target及离散指标固定时，五种条件的dequantization→MSE向量逐值相同，按原Python浮点运算顺序重建的utility均精确等于当前V5。该探测没有提供“固定像素评分算术足以解释历史差异”的证据；本轮观测到的utility变化与稀少的量化像素变化相伴。不能据此定位历史CPU或某个具体算子。

没有任何条件匹配历史完整task/clean NPZ的长度与SHA，也没有任何条件复现完整历史utility数组。不选择最接近的capability，不扩展到新seed或其他后端。

## 解释边界与原失败保留

本轮只评估seed17的frozen original action0；没有重放seed29/43或learned ordinary48 checkpoint/trajectory。显式dispatch条件使用unset预生成的固定latent noise，因此是条件化干预，不是原程序在各dispatch下重新抽随机数的端到端重放。ATen capability也不限制所有MKL/oneDNN路径。

首轮DEFAULT失败的实际输入张量未被保留，仍不能追溯到具体构造算子。新方案消除了本轮条件间输入重建的混杂，并没有补写首轮缺失证据。

原forward全字段相等通过受登记源码约束的完整hash回执独立核对；未保留原始浮点logits，本复核没有重新运行模型以重造这些张量。

原AUDIT SHA256仍为`35af3341f3fc283c41beda469e5c9ff2531f7bf01d537cb4dcc9c4a7fd6b42df`；首轮失败SUMMARY SHA256仍为`555ab819d5d3215fc34b901db7a70aa89c4e4363719c5bc8eadfbffadd786642`。科学状态仍FAIL，admission=false，新holdout未授权，原始媒体上传批准阻断保持。本复核及本轮没有上传raw。
