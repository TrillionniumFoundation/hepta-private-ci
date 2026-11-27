# Two-layer Hepta Continuous Spiking Network

The sender transforms a learned drive into a principal, evaluates the endogenous boundary, transports a killed diffusion with one-step refractory reset, and computes equity and discounted loss. The receiver has independent trainable input, recurrent and price-feedback weights. The default inter-layer message is the log boundary and seven projections of the live/refractory distribution. Each column is a linear combination of future first-hit functionals under a fixed, data-independent schedule bank. Its coefficients may have either sign. Individual components are coordinates, not firing probabilities. The optional `forced_flow` function returns genuine probabilities for a specified future boundary intervention. Both operations support PyTorch backpropagation. Four ordinary port choices and a full active-state port share the same model entry point.

From the repository root, put `qualification/hcsn_continuous_20261127/core` and this directory on PYTHONPATH. A minimal training forward pass is

```python
import torch
from predictive import PredictiveSpikingNetwork

net = PredictiveSpikingNetwork(input_size=5, width=8, outputs=3, port="predictive")
frames = torch.randn(24, 4, 5, dtype=torch.float64)
labels = torch.randint(0, 3, (24, 4))
logits, state = net(frames)
loss = torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels.flatten())
loss.backward()
```

Use a previous state to stream successive windows. To truncate backpropagation through time, detach the tensors at the chosen chunk boundary. To predict the flow for a supplied future relative log boundary, pass a tensor with shape [horizon,batch,width] to `forced_flow(net.sender, state[0], levels)`. This is a conditional intervention. Learned future inputs can generate other boundaries. Layer and readout weights remain ordinary trainable parameters. Use `net.to(device=..., dtype=...)` to control device and precision; CPU double was verified here. The fixed basis is calibrated for these specific twelve atoms, model time step .25, and the specified physical law. Fitting a different diffusion law would require updating the projection bank. The class exposes no claim of lossless compression or universal superiority.

The independent NumPy replay matches the projected-intervention recurrence within 7.7e−17. All named parameter blocks and the input receive finite gradients. Maximum absolute directional-gradient disagreement with two-sided differences was 1.90e−12. Streaming split and causal-prefix checks had zero difference on the tested tensors. Training the two physical layers on a small diagnostic sequence brought cross-entropy from 0.68169 to 0.23009 in 65 AdamW updates. This check establishes implementation behavior. See sibling neurons/ and synapse/ for actual recordings with separate held-out labels; these evaluated constructed encoders, not end-to-end fitting of the class above.
