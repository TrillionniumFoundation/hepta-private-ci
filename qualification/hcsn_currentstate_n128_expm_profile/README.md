# N128 matrix-exponential resource profile

Status at source freeze: **HOLD / INTENT_NOT_EXECUTED**.

The first remote source, `b7596b6a06ef6af2fe4fc8d1647f6ec8eedc80bc`,
was rejected before numerical imports in Actions run `43316938536`, job
`131527292274`: its source inventory named two pre-final roster hashes. It
executed 0 matrix exponentials. That RED and its original logs remain intact.
The successor uses a new key ending in `002-after-preimport-red`; it does not
retry or overwrite the terminal first key.

This successor is based on exact #6264 head
`4dfa569b213d02859f76128ed09cacd7a829b91e`. It adds the three previously
published N128 input blobs without changing their bytes, materializes the
authentic #6264 graph once, captures its four unique CSR generators, and calls
SciPy `expm` exactly once per generator at `dt=0.2`.

The sole purpose is to retain a source-bound hosted-CPU measurement of the
matrix-exponential wall time and complete child-process RSS for the actual
N128 operators. It executes no current-state packet propagation, full-state
oracle, Torch operation, optimizer, or training.

Even a successful run does **not** make the N128 current-state candidate
qualified. The dynamic packet core, full-state oracle, serializer/cold
recovery, durable host/cgroup allocation, N256/N512 execution, arbitrary
histories, later cycles, full-network training, asynchronous cost, and HPCA
external custody remain open. The #6247 rare-return negative result, older OOM
and killed attempts, and every historical `UNKNOWN` remain unchanged.
