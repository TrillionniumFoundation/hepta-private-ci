# Continuous first passage at the two frozen split meshes

当神经元当前状态已知，距离一个固定吸收阈值的漂移与扩散系数为常数时，可以用仓内已有算子求指定期限内的首次触及概率及其内点梯度。原始离散演化在短期限下仍有显著相对误差。移动阈值、神经元间耦合与重置后累计脉冲数需要单独求解。

A neuron with a known positive log-distance to a fixed threshold, constant drift, and constant positive diffusion has an exact continuous first-passage readout. The repository already implements it in `TensorDiffusion.hit_probability` and implements a strict-interior companion `_first_hit_logprob`. This audit cross-checks those existing paths at the rare state in PR #7004. The original finite-mesh evolution runs separately.

For distance $x>0$ and horizon $T>0$, let $X_s=x+\mu s+\sigma W_s$ and $\tau=\inf\{s\geq0:X_s\leq0\}$. Reflection gives

$$
F(x,T)=P(\tau\leq T)=
\Phi\!\left(\frac{-x-\mu T}{\sigma\sqrt T}\right)
+e^{-2\mu x/\sigma^2}\Phi\!\left(\frac{-x+\mu T}{\sigma\sqrt T}\right).
$$

The independent reference integrates the hitting-time density $x\exp[-(x+\mu s)^2/(2\sigma^2s)]/(\sigma\sqrt{2\pi s^3})$. The change of variables $v=(x^2/2\sigma^2)(1/s-1/T)$ prevents tiny mass from disappearing under an absolute quadrature tolerance. Separate 70- and 105-decimal-digit integrations supply the probability and its distance, drift and diffusion derivatives. The density at the deadline supplies the time derivative. A high-precision reflection calculation cross-checks the probability and distance derivative. Physical derivatives follow from $x=\log R-B$, so $\partial_B F+R\,\partial_R F=0$ at the fixed absolute reset. The undiscounted probability is independent of the discount.

The original reset has $x=0.5$, $\mu=-0.12$, $\sigma=0.5$, and delay $0.2$. Both evaluated horizons precede that delay. The underlying continuous process is on the half-line. For a continuous process that coincides until the upper endpoint 2 is first touched, the probability of reaching that endpoint from the reset by either deadline bounds its possible effect on the first-hit probability. Those two upper bounds are $4.78\times10^{-198}$ and $1.16\times10^{-21}$. The frozen continuous-time Markov chain has its own discrete transition law.

| Horizon | Continuous probability from independent integral | FP64 probability relative error | Largest relative error over four probability derivatives | Original CTMC divided by continuous probability, grading 1 and 0 |
|---|---:|---:|---:|---:|
| 0.01 | 1.9367990970040388e-23 | 2.56e-15 | 2.61e-15 | 2,078,586.19 and 804,116.09 |
| 0.1 | 0.0019850919213766752 | 2.62e-16 | 4.48e-16 | 1.00102966 and 0.99456522 |

The companion log readout agreed to within $1.61\times10^{-13}$ in absolute log probability across 64 positive nodes, two time horizons and two fixed geometries. At the shorter horizon, each grid had one subnormal and two zero FP64 probability outputs. The log output remained finite, including at $T=10^{-5}$ for the original reset where the probability output was zero. The calculated gradient vectors, their maximum componentwise relative errors and all counts appear in `RESULT.json`.

Both $F$ and its natural logarithm are dimensionless. For log-distance in units $D$ and model time in units $U$, the stored derivatives in the order $x,T,\mu,\sigma$ have units $1/D,1/U,U/D,\sqrt{U}/D$. The physical derivatives with respect to $B$ and $R$ are per unit of log-boundary and per unit of absolute reset. The numerical gradients refer to the model time unit, without a biological clock calibration.

Writing $a=x^2/(2\sigma^2)$, the short-time limits at a fixed interior distance are

$$
(T\log F,\ T^2\partial_T\log F,\ T\partial_x\log F,
\partial_\mu\log F,\ T\partial_\sigma\log F)
\longrightarrow
(-a,\ a,\ -x/\sigma^2,\ -x/\sigma^2,\ x^2/\sigma^3).
$$

At $T=10^{-5}$ the largest relative difference from these limits was $1.15\times10^{-4}$. At fixed $T=0.01$, setting $z=\mu\sqrt T/\sigma$ gives $\partial_x F(0+,T)=-2\phi(z)/(\sigma\sqrt T)-2\mu\Phi(z)/\sigma^2$. The computed gradient at $x=10^{-6}$ agreed to within $9.60\times10^{-7}$ relative. Values at the boundary and zero deadline follow the existing atom convention. Automatic differentiation is tested only in the strict interior.

This readout describes the first event of an active excursion with known initial state. A moving boundary, a state-dependent or interacting generator, unobserved state, and renewed event counts require their own modeling and qualifications. In particular, using the continuous first-hit mass as an extra feature leaves the Markov chain's survivor and reset masses unchanged. Replacing only its flux with this value would require a new, conservation-consistent evolution. The existing finite-mesh gate still records its original rare-hit failure.

## Reproduction

从包含本证据目录与 #7004 提交的仓库开始，创建精确提交的独立工作树，只复制本目录。以下环境为 Linux CPU、CPython 3.12，本次使用 3.12.14。NumPy 和 SciPy 版本也与原 split 工作流一致。

```sh
git worktree add --detach /tmp/hcsn-halfline-src 4a3a61f1d68a9adbc738f4f5374b01467699c184
cp -R qualification/hcsn_halfline_readout /tmp/hcsn-halfline-src/qualification/
cd /tmp/hcsn-halfline-src
python3.12 -m venv /tmp/hcsn-halfline-env
. /tmp/hcsn-halfline-env/bin/activate
python -m pip install numpy==2.3.5 scipy==1.17.0 mpmath==1.3.0
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu
```

三个入口依次复算连续读出、原离散资格和既有对数风险梯度测试。

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m qualification.hcsn_halfline_readout.verify --output /tmp/hcsn-halfline.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m qualification.hcsn_split_mesh.qualify --current-source --output /tmp/hcsn-split-evidence-new
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m unittest -v qualification.hcsn_differentiable.tests.test_logrisk qualification.hcsn_differentiable.tests.test_logrisk_hessian
```

The split runner requires a fresh output directory. `protocol.json` binds the tested hypotheses, tolerances and upstream Git object identities. The verifier checks all 35 inventory files and 12 designated Git blobs, some of which overlap that inventory. `UPSTREAM_TESTS.json` records the eight original tests and the unchanged split inventory. Runtime versions are in `RESULT.json`. The six raw files in `upstream-run.zip` record the original current-source runner outputs and the separate log-risk suite. Unzip the archive to read the source inventories, stdout, stderr and machine-readable original result. The assay uses CPU FP64 for the existing readouts. Absorbing-boundary models of individual neurons were published by Gerstein and Mandelbrot in 1964. Brown gives the first-passage density with drift on page 6. [Gerstein and Mandelbrot (1964)](https://pmc.ncbi.nlm.nih.gov/articles/PMC1367440/) · [Brown, equation 2.16](https://sites.stat.columbia.edu/liam/teaching/neurostat-spr11/papers/brown-et-al/LesHouches.pdf)
