# v7 内存观测模块：003 修复后的独立只读复查

## 范围与版本身份

本复查只读取冻结的 003 源码与 `HANDOFF.json`，未修改源码，未运行或重跑测试、探针、模型或科学确认。原初审 `MEMORY_OBSERVER_REVIEW.md` 保留。

本次读取到的源文件 SHA256 与 003 交接记录一致：

| 文件 | SHA256 |
| --- | --- |
| `process_memory.py` | `a5fa02c065717b3482ec04e581e986168612a795c13381a0e280e4de6a97feba` |
| `probe_memory.py` | `6987027bef56410fdf62104256074090776859fee9e2c038acf5ae9e898855e5` |

## 结论

| 初审问题 | 003 源码复查结论 | 剩余边界 |
| --- | --- | --- |
| P1：稳定漏报已知存活成员仍可能声明完整族 | **在传入完整已知清单的采样调用、以及受控三进程探针中已修复** | 通用 API 的 `required_members` 仍可省略；调用方必须传入全部已登记、预期存活的身份。不能据此前后枚举一致排除未知或短命后代 |
| P2：不完整行可永久阻塞握手 | **已修复该读取路径** | 这是读入的时间／字节界限，不构成整棵进程树故障回收保证 |
| P2：退出等待与清理无界 | **直接子进程等待、升级信号和清理尝试已设界限** | 每层只拥有并清理自己的直接子进程；祖先 SIGKILL 可先于子层清理结束，内核中不可及时退出的进程也可能仍未回收 |

当前运行环境的**完整进程族内存仍不可用**，这一 blocker 没有关闭；003 交接记录也明确保持 `full_family_blocker_closed=false`、`full_family_available=false` 和 `full_family_rss_bytes=null`。本复查没有将源码修复或已登记集合成功提升为完整族测量通过。

## P1：两次包含与受控精确集合已经连接

`sample_family(root, required_members=...)` 将所需身份按 mounted-proc PID 建表，拒绝重复身份或不一致的 root，并在枚举前核验每个所需身份仍与当前进程一致。

随后代码在**第一次枚举和第二次枚举分别**要求 `observed.get(pid) == expected_identity`。比较包含 namespace PID 链、start ticks 和父关系，不能用相同 PID 数量替代。缺失、错配或进程变化均抛出 `Unavailable`，返回空 RSS 结果并令完整覆盖为 false；两次族成员列表不相等也拒绝。

受控探针通过 `exact_controlled_family_sample` 传入 parent、child、grandchild 的三个身份。它还比较排序后的完整身份集合与枚举结果，出现额外非预期成员同样拒绝，并清空可用 RSS。最终 `full_family_measurement_available` 同时要求每个样本 `available` 且 `controlled_inventory_exact_match is True`。因此，初审所指出的“已知三个成员仍存活，却把稳定 root-only 清单当成完整族”的受控路径已经关闭。

这一结论依赖真实调用方提供全部已知存活身份。`required_members=None` 仍只把 root 作为已知下界；本 API 无法推断调用方没有传入的登记信息。真实服务适配时须把该参数接到生命周期登记表。前后两次一致也不是原子快照或连续时段证明：未知子进程可能在枚举之间启动并退出，RSS 读数亦是顺序读取。

## P2：部分行超时确实作用于实际读取

`BoundedLineReader` 把实际 fd 设为非阻塞，通过 `select` 等待就绪，再用有界 `os.read` 收集字节；它没有在就绪后调用可能继续阻塞的 `readline`。每次读行保存一个 monotonic deadline，缓冲区没有换行时仍检查剩余时间，默认每行最多等待 10 秒、最多 131,072 字节。对端只写入部分 JSON 而不补换行，会沿超时路径失败；EOF、超长行、无效编码或 JSON 也不会被当成有效握手。

父进程读取 child 的握手／结束响应、child 读取 grandchild 的响应，以及后代等待结束命令，均已使用这一读取器。`wait_owned` 使用带 deadline 的 `wait4(..., WNOHANG)`，不再无限阻塞等待退出。

这些判断来自实际代码路径审阅，不是本复查新运行的故障测试结果。作者的已有验证记录与本只读结论应分别引用。

## 清理保证必须严格限定

`cleanup_owned` 仅处理其 `Popen` 对象所代表、尚未回收的**直接子进程**：先尝试 finish，之后按有限等待升级 SIGTERM 和 SIGKILL。它没有全系统扫描、mounted-proc PID 杀进程或进程组清理。后代的 SIGTERM handler 与 `finally` 会尝试清理该后代自己的直接子进程。

但不能据此写“任何故障都保证整棵树回收”。父层只等待自己的每层 grace；例如 child 正在 `finally` 中清理 grandchild 时，parent 可能已耗尽 grace 并 SIGKILL child，导致 child 尚未来得及完成 grandchild 的清理。对内核中无法及时退出的进程，最终等待也可能到期并抛错。当前代码保证的是有界的直接子进程清理尝试和正常路径的显式回收，不能保证任意祖先／后代故障组合下的全树最终回收。

若故障发生在完整探针 JSON 写出之前，应保留外层 worker 的失败凭证和日志；未确认回收的后代，其内存和完整费用范围继续记为未知。外层某个 `wait4` 凭证不能自动变成全部仍存活后代的完整 CPU 账。

003 的 `HANDOFF.json` 已明确写入这些清理与失败费用边界。最终报告应沿用“尝试清理自己的直接子进程”和“完整族观测仍不可用”的表述。

## 与科学验收的关系

该修复加强了进程身份、已知成员覆盖和探针的有界读取，未恢复缺失的 v6 资产，未接入真实 HCSN 执行，也未建立任何新模型的质量、延迟、内存或经济性优势。已登记三进程集合的有效测量、完整族不可用，以及科学确认未开始，应作为三个不同状态保留。
