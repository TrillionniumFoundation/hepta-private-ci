# R18：原生 owner 与真实持久 provider 效果恢复

修正独立复核发现的LEASE窗口后，run02的 **130/130** 个故障／竞争案例通过，涉及 **408** 个真实Rust进程。单独provider的购买计数、费用余额和operation去重账发生真实磁盘状态变化；owner在进程死亡后重试，不会重复增加这些注册效果。旧owner进程被暂停后，由新generation完成执行，再释放旧进程；旧进程拒绝继续写入。

这是本地durable-mailbox协议资格：Rust持有cursor、pending outbox、inbox、费用、时间与不透明数字状态。CTMC概率状态及固定动作来自冻结Python R17的受控重放。它没有把金融矩阵指数、规划器或学习过程移植到Rust，不能据此宣称生产Hepta神经元、实时模型或解析核心质量／性能门已经闭合。

## 执行范围与结果

两组冻结拟合151101／151103、IID／OOD两条有限owner轨迹、full／anchored表示、WAIT→READ与REFRESH固定程序，共16组参考轨迹。96组owner阶段故障、16组provider效果已提交但回复丢失、16组真实旧owner竞争，加一组存储失败和一组LEASE回复丢失，共130组。它们是故障组合，不是130个独立科学样本。

owner覆盖准备、时间已推进、provider回复已取得但owner尚未提交、inbox已持久化、效果已应用和query边界。provider实际READ／REFRESH计数与microcredit收费，跟唯一operation ID一一对应。完整owner数字状态、全部query/action/token/fee、原生纳秒时钟与microcredit账均与Python R17一致；Python参考的完整query记录又与旧R16执行器一致。

独立stdlib审计不导入campaign、runtime、planner或数值模型，重新核对 **130** 组状态、**780** 个query及effect receipt、**260** 条持久LEASE回复和408项进程收据。所有case的最终generation均为2；丢失的旧LEASE回复不会在重放时额外授予第三代。六项负例／幂等检查通过：旧generation、新run、未知operation、变造重复请求、相同请求返回原收据，以及注入ENOSPC后的fail-stop和重启恢复。

## 必须保留的失败与修复

首个socket方案在Rust `UnixListener.bind`和独立Python AF_UNIX bind均得到EPERM；原日志保留。所测IPC是本地磁盘mailbox，未获得socket／网络资格。开发时还修复了禁用fault hook被误触发的错误；原测量与说明保留。

v1的129项注册测试通过，但独立复核发现未覆盖的真实缺陷：LEASE generation与requestID回复分两次持久化，二者之间死亡会让旧请求再次授予generation。v1源码、原冻结和结果全部保留，不能称其LEASE exactly-once通过。v2先在候选状态内计算完整变更，再将generation／billing／request reply一次原子替换提交；所有持久化错误直接使provider退出。随后完整重跑并增加该窗口的真实provider SIGKILL回归。两轮身份见SOURCE_HISTORY，不静默替换历史源码。

## 成本与边界

| 轮次 | 原生子进程CPU | 完整campaign外层CPU | 外层墙钟 |
| --- | ---: | ---: | ---: |
| run01（保留缺陷） | 14.670349 s | 18.947222 s | 94.793008 s |
| run02（修正后） | 13.661849 s | 18.051313 s | 99.743682 s |

两次外层CPU合计 **36.998535 s**；原生子进程已包含在外层，不能再次相加。外层覆盖Python参考帧构造、子进程及本轮最终输出；编译、开发和独立审计没有完整统一外层计量，初次socket尝试CPU未知，未按零计。最大外层／子进程wait4 RSS为77,476KiB，含fork前继承的Python进程页，不能当成纯Rust稳态内存。Rust使用默认未优化编译；且其不执行CTMC数值核，因此这些CPU记录不能与旧完整模型做速度比较，更不是能耗证据。

原子文件替换使用write、file fsync、rename与directory fsync；未做真正断电／OS重启。FNV64只用于偶发损坏检测，不认证恶意本地改写者。有限本地ledger不是跨主机fencing或物理世界效果的一般exactly-once证明。provider的观察token仍是注册fixture，真实变化是独立账本的计数与收费。

生产native金融核、实时内容模型、完整NeuronModelPort资格、网络、GPU、焦耳、开放域跨模态及同质量完整成本采用门仍开放，production_activation保持false。真实生产journal桥接须依其自己的固定源码和测试记录单独判断。

完整原始证据、v1阴性记录与重组说明见 [delivery_small/README.md](delivery_small/README.md)。最终执行源冻结SHA256：`ff5feb5473c415fe9504081f75aa00ecb9905cfe32a50c3da57251367c33c6d4`。
