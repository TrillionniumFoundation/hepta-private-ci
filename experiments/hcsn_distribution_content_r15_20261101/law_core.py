"""Finite regenerative probability/content state with causal learned observations.

The uniform baseline comes from frozen R14 ZeroDelayFlow. The default explicitly
extends it with a nonuniform tail; neither generator learns a moving boundary.
"""

from collections import OrderedDict
import math

import numpy as np
from scipy.linalg import expm
import torch
from torch import nn

from experiments.hcsn_validation_r14_20261101.numerics.zero_delay import ZeroDelayFlow
from .tail_grid import TailGridFlow


class DistributionContentCore(nn.Module):
    """Carry a spatial law and its position-conditioned content first moment.

    State is an explicit dictionary: probability [B,S], content_moment [B,S,W].
    S includes an absorbing upper cemetery, whose content is never read out.
    ``step(x, state, dt)`` returns (feature, successor_state).  No hidden mutable
    recurrent state or future observation is kept inside this module.
    """

    FAMILIES = ("analytic_distribution", "ordinary_distribution")
    ABLATIONS = ("none", "content_independence", "mean_position", "readout_independence")

    def __init__(self, family="analytic_distribution", width=16, seed=0,
                 n_positions=182, spacing=1/17, x=1., mu=-.25, sigma=1.,
                 reset=.8, ablation="none", cache_size=128, n_anchors=12,
                 tail_spacing=.5, tail_upper=60.):
        super().__init__()
        if family not in self.FAMILIES or ablation not in self.ABLATIONS:
            raise ValueError("Unknown dynamics family or execution ablation")
        if n_positions < 2 or width < 1 or cache_size < 1 or n_anchors < 2:
            raise ValueError("Positive width/cache and at least two positions required")
        self.family, self.width = family, width
        self.ablation, self.cache_size = ablation, cache_size
        self.n_anchors = min(n_anchors, n_positions)
        self.config = dict(family=family, width=width, seed=seed,
            n_positions=n_positions, spacing=spacing, x=x, mu=mu, sigma=sigma,
            reset=reset, ablation=ablation, cache_size=cache_size, n_anchors=self.n_anchors,
            tail_spacing=tail_spacing, tail_upper=tail_upper)
        if tail_spacing is None:
            self.reference = ZeroDelayFlow(x=x, mu=mu, sigma=sigma, reset=reset,
                spacing=spacing, upper=(n_positions+1)*spacing, count_cap=0)
        else:
            self.reference = TailGridFlow(x=x, mu=mu, sigma=sigma, reset=reset,
                spacing=spacing, fine_positions=n_positions, tail_spacing=tail_spacing,
                upper=tail_upper, count_cap=0)
        self.n_positions = len(self.reference.positions)
        upper_rate = float(np.asarray(self.reference.up).reshape(-1)[-1])
        # Sum event marks, retain the upper cemetery, exclude the count reward.
        generator = self.reference._operator(1, self.reference.up,
            self.reference.down, self.reference.reset_law).toarray()[:-1, :-1]
        initial = np.r_[self.reference.initial_law, 0.]
        # Ordinary comparator: one exponential mixing rate, equal state capacity.
        # Match the reflecting active law's stationary profile and slowest rate;
        # preserve the same upper-exit hazard instead of silently deleting loss.
        reflected = generator[:-1, :-1].copy()
        reflected[-1, -1] += upper_rate
        system = reflected.copy()
        system[-1] = 1.
        rhs = np.zeros(self.n_positions); rhs[-1] = 1.
        stationary = np.linalg.solve(system, rhs)
        rates = np.linalg.eigvals(reflected).real
        mixing_rate = -float(np.sort(rates)[-2])
        if stationary.min() < -1e-12 or mixing_rate <= 0:
            raise ValueError("Invalid ordinary stationary/mixing calibration")
        ordinary = np.zeros_like(generator)
        ordinary[:-1, :-1] = mixing_rate * (stationary[:, None]-np.eye(self.n_positions))
        ordinary[-1, -2] = upper_rate
        ordinary[-2, -2] -= upper_rate
        self.register_buffer("generator", torch.tensor(generator, dtype=torch.float64))
        self.register_buffer("ordinary_generator", torch.tensor(ordinary, dtype=torch.float64))
        self.register_buffer("initial_probability", torch.tensor(initial, dtype=torch.float64))
        self.register_buffer("positions", torch.tensor(self.reference.positions, dtype=torch.float64))
        # Refine numerical resolution without silently increasing learned capacity.
        coordinate = np.linspace(0., self.n_anchors-1, n_positions)
        basis = np.zeros((self.n_positions, self.n_anchors))
        basis[:n_positions] = np.maximum(0., 1.-np.abs(coordinate[:, None]-np.arange(self.n_anchors)))
        basis[n_positions:, -1] = 1.  # Constant physical-anchor extrapolation.
        self.anchor_positions = np.linspace(spacing, n_positions*spacing, self.n_anchors).tolist()
        self.register_buffer("position_basis", torch.tensor(basis, dtype=torch.float32))
        self.ordinary_calibration = dict(mixing_rate=mixing_rate,
                                        stationary_profile=stationary.tolist())
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.candidate = nn.Linear(2*width, width)
            self.write = nn.Linear(2*width, width)
            self.evidence = nn.Linear(2*width, self.n_anchors)
            self.position_content = nn.Parameter(.05*torch.randn(self.n_anchors, width))
            self.position_write = nn.Parameter(torch.zeros(self.n_anchors, width))
            self.position_read = nn.Parameter(.05*torch.randn(self.n_anchors, width))
        self._cache = OrderedDict()
        self.cache_hits = self.cache_misses = 0

    def initial_state(self, batch, device=None, dtype=None):
        device = self.position_content.device if device is None else device
        dtype = self.position_content.dtype if dtype is None else dtype
        return dict(probability=self.initial_probability.to(device=device, dtype=torch.float64)
                        .expand(batch, -1).clone(),
                    content_moment=torch.zeros(batch, self.n_positions+1, self.width,
                                               device=device, dtype=dtype))

    def clear_cache(self):
        self._cache.clear()
        self.cache_hits = self.cache_misses = 0

    def _apply(self, fn, recurse=True):
        result = super()._apply(fn, recurse=recurse)
        if hasattr(self, "_cache"):
            self.clear_cache()
        return result

    def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict,
                              missing_keys, unexpected_keys, error_msgs):
        super()._load_from_state_dict(state_dict, prefix, local_metadata, strict,
            missing_keys, unexpected_keys, error_msgs)
        self.clear_cache()

    def _matrices(self, dt, device):
        generator = self.generator if self.family == "analytic_distribution" else self.ordinary_generator
        generator = generator.to(device=device, dtype=torch.float64)
        if dt.requires_grad:
            return torch.matrix_exp(dt.to(device=device, dtype=torch.float64)[:, None, None]*generator)
        # Exact floating values are keys. No rounding, bucketing or dt clipping.
        values, inverse = torch.unique(dt.detach().cpu().double(), return_inverse=True)
        matrices = []
        for value in values.tolist():
            key = (self.family, float(value).hex(), str(device))
            if key in self._cache:
                matrix = self._cache.pop(key)
                self.cache_hits += 1
            else:
                matrix = torch.matrix_exp(generator*value).detach()
                self.cache_misses += 1
            self._cache[key] = matrix
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
            matrices.append(matrix)
        return torch.stack(matrices)[inverse.to(device)]

    def propagate(self, state, dt):
        """Unobserved physical flow; repeated calls obey this finite semigroup.

        Reset preserves carried content; its first moment therefore obeys the
        same linear generator as probability. No state clipping/renormalization.
        """
        probability, moment = state["probability"], state["content_moment"]
        dt = torch.as_tensor(dt, device=probability.device, dtype=torch.float64).reshape(-1)
        if dt.numel() == 1:
            dt = dt.expand(len(probability))
        if dt.numel() != len(probability) or not bool(torch.isfinite(dt).all()) or bool((dt < 0).any()):
            raise ValueError("One finite nonnegative physical interval per batch row required")
        if not dt.requires_grad and bool((dt == dt[0]).all()):
            matrix = self._matrices(dt[:1], probability.device)[0]
            batch, size, width = moment.shape
            transported = moment.transpose(1, 2).reshape(batch*width, size)@matrix.to(moment.dtype).T
            return dict(probability=probability@matrix.T,
                        content_moment=transported.reshape(batch, width, size).transpose(1, 2))
        matrix = self._matrices(dt, probability.device)
        return dict(probability=torch.bmm(matrix, probability[..., None]).squeeze(-1),
                    content_moment=torch.bmm(matrix.to(moment.dtype), moment))

    def read_state(self, state):
        """Position-dependent content readout; cemetery content stays unavailable."""
        weight = 1.+.5*torch.tanh(self.position_basis@self.position_read)
        return (state["content_moment"][:, :-1]*weight).sum(1)

    def observe(self, state, encoded):
        """Condition on this acquired frame and write content at each position.

        Reweight only the surviving active law; the cemetery mass is preserved.
        This is a learned internal likelihood, not a calibrated physical sensor.
        """
        probability, moment = state["probability"], state["content_moment"]
        context = torch.cat((encoded, self.read_state(state)), -1)
        likelihood = torch.exp(2.*torch.tanh(self.evidence(context)@self.position_basis.T)).double()
        active = probability[:, :-1]
        active_mass = active.sum(-1, keepdim=True)
        denominator = (active*likelihood).sum(-1, keepdim=True)
        scale = active_mass/denominator.clamp_min(torch.finfo(torch.float64).tiny)
        multiplier = likelihood*scale
        next_probability = active*multiplier
        conditioned = moment[:, :-1]*multiplier.to(moment.dtype)[..., None]
        candidate = torch.tanh(self.candidate(context)[:, None]+self.position_basis@self.position_content)
        write = torch.sigmoid(self.write(context)[:, None]+self.position_basis@self.position_write)
        updated = (1.-write)*conditioned + next_probability.to(moment.dtype)[..., None]*write*candidate
        return dict(probability=torch.cat((next_probability, probability[:, -1:]), 1),
                    content_moment=torch.cat((updated, moment[:, -1:]), 1))

    def collapse(self, state, mode=None):
        """Intervene on state under the selected conservation contract."""
        mode = self.ablation if mode is None else mode
        if mode not in self.ABLATIONS:
            raise ValueError("Unknown execution ablation")
        if mode == "none":
            return state
        probability, moment = state["probability"], state["content_moment"]
        active = probability[:, :-1]
        mass = active.sum(-1, keepdim=True)
        if mode == "readout_independence":
            weight = 1.+.5*torch.tanh(self.position_basis@self.position_read)
            weighted_mass = (active[..., None]*weight.double()).sum(1)
            denominator = torch.where(weighted_mass > 0., weighted_mass, torch.ones_like(weighted_mass))
            constant = self.read_state(state).double()/denominator
            collapsed = (active[..., None]*constant[:, None]).to(moment.dtype)
            return dict(probability=probability,
                        content_moment=torch.cat((collapsed, moment[:, -1:]), 1))
        if mode == "mean_position":
            denominator = torch.where(mass > 0., mass, torch.ones_like(mass))
            mean = (active*self.positions).sum(-1)/denominator[:, 0]
            left = (torch.searchsorted(self.positions, mean.contiguous(), right=True)-1).clamp(0, self.n_positions-2)
            fraction = (mean-self.positions[left])/(self.positions[left+1]-self.positions[left])
            reduced = torch.zeros_like(active)
            reduced.scatter_(1, left[:, None], mass*(1.-fraction[:, None]))
            reduced.scatter_add_(1, (left+1)[:, None], mass*fraction[:, None])
            active = reduced
        total_content = moment[:, :-1].sum(1, keepdim=True)
        collapsed = (active/mass.clamp_min(1e-300)).to(moment.dtype)[..., None]*total_content
        return dict(probability=torch.cat((active, probability[:, -1:]), 1),
                    content_moment=torch.cat((collapsed, moment[:, -1:]), 1))

    def step(self, encoded, state, dt):
        successor = self.observe(self.propagate(state, dt), encoded)
        successor = self.collapse(successor)
        return self.read_state(successor), successor

    def forward(self, encoded, dt):
        if encoded.ndim != 3 or encoded.shape[-1] != self.width or dt.shape != encoded.shape[:2]:
            raise ValueError("Expected encoded [B,T,W] and dt [B,T]")
        state = self.initial_state(len(encoded), encoded.device, encoded.dtype)
        result = []
        for index in range(encoded.shape[1]):
            feature, state = self.step(encoded[:, index], state, dt[:, index])
            result.append(feature)
        if not result:
            return encoded.new_empty((len(encoded), 0, self.width))
        return torch.stack(result, 1)

    def diagnose_interval(self, state, dt, count_cap=3):
        """Independent marked SciPy calculation for one unobserved analytic gap.

        Marks start at zero for this interval, not at the beginning of a sequence.
        These diagnostics are not training features or a free online operation.
        """
        if self.family != "analytic_distribution" or not math.isfinite(dt) or dt < 0:
            raise ValueError("Marked diagnostic requires analytic flow and finite dt>=0")
        if type(count_cap) is not int or count_cap < 0:
            raise ValueError("Nonnegative integer count cap required")
        layers, size = count_cap+2, self.n_positions+1
        operator = self.reference._operator(layers, self.reference.up,
            self.reference.down, self.reference.reset_law).toarray()
        matrix = expm(dt*operator)
        probability = state["probability"].detach().cpu().double().numpy()
        initial = np.zeros((len(probability), layers*size+1))
        initial[:, :size] = probability
        successor = initial@matrix.T
        marked = successor[:, :-1].reshape(len(probability), layers, size)
        counts = marked.sum(-1)
        return dict(count_pmf_with_overflow=counts.tolist(),
                    first_hit=(1.-counts[:, 0]).tolist(),
                    expected_count=successor[:, -1].tolist(),
                    upper_loss=marked[:, :, -1].sum(-1).tolist(),
                    probability=marked.sum(1).tolist())
