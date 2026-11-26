# 固定宿主 metadata profile（尚未执行）

此新增 profile 只观察 Ubuntu 24.04 / CPython 3.12.3 的宿主和已安装 wheel 身份，运行五个纯字典宿主负控。登记状态为 REGISTERED_NOT_EXECUTED；此处没有新宿主通过结果。

## 原问题和来源

原 hosted-runtime-snapshot V2 的 ubuntu-latest 后来解析为 Ubuntu 26.04.1，固定 Python 3.12.3 在 setup-python 阶段失败。原 workflow、REQUEST/V2、SOURCE_FREEZE/V2 和原 observer 全部保留，不更新旧 hash。

旧 attempt002（source1960091、run44253300311/job134628918636）已有实际 Ubuntu 24.04 / Python 3.12.3 观察，原观察 SHA 为 c68136d3c80ff4f46feee57556a4d09adaf2e1e1fa6dd14828d353bfc6b64233。其 runtime/resource admission 仍为 false；它证明旧记录存在，不替代新 CI 的实际结果。

LEGACY_SOURCE.tar.xz 保存13个原文件与一个成员清单，补齐旧 verifier 所需 REQUEST.json 和 attempt001 的原 log/terminal。V2 的11个 SHA 可完整比对。新 profile 只做字节核验，不执行原 verifier、原五项控制或 observer.observe()。

原 observer 的 _distribution、_sha256、_meminfo、_cgroup_chain、_read 被原字节加载后用于 metadata。不会调用 _runtime/observe，不导入 NumPy/SciPy/Torch 或 qualification；导入守卫和子进程/网络 audit guard 在 helper 调用前生效。

## 新来源与计数

SOURCE_FREEZE.json 绑定新 runner、PROFILE、精确 requirements、legacy archive/index 和独立 workflow 共6个文件。原 V2 来源在归档内按原路径和原 freeze 单独核对。新配置不会替换原 freeze 的 workflow pin。

唯一 child 的正向路径固定为：observer module load1；原 distribution2、sha2563、meminfo1、cgroup_chain1、read1；host metadata observation1。前后各做一次新来源与旧来源校验。

host validator 共6次：实际 host1次，五个错误 host 各拒绝1次，分别改变 Ubuntu release、Python、NumPy、SciPy 或 OMP_NUM_THREADS。它们只改内存字典，不安装其他版本或启动另一宿主。

N256 input/serializer、dynamic、expm、Torch、model、optimizer、training 均为0。原数值 future_envelope 与已完成 warm-1 的 key/预算不变。新资料不提升 runtime/resource admission、数学资格或生产状态。

## 一次普通 CI 和资源

只响应精确分支 fix/hcsn-n256-host-metadata-20261126-0198a7 首次创建的普通 push。workflow 与 runner 同时拒绝 run_attempt≠1 和非 created 事件；无 pull_request、workflow_dispatch、矩阵或自动 retry。

原触发器不改，新路径位于 hcsn_ci_readbacks 的独立 engineering 修复目录。发布前应使用新分支 create-only，并核对分支尚不存在；不删除/重建同名分支或追加更新来重开预算。

job 固定 ubuntu-24.04 / Python3.12.3，contents:read、10分钟、4个线程变量为1，保留旧固定 actions SHA。只安装原 NumPy2.3.5/SciPy1.17.0 binary wheels以读取已安装 metadata，不加载其数值代码。

launcher 硬 wall45秒；唯一 child 硬 wall30秒、CPU soft/hard20/21秒、AS256MiB、每个 stream/receipt64KiB。parent 的字节解包在 child 之前，archive14成员、legacy总bytes≤256KiB。安装与checkout成本属于 job10分钟上限。

输出目录与 CHILD_STARTED 原件只创建一次。成功、拒绝、超时均保留原 STARTED、child STARTED、RESULT（若生成）、LAUNCH_RESULT、stdout/stderr与原 legacy 字节；没有伪造缺失结果。setup-python 或安装阶段失败时以真实 Actions 原日志为准，不重试。

## 执行前条件与范围

root先完成静态独立审查、官方fmt及新来源重新绑定，再以一个 create-only branch publication 触发普通CI。不得在本地预跑driver、旧verifier、旧observer或N256协议；不能把当前未执行状态写成PASS。

入口为 `python -I -B qualification/hcsn_ci_readbacks/engineering_repairs_20261126_0198a7/n256_host_profile/run_profile.py --output <fresh-directory>`，并要求真实GitHub push环境、精确branch/source/workflow identity。该命令不是第二次执行授权。

成功只能关闭这份新宿主metadata配置的实测边界。它不重写旧失败、不证明矩阵指数一致性、不提供新数值预算，也不证明全部CI通过。所有原件与当前结果按各自identity解释。
