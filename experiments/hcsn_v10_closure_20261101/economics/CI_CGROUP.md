# 独立 cgroup v2 内存资格执行

此能力补充尚不等于 GitHub 实际运行已通过。PR 路径过滤只包括工作流自身、两个 helper 和被冻结 joint profile 的实际源码/输入；追加其他报告或 CI 收据不会触发重复资格执行。工作流使用 `contents: read`、无仓库写入、无 secret、10 分钟 timeout。checkout/setup-python/upload-artifact 的精确 pin 均从基线仓库实际读取，出处在 `CI_ACTION_PINS.json`。非 cone sparse checkout 仅取得两个 helper、联合模型五项 Python 源码、冻结 JSON、共同 test 和五份权重；不取得历史大包、训练资料或整个仓库。

本地默认 `ci_cgroup.py probe` 只读能力文件。只有显式 `run` 才尝试在已经启用 memory controller 的指定父级下新建唯一私有 group；它不修改宿主 mount 或父级 controller。缺少权限、memory.peak、cgroup.kill 或其他必要接口时生成 FAIL 收据并返回非零，不能冒充已测得精确峰值。

GitHub-hosted Ubuntu 上，root monitor 通过管道阻塞 fork 子进程，写入并核对私有 `cgroup.procs` 后才释放执行。任务再降为原 runner uid/gid 并设置 no-new-privileges，普通后代继承同一 cgroup。monitor 置身外部，等直接任务退出且该 group 不再 populated 后读取内核 `memory.peak`；超时只对自己新建的 group 使用 `cgroup.kill`，清理只删除自己新建的 group。新 group 有 1 GiB memory.max，任何 OOM-kill 均视为失败。

计量口径是内核定义的、包含后代和 kernel/已归属 page-cache 的 **cgroup memory charge 连续峰值**，不是 RSS/PSS、采样峰值或各进程 HWM 之和。共享文件页可能已归属其他 cgroup，monitor 和 pip 安装也不在任务组内；不能把该数字改称完整物理工作集、所有历史准备或设备能量。

先执行并校验父子进程同时触碰 48 MiB 的控制 fixture，再在新 group 内重放已冻结的真实 NumPy/SciPy 联合模型 evaluation。`ci_joint_replay.py` 核对共同 test、五份权重和 PLAN/TRAINING_COMPLETE 的全部模型源码哈希，只复制必要资料到新的临时输出目录，不覆盖现有结果，也不重新训练或选择参数。任务内包含解释器启动、导入、校验/复制、真实评价、bootstrap 与输出序列化；该边界不代表完整训练阶段。

CI 总是上传能力、stdout/stderr、kernel 收据和新评价输出。成功收据必须与具体 source commit、运行 ID 和冻结模型身份一起使用。没有 GitHub 实际成功运行前，精确内存的外部能力缺口仍保持未验收；能源依旧未知。
