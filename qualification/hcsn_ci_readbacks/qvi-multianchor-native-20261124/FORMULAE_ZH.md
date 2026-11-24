# 条件编辑与有限保持证书

令 kappa=2rho/(sqrt(mu²+2rho sigma²)-mu)，s=g/rho，t=g mu/rho²-maintenance/rho，eta=exp(-rho delay)。原模型残量为

F(b;K)=s b+t+s/kappa+K-eta[s a+t+(s/kappa)exp(-kappa(a-b))]。

它对 K 的偏导为 1，且 F_b=s[1-eta exp(-kappa(a-b))]>0。因此给定合法内点目标 b*，K*=K-F(b*;K) 是唯一条件成本反演；必须复核 K*>0、原根区间及成本改动上限。这里没有从外部任务收益自动发现 b*。

源单元原有累计有符号命中向量为 M(x;b)。接收初态 y=c+.31b+.48 w^T M。保持旧初态在固定目标处等价于 A delta=r，其中 A_i=[1,.48M_0(x_i;b*),.48M_1(x_i;b*)]，delta=[delta c,delta w0,delta w1]，r_i=y_old(x_i)-c0-.31b*-.48w0^T M(x_i;b*)。

仅允许常数 bias 时，任意两点误差差固定，因此最小最大误差至少为 |r_i-r_j|/2。新增已有投影支持不会推翻原两坐标的不可达结论。

对任意非零见证向量 u 和 box ||delta||inf<=L，有

||A delta-r||inf >= max(0, (|u^T r|-L||A^T u||1)/||u||1)。

证明：|u^T r| <= |u^T(r-A delta)|+|u^T A delta| <= ||u||1 ||r-A delta||inf+L||A^T u||1。Rust 用外向界计算有限下界，Python Fraction 将所有 IEEE 输入作为精确有理数复核；见证的 L1 也计算实际界，不假定浮点归一化恰为一。

若精确有理消元得到 A^T u=0，则可去掉预算项，得到与参数幅度无关的下界 |u^T r|/||u||1。三行满秩时还有唯一精确解，可直接检查是否在原 box 内。capacity_certificate.py 仅做这样的事后代数，不访问 holdout 或选择候选。

证书只覆盖记录的有限线性接收初态问题。全 49 输出由原冻结传播算子另行验收；有限保护点不推出连续全域保持，接收初态下界也不自动成为 49 输出下界。联合改变源物理 law 或新增网络结构均不在此证书范围。
