# H4 实际原件独立复核

## 结论

本次原件支持 **H4 同一冻结源码在 desktop 上的原门禁全部通过**。独立复核涵盖 20 个有序 gate 的实际 receipt 和完整 raw、301 条 primary FD 记录、294 条实时观察、普通进程六份证明、源码及配置前后记录，以及最终交付与镜像索引。没有重跑 native、修改源码、改变门禁或恢复远端 bulk。

这项结论限定于原记录所声明的 `passed-one-source-desktop-gates-only`。完整二进制归档与最终下载闭合尚待实际归档步骤；真实 WAN、独立管理方、整机恢复、完整模型推理和学习质量不在本次资格内。H1、H2、H3 的原失败状态保持不变。

## 唯一执行与源码身份

| 项目 | 实际值 |
| --- | --- |
| Job | `1a1ade2970f-fc05-5b5c` |
| 幂等键 | `ms-joint-h4-native-6db78-attempt1-93bfcf` |
| 权威终态 | SUCCEEDED，exit 0，2026-11-05 23:05:10.435 UTC |
| 原外层预算 | 5,400 秒；无超时、无自动重试 |
| Coordinator 实际总耗时 | 1,236.8491698539583 秒，包含原始守卫与采集 |
| 源码提交 | `6db78eca53a5acdda0d96873d3f4cd65863426f0` |
| 源码树 | `e91f5994017fc5d2cfe58d405a20ee6ad9376772` |
| 原始完整源码守卫 | 前后逐字一致，11,840 tracked files / 183,410,043 bytes，missing 0、hidden 0、clean |
| 外部执行文件 | 12 个本地冻结文件与 native 环境、执行前后记录的 SHA 全部相同 |
| Git 配置 | 5 个公共及 worktree 配置哈希前后相同 |

本审查读取并核对的是原生执行期间产生的完整源码守卫回执；没有再次访问 desktop 读取整个源码树。原记录中的 ignored 路径不变，记录的 6,094 字节 Python bytecode 前后同 SHA。该观察保留了其明确范围，不被扩展成逐 import 或完整动态运行时闭包证明。

## 原顺序门禁

| 门禁分组 | 实际结果 | 原预算与边界 |
| --- | --- | --- |
| 原 workflow 的精确选择 | 74 / 0 | 11 个 Rust gate，全部精确名称保留 |
| 原兼容控制 | 6 / 0 | 600 秒 |
| Provider controls | 10 / 0 | 600 秒 |
| FinalUse | 50 / 0 | 20.304 秒 / 600 秒 |
| 完整 evidence library | 161 / 0，1 项 ignored | 232.533 秒 / 600 秒；原单例 60 秒不变 |
| Source / diverse Python controls | 135 / 0、32 / 0 | 原 wrapper 默认 3,600 秒，未伪造 hosted 环境 |
| `just fix` | exit 0 | 467.287 秒 / 1,200 秒，六个原指定包 |
| `just fmt --base 1556…` | exit 0 | 4.091 秒 / 300 秒；原输出确为 0 字节并已实际读取 |

全部 20 个 gate 的 command、顺序、receipt SHA、raw 长度及 SHA、状态和源码前后身份均与冻结计划及最终 pipeline 对齐。301 是跨 gate 的 Rust case 执行次数，共 276 个唯一的 `(target, case)`，不能描述成 301 个独立场景。301 次均有唯一 PID/start 的 primary FD 记录；唯一允许两个 target 的 `neural-runtime-input` 仍严格映射那两个指定名称。

## FinalUse 的本次真实子进程归属

50 条原始 `ok` 与 50 条 primary FD 记录精确双射。实时观察中 49 条直接对应 outer FD，另外一条是冻结规则唯一允许的 `killed_owner_releases_lock_but_keeps_claim` 子进程：

- child：PID `1159872` / start `99685414`。
- 直接 parent：PID `1159870` / start `99685394`，对应唯一的该 case outer FD。
- 两次观察时点：`1793919188.1898832` 至 `1793919188.1922848`。
- child、parent 的完整 argv、源身份、可执行文件和实际文件对象相同；两次完整的 7 节点祖先链一致并到达本 gate 的精确 wrapper。
- 实际记录的镜像为 14,103,072 字节，SHA `1383f1adbe7721e1ff362142f0ce35ef755bece0ae2a188cb28e375a2332b923`。

该 child 保持辅助观察身份，`test_outcome_credit=false`。它不增加测试数，也不填补缺失的 primary FD。H3 缺少即时 parent 证据的旧记录没有被回填或重新判定。

## 完整 evidence library 与 ignored child

完整 raw 的 161 个唯一通过名称，严格等于冻结目录的 161 个名称及 161 个唯一 PID/start FD 记录。157 条实时观察全部直接对应这些 FD，没有辅助子进程或匹配错误。其余四个短进程由本次自己的 FD 记录覆盖，不借用其他运行。

同一实际镜像 `a948cdfa5aeafc03fcfc63459e581ca254129f4d878949236e0bf42df3fe725f`（53,291,680 字节）的 `--list --ignored --format terse` 原输出只有 `authbus_outbox_tests::crash_delivery_child`。它不在 161 个选定名称中，也没有被实时采集器错误赋予额外 case 信用；先前只读预审的这一判断已由本轮原件验证。

## 普通进程的实际效果与恢复证明

`effect-pq-product` 两项实际通过，wrapper 耗时 44.961 秒。六份过程证明与成功测试后的完整 `completed.json` 逐项一致，coordinator 的独立 verification 回执也指向本次同一 SHA `ed9670712dd67b5ed74cce07136750a2ec4215e0a83703f9bd0509f70af6833f`。

真实第一代 PID `1154142` / start `99675455` / generation 1，在 provider 已 fsync 原操作且尚未发送 ACK 后被预先围栏的 supervisor 杀掉。第二代 PID `1155773` / start `99678906` / generation 5 使用相同 held file object；第一代完整 hash/copy，第二代明确是 held-object reuse，不能记作第二次完整 hash。

实际通过的源码断言确认：旧 client 与旧世代 grant 被拒，第一次查询缺失保持 Indeterminate，第二次查询找回原操作，第三次本地读取返回同一终态而不增加查询。最终 **POST 1、physical apply 1、lookup 2、nonce 1**，原 key、payload、operation ID digest 与持久 ACK 一致；原 trust/frontier 没有被重置，重开持久库读回同一终态，第二代清理也删除了精确旧租约。

这仍是受控本地 operator/provider、supervisor 预围栏后 SIGKILL 的普通进程组合。它不证明突发掉电、整机或整库恢复、独立 frontier 托管，也不自动关闭 generic tool/provider 的所有 PQ owner 输入缺口。

## 最终交付与镜像索引

原交付 `bda6c712…` 声明的 **131 项、5,522,990 字节**已全部实际读取并核对长度与 SHA，包括原空文件。镜像索引 `a1e42612…` 中的 **597 条观察引用**全部逐原文件 SHA 和记录索引回查，且没有重复、缺失或借用旧运行记录：

- 301 条 primary FD。
- 294 条 live，其中 293 条直接对应 primary FD、1 条是上述明确归属的辅助 child。
- 两代 ordinary daemon 观察，共用一次实际 retained image。

总计 11 个完整镜像、1,674,575,368 字节、32 个原始 retained aliases。八个 primary case 没被轮询看见，均有本次自己的完整 FD 记录；不存在据此补造 live 记录的做法。索引所述无 partial 是“已捕获记录和完整普通进程证明中没有 partial”，不是全 target 文件系统扫描结论。

11 个镜像的记录 SHA/长度都与 H3 完整父索引相同，这是后续内容引用的**元数据重合**。本审查没有读取远端 retained ELF 或 H3 整包；后续 ce96 exporter 仍须实际读取每个选定 H4 文件两次、完整验证唯一 H3 父包，消费端仍须核验两包与全部分片和成员。不能因为本次索引重合就声称已完成二进制持久交付。

## 方法记录与保留边界

独立审查脚本的两次初始错误已保留：一次没有解包 launch 工具的 `job` 层，一次将交付展示状态的大写拼写误等同于 pipeline 小写拼写。修正实际响应结构和显式状态映射后，重读同一原件完成核对；这些是本地审计脚本错误，没有执行或重试 native，也没有改变验收条件。

总审查不授予联合发布资格，不回写历史失败，不改冻结源码或执行配置。H1 下载保持 paused、in-flight 0；本次没有远端 bulk 放行或归档 dispatch。
