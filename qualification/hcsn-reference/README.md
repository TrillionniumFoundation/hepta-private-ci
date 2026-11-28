# Hepta Continuous Spiking Network

A PyTorch reference network for the He–Xiong continuous free-boundary experiment. Each hidden unit holds a distribution of margins above an absorbing boundary and a refractory compartment. The only signal passed from one layer to the next is the log ratio of its actual endogenous boundary to its reference boundary. An ordinary task loss can train both hidden layers through PyTorch backpropagation.

The financial operator uses the equilibrium barrier, equity value, and difference between default-free and risky debt under the same liquidity discount from [He and Xiong, Journal of Finance, 2012](https://www.princeton.edu/~wxiong/papers/rollover.pdf). The input modulates contract principal. The previous population’s average equity sets the strength of a force toward the reset margin, and its monetary credit loss drives the physical margin toward absorption. Both gains are nonnegative. Recent firing feeds back into the next boundary. This last link allows a boundary-only downstream layer to observe changes in recent firing.

The neural transport assumes a linear change in log boundary over one interval. The resulting constant relative drift includes the boundary speed. Under this drift, the absorbed Brownian transition is integrated over every destination bin, including the open upper tail. Fired mass spends one full interval in the refractory compartment before reset. Replacing the conditional position in each bin by its grid representative is a numerical approximation. Time and firing rates are expressed in model units. Credit loss, first-hit probability and fired mass have separate meanings. This reference does not calibrate biological time or physiological parameters.

## Run

From this directory, with Python 3.10+, PyTorch, NumPy and SciPy installed:

```python
import torch
from hepta_spiking import HeptaContinuousSpikingNetwork, Prices, Contract

law = Prices(Contract())
print(law.boundary, law.equity(.18), law.credit_loss(.18), law.hit(.18))

net = HeptaContinuousSpikingNetwork(8, 16, 4, layers=2, atoms=12, dtype=torch.float32)
frames = torch.randn(24, 6, 8)
logits, state = net(frames)
target = torch.tensor([0, 1, 2, 3, 0, 1])
loss = torch.nn.functional.cross_entropy(logits[-1], target)
optimizer = torch.optim.Adam(net.parameters(), lr=.001)
optimizer.zero_grad(set_to_none=True)
loss.backward()
optimizer.step()
```

For streaming inference, use `net.eval()` under `torch.no_grad()`, then pass `state` as the second argument on the next time chunk. A state is per trajectory, layer and parameter snapshot. Reinitialize or replay the history after a parameter edit when a consistent state under the new model is required. FP32 and FP64 are supported transport formats. State exposes active mass, refractory mass, normalized log boundary, population equity and monetary loss.

## Verification

```bash
python -m unittest -v test_reference
```

The tests compare the absorbed distribution with direct density quadrature, check financial contact and price interpolation across contract principals, check mass conservation and streaming equivalence, compare early-time input gradients with finite differences, train a hidden matrix using a normal optimizer, and cut the only wire between layers. A receiver deprived of this wire produces identical output for distinct input trajectories. The reference network and tests are self-contained. The larger [research and real-data qualification](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7273) documents the complementary stability, identifiability and training results.
