"""Finite Brownian cells and explicitly free-endpoint digital features.

Source of the image-law construction: R8 kernels.py at 74cf5f30a4e87a2666c57b3f8fba38f8d09fdfd3.
Active states are voltage representatives, then LOWER refractory, then UPPER
refractory. Every interval permits at most one fresh event. Old refractory
states release at the interval end. Repeated projection is an approximation to
continuous dynamics; the finite transition and its derivatives are well defined.
"""
import math

import torch
from torch import nn

VERSION = "digital-read-before-brownian-images-v1"
RAW_NAMES = ("boundary", "diffusion", "gain", "drift_bias", "reset_plus", "reset_minus", "recovery_rate")
THRESHOLDS = (-0.5, 0.0, 0.5)
HORIZONS = (0.25, 0.75, 1.5)
MAX_DT = 2.0
RESET_SD = 0.12


def normal_cdf(z):
    return 0.5 * torch.erfc(-z / math.sqrt(2.0))


def log_normal_interval(lower, upper):
    """Stable log P(lower < N(0,1) <= upper), including equal finite bounds."""
    lower, upper = torch.broadcast_tensors(lower, upper)
    if bool(torch.any(~torch.isfinite(lower)) or torch.any(~torch.isfinite(upper))
            or torch.any(upper < lower)):
        raise ValueError("normal interval requires finite ordered bounds")
    right = lower >= 0
    a, b = torch.where(right, -upper, lower), torch.where(right, -lower, upper)
    small, big = torch.special.log_ndtr(a), torch.special.log_ndtr(b)
    positive = big > small
    delta = torch.where(positive, small - big, -torch.ones_like(big))
    result = big + torch.log(-torch.expm1(delta))
    return torch.where(positive, result, torch.full_like(result, -torch.inf))


def normal_interval(lower, upper):
    return log_normal_interval(lower, upper).exp()


def gaussian_events(mean, variance, lower, upper):
    """(put, idle, call) = (X<=lower, lower<X<=upper, X>upper).

    At variance zero these are indicator atoms. Equal strikes have no idle mass.
    This utility describes an unbounded Gaussian endpoint, without prior reset.
    """
    mean = torch.as_tensor(mean, dtype=torch.float64)
    args = [torch.as_tensor(v, dtype=mean.dtype, device=mean.device) for v in (variance, lower, upper)]
    mean, variance, lower, upper = torch.broadcast_tensors(mean, *args)
    if bool(torch.any(~torch.isfinite(torch.stack((mean, variance, lower, upper))))
            or torch.any(variance < 0) or torch.any(lower > upper)):
        raise ValueError("Gaussian events require finite variance>=0 and lower<=upper")
    positive = variance > 0
    sd = torch.sqrt(torch.where(positive, variance, torch.ones_like(variance)))
    a, b = (lower - mean) / sd, (upper - mean) / sd
    smooth = torch.stack((normal_cdf(a), normal_interval(a, b), normal_cdf(-b)), -1)
    atoms = torch.stack((mean <= lower, (mean > lower) & (mean <= upper), mean > upper), -1)
    return torch.where(positive[..., None], smooth, atoms.to(mean.dtype))


def _lower_exit(x, drift, sigma, dt, width, terms):
    k = torch.arange(-terms, terms + 1, dtype=x.dtype, device=x.device)
    distance_signed = x[..., None] + 2 * width * k
    distance = distance_signed.abs()
    mu, scale = drift[..., None], sigma * math.sqrt(dt)
    log_hit = torch.logaddexp(
        torch.special.log_ndtr((-distance - mu * dt) / scale),
        -2 * mu * distance / sigma.square() + torch.special.log_ndtr((-distance + mu * dt) / scale))
    weighted = torch.exp(mu * (distance - x[..., None]) / sigma.square() + log_hit)
    return (distance_signed.sign() * weighted).sum(-1)


def brownian_first_exit(x, drift, sigma, dt, boundary, image_terms=12):
    """Unconditional competing (lower, upper) exit probabilities by dt."""
    x, drift = torch.broadcast_tensors(x, drift)
    lower = _lower_exit(x + boundary, drift, sigma, dt, 2 * boundary, image_terms)
    upper = _lower_exit(boundary - x, -drift, sigma, dt, 2 * boundary, image_terms)
    return torch.stack((lower, upper), -1)


def brownian_killed_bins(x, edges, drift, sigma, dt, boundary, image_terms=12):
    """Bin masses jointly with no earlier exit; no normalization by survival."""
    x, drift = torch.broadcast_tensors(x, drift)
    k = torch.arange(-image_terms, image_terms + 1, dtype=x.dtype, device=x.device)
    length = 2 * boundary
    shifted_x, mu = x[..., None, None] + boundary, drift[..., None, None]
    shift = 2 * k * length
    a, b, scale = edges[:-1, None] + boundary, edges[1:, None] + boundary, sigma * math.sqrt(dt)
    mean1, mean2 = shifted_x - shift + mu * dt, -shifted_x - shift + mu * dt
    log1 = -mu * shift / sigma.square() + log_normal_interval((a - mean1) / scale, (b - mean1) / scale)
    log2 = -2 * mu * (shifted_x + k * length) / sigma.square() + log_normal_interval((a - mean2) / scale, (b - mean2) / scale)
    return (log1.exp() - log2.exp()).sum(-1)


class FiniteCell(nn.Module):
    """Shared process family; effective learned raw parameters: ordinary=4, others=7.

    Physical envelope: boundary in (.8,1.2), diffusion in (.35,.8), gain in
    (0,.9), drift_bias in (-.2,.2), reset centers in (-.6b,.6b), recovery_rate
    in (.25,2). Thus |drift|<=1.1. Durations are in [0,2]. Ordinary reset and
    recovery inputs are detached fixed zeros and cannot fake effective capacity.
    """
    def __init__(self, mode, raw=None, n_grid=15, image_terms=12):
        super().__init__()
        if mode not in ("ordinary", "clocked", "first_passage"):
            raise ValueError("unknown finite cell mode")
        if not isinstance(n_grid, int) or n_grid < 3 or n_grid % 2 != 1:
            raise ValueError("n_grid must be odd and >=3")
        if not isinstance(image_terms, int) or image_terms < 1:
            raise ValueError("image_terms must be positive")
        value = torch.zeros(7, dtype=torch.float64) if raw is None else torch.as_tensor(raw, dtype=torch.float64).clone().detach()
        if value.shape != (7,) or not bool(torch.isfinite(value).all()):
            raise ValueError("seven finite raw parameters required")
        self.raw = nn.Parameter(value)
        self.mode, self.n_grid, self.image_terms = mode, n_grid, image_terms
        self.n_states = n_grid + 2
        self.register_buffer("edges_normalized", torch.linspace(-1, 1, n_grid + 1, dtype=torch.float64))
        self.register_buffer("centers_normalized", (self.edges_normalized[:-1] + self.edges_normalized[1:]) / 2)

    @property
    def effective_parameter_count(self):
        return 4 if self.mode == "ordinary" else 7

    def physical(self):
        raw = self.raw
        extras = raw[4:] if self.mode != "ordinary" else torch.zeros_like(raw[4:])
        boundary = 0.8 + 0.4 * torch.sigmoid(raw[0])
        return dict(boundary=boundary, diffusion=0.35 + 0.45 * torch.sigmoid(raw[1]),
                    gain=0.9 * torch.sigmoid(raw[2]), drift_bias=0.2 * torch.tanh(raw[3]),
                    reset_plus=boundary * 0.6 * torch.tanh(extras[0]),
                    reset_minus=boundary * 0.6 * torch.tanh(extras[1]),
                    recovery_rate=0.25 + 1.75 * torch.sigmoid(extras[2]))

    def _context(self, symbol, reliability):
        symbol, reliability = float(symbol), float(reliability)
        if symbol not in (-1.0, 0.0, 1.0) or not math.isfinite(reliability) or not 0 <= reliability <= 1:
            raise ValueError("symbol must be -1/0/+1 and reliability in [0,1]")
        p = self.physical()
        return p, p["drift_bias"] + p["gain"] * symbol * (2 * reliability - 1)

    def initial(self):
        return torch.nn.functional.one_hot(
            torch.tensor(self.n_grid // 2, device=self.raw.device), self.n_states).to(self.raw.dtype)

    def reset_distributions(self):
        """Rows after LOWER and UPPER events, respectively; folded Gaussian reset."""
        p = self.physical()
        means = torch.stack((p["reset_minus"], p["reset_plus"])) / p["boundary"]
        z = (self.edges_normalized[None, 1:-1] - means[:, None]) / RESET_SD
        return torch.cat((normal_cdf(z[:, :1]), normal_interval(z[:, :-1], z[:, 1:]), normal_cdf(-z[:, -1:])), -1)

    def transition(self, dt, symbol, reliability):
        """Return T[n,n] and P(fresh event during interval | old state)[n]."""
        dt = float(dt)
        if not math.isfinite(dt) or not 0 <= dt <= MAX_DT:
            raise ValueError(f"duration must be in [0,{MAX_DT}]")
        p, drift = self._context(symbol, reliability)
        if dt == 0:
            return torch.eye(self.n_states, dtype=self.raw.dtype, device=self.raw.device) + self.raw.sum()*0, self.raw.new_zeros(self.n_states)
        x, edges = p["boundary"] * self.centers_normalized, p["boundary"] * self.edges_normalized
        if self.mode == "first_passage":
            active = brownian_killed_bins(x, edges, drift, p["diffusion"], dt, p["boundary"], self.image_terms)
            events = brownian_first_exit(x, drift, p["diffusion"], dt, p["boundary"], self.image_terms)
        else:
            z = (edges[None, :] - (x + drift * dt)[:, None]) / (p["diffusion"] * math.sqrt(dt))
            if self.mode == "ordinary":
                active = torch.cat((normal_cdf(z[:, 1:2]), normal_interval(z[:, 1:-2], z[:, 2:-1]), normal_cdf(-z[:, -2:-1])), -1)
                events = x.new_zeros(self.n_grid, 2)
            else:
                active = normal_interval(z[:, :-1], z[:, 1:])
                events = torch.stack((normal_cdf(z[:, 0]), normal_cdf(-z[:, -1])), -1)
        if bool(torch.any(active.detach() < -2e-11) or torch.any(events.detach() < -2e-11)):
            raise ArithmeticError("image sum has material negative mass")
        active, events = active.clamp_min(0), events.clamp_min(0)
        if self.mode == "ordinary":
            refractory = torch.cat((x.new_zeros(2, self.n_grid), torch.eye(2, dtype=x.dtype, device=x.device)), -1)
        else:
            release = -torch.expm1(-p["recovery_rate"] * dt)
            refractory = torch.cat((release * self.reset_distributions(),
                                    (1 - release) * torch.eye(2, dtype=x.dtype, device=x.device)), -1)
        transition = torch.cat((torch.cat((active, events), -1), refractory), 0)
        if not bool(torch.isfinite(transition.detach()).all()) or float((transition.detach().sum(-1) - 1).abs().max()) > 2e-10:
            raise ArithmeticError("finite transition has nonfinite entries or mass defect >2e-10")
        return transition, torch.cat((events.sum(-1), x.new_zeros(2)))

    def features(self, symbol, reliability, bank=True):
        """[n,12], horizon-major calls or powers 2..10, then position/ref flags.

        Active rows are free_endpoint_conditional_on_active. Refractory rows
        have zero call/position features, not a claim that their put mass is 1.
        """
        p, drift = self._context(symbol, reliability)
        u = self.centers_normalized
        if bank:
            x = p["boundary"] * u
            calls = [normal_cdf((x + drift * h - k * p["boundary"]) / (p["diffusion"] * math.sqrt(h)))
                     for h in HORIZONS for k in THRESHOLDS]
            representation = torch.stack(calls, -1)
        else:
            representation = torch.stack([u.pow(k) for k in range(2, 11)], -1)
        active = torch.cat((representation, u[:, None], u.new_zeros(self.n_grid, 2)), -1)
        refractory = torch.cat((u.new_zeros(2, 10), torch.eye(2, dtype=u.dtype, device=u.device)), -1)
        return torch.cat((active, refractory), 0)

    @staticmethod
    def feature_names(bank=True):
        names = ([f"call_h{h:g}_k{k:g}" for h in HORIZONS for k in THRESHOLDS]
                 if bank else [f"position_power_{k}" for k in range(2, 11)])
        return names + ["position", "lower_refractory", "upper_refractory"]

    def export(self, contexts, bank=True):
        """JSON-ready tables for dictionaries containing dt,symbol,reliability.

        No inputs are silently rounded. Contexts must match native public values
        exactly; the native owner must reject a missing context rather than guess.
        """
        tables = []
        with torch.no_grad():
            for context in contexts:
                dt, symbol, reliability = (float(context[k]) for k in ("dt", "symbol", "reliability"))
                t, events = self.transition(dt, symbol, reliability)
                tables.append(dict(dt=dt, symbol=symbol, reliability=reliability,
                                   transition=t.tolist(), event_probability=events.tolist(),
                                   features=self.features(symbol, reliability, bank).tolist()))
        return dict(schema=VERSION, mode=self.mode, n_grid=self.n_grid, n_states=self.n_states,
                    state_order="active voltage ascending, lower refractory, upper refractory",
                    raw_names=list(RAW_NAMES), raw=self.raw.detach().cpu().tolist(),
                    physical={k: float(v.detach()) for k, v in self.physical().items()},
                    effective_parameter_count=self.effective_parameter_count,
                    image_terms=self.image_terms, maximum_duration=MAX_DT,
                    reset_law=dict(kind="folded Gaussian", normalized_sd=RESET_SD),
                    feature_contract="free_endpoint_conditional_on_active; refractory rows have no free forecast",
                    feature_names=self.feature_names(bank), thresholds=list(THRESHOLDS), horizons=list(HORIZONS),
                    initial=self.initial().tolist(), contexts=tables,
                    approximation="finite voltage projection; end-of-interval recovery; at most one fresh event per interval")
