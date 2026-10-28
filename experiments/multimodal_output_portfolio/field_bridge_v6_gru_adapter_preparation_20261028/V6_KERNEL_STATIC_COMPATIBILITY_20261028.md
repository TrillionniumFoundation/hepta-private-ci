# V6 科学 kernel 静态接线核对

**STATIC_AUDIT_ONLY / NOT_REGISTERED / NOT_EXECUTED；科学 FAIL 与 admission=false 保留。**
本轮仅读冻结源码、安装版 PyTorch rnn.py 和固定 JSON metadata；没有 import 科学模块、打开权重或数据文件、构造模型、执行 toy/scientific forward、训练或读取 holdout。

## 确定的接口阻断

冻结 NeuralPortfolio 的 text_encoder 与 text_decoder 都是 stock nn.GRU。现有严格适配器会拒绝 RNNBase 的合法 _flat_weights 注册参数缓存和 _flat_weight_refs 弱引用，因此此前 toy PASS 不能代表已经接通科学模型。安装版 rnn.py 明确由 _init_flat_weights 建立这些缓存，CPU flatten_parameters 不执行 cuDNN storage 打包。下一扩展必须逐一验证名称、顺序、长度、注册参数对象 identity、weakref 目标及派生形状，不可无条件略过这些字段。

## 实际接线约束

- 保留旧 make_model/new_optimizer 与 guard48 kernel；16 个 up/down 参数进入 SGD，base/teacher/observer 仍冻结。original_generator 传 context.original 原始模型，不传 ControlledSnapshot 包装。
- 初始 mixed modes 必须保留：主模型先 eval，随后新 LocalAdapter 的 training=True；其原 base Linear 为 False。不要为适配器另外调用 model.eval() 改变这个身份。capture/restore 放在 measure_state/guarded_block 返回后的正常 autograd 步边界，不能放进 hard_panel 的 inference_mode。
- 训练动作 baseline 17→2、29→3、43→3 只用于 multiplier；生成动作 context.action 仍为17→0、29→3、43→0，两套索引不可混用。
- 旧 training_common.configuration 强制 ridges=[1e-4,.01,1.]。新head固定 ridge1 放在独立候选配置/fit层，不修改旧kernel protocol。
- 不可直接投影整个 Context：显式分离模型引用、外部 Costs、四个development角色的corpus与probe/guard数据。绑定每个batch的condition/noise_seed/source_ids和全部Observation/Target六张量。guard baseline单独绑定reward values及output/source配对，避免同一array在context与guard中重复形成alias。
- 每个未来48-step块的data/noise tape、clock、remaining budget与baseline index进入record。零动作/拒绝均前进逻辑时钟且收费；物理Costs不随branch回滚。
- 原 local_hash/optimizer_hash/frozen_base_hash、panel_identity 与新 typed codec 的digest编码不同，分别命名存储，不能交叉当作同一SHA算法比较。
- shown kernel的data/noise Generators逐调用局部构造，branch边界没有持久named generator；使用明确空registry，同时保留Torch/Python/NumPy全局RNG。这是静态推断，尚非科学重放证明。

## 仅由源代码/metadata能推出的容量

三个模型config均声明hidden96；8个rank8 adapter共18,144标量/16数组。若使用已拟定float32运行时：参数本体每checkpoint 72,576B；参数+全部梯度+全部momentum数组最多217,728B。按144 parent+576 branch-terminal+24 prefix-terminal+36 rollout-terminal=780个checkpoint，分别为56,609,280B和169,827,840B；都还没有header、guard、RNG或其它证据。

每probe输出512行，仅uint8像素802,816B；720份probe像素逻辑payload为578,027,520B。39份task/clean配对endpoint的像素逻辑payload为156,549,120B，总计734,576,640B。旧 save_hard 使用 np.savez_compressed，所以这些未压缩数字**既不是磁盘文件大小，也不能用来宣称500MiB raw gate已失败或已通过**。完整serializer/Unicode/ZIP/trace/head/失败保留/restore/archive预算仍未证明。

## 下一窄阶段

新目录实现exact-stock CPU GRU缓存验证扩展，继承原capture/restore主体和严格拒绝默认；以函数完整bytes/AST对照绑定仅复制的_parts/_description，明确其局部global引用接缝。只跑tiny GRU参数/SGD/RNG replay和坏cache/override首写前拒绝，保持此前两阶段与全部科学freeze字节不动。

机器报告包含逐文件SHA、完整接线表及条件容量计算：V6_KERNEL_STATIC_COMPATIBILITY_20261028.json。
