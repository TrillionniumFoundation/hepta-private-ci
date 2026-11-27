"""Causal v4 comparators with exact interval dynamics and explicit spike events.

The spiking readout is the actual exponential spike trace. An explicitly named
analog readout is available as a stronger hybrid control, never silently used.
ALIF's threshold decays continuously and increments at every physical spike.
Between input observations, currents are held; recurrent controls refresh only
at real observations. Internal spikes are not task output pulses or energy units.
"""

import math

import numpy as np
import torch
from torch import nn


def _surrogate(hard, soft):
    return hard + (soft - soft.detach())


def _elapsed(value, like):
    result = torch.as_tensor(value, dtype=like.dtype, device=like.device)
    if result.numel() == 1:
        result = result.expand(like.shape[0])
    if result.shape != (like.shape[0],) or not bool(torch.isfinite(result).all()):
        raise ValueError("elapsed time must be finite scalar or [B]")
    if bool((result < 0).any()):
        raise ValueError("negative elapsed time")
    return result


def _mask(value, like):
    result = torch.as_tensor(value, dtype=torch.bool, device=like.device)
    if result.numel() == 1:
        result = result.expand(like.shape[0])
    if result.shape != (like.shape[0],):
        raise ValueError("event mask must be scalar or [B]")
    return result


class EventSpikingEncoder(nn.Module):
    def __init__(self, variant="lif", input_size=22, hidden_size=8,
                 membrane_tau=1.25, threshold=.65, refractory=.1,
                 trace_tau=2.5, adaptation_tau=3., adaptation_strength=.3,
                 resource_penalty=.5, current_scale=1.8, kick_scale=.35,
                 surrogate_slope=5., readout_mode="spike", feedback_mode="spike",
                 max_interval_spikes=256):
        super().__init__()
        if variant not in ("lif", "alif", "alif_held", "resource_lif"):
            raise ValueError("unknown spiking comparator")
        if readout_mode not in ("spike", "analog") or feedback_mode not in ("spike", "context"):
            raise ValueError("unknown readout or feedback mode")
        constants = (membrane_tau, threshold, refractory, trace_tau,
                     adaptation_tau, adaptation_strength, resource_penalty,
                     current_scale, kick_scale, surrogate_slope)
        if not all(math.isfinite(x) and x >= 0 for x in constants):
            raise ValueError("finite nonnegative constants required")
        if min(membrane_tau, threshold, refractory, trace_tau, adaptation_tau) <= 0:
            raise ValueError("positive time constants, threshold and refractory required")
        if variant == "alif" and adaptation_tau < membrane_tau:
            raise ValueError("ALIF root certificate requires adaptation_tau >= membrane_tau")
        if not isinstance(max_interval_spikes, int) or max_interval_spikes < 1:
            raise ValueError("positive event work cap required")
        self.variant, self.input_size, self.hidden_size = variant, input_size, hidden_size
        self.membrane_tau, self.threshold, self.refractory = membrane_tau, threshold, refractory
        self.trace_tau, self.adaptation_tau = trace_tau, adaptation_tau
        self.adaptation_strength, self.resource_penalty = adaptation_strength, resource_penalty
        self.current_scale, self.kick_scale = current_scale, kick_scale
        self.surrogate_slope, self.max_interval_spikes = surrogate_slope, max_interval_spikes
        self.readout_mode, self.feedback_mode = readout_mode, feedback_mode
        self.input_layer = nn.Linear(input_size, hidden_size)
        self.recurrent_layer = nn.Linear(hidden_size, hidden_size, bias=False)
        nn.init.xavier_uniform_(self.input_layer.weight, gain=.7)
        nn.init.zeros_(self.input_layer.bias)
        nn.init.orthogonal_(self.recurrent_layer.weight, gain=.25)

    def initial_state(self, batch_size, device=None, dtype=None):
        p = self.input_layer.weight
        device, dtype = device or p.device, dtype or p.dtype
        zero = lambda: torch.zeros(batch_size, self.hidden_size, device=device, dtype=dtype)
        state = {k: zero() for k in ("voltage", "context", "refractory_remaining", "spike_trace")}
        state["time"] = torch.zeros(batch_size, device=device, dtype=dtype)
        if self.variant in ("alif", "alif_held"):
            state["adaptation_trace"] = zero()
        if self.variant in ("alif_held", "resource_lif"):
            state["held_threshold"] = torch.full_like(state["voltage"], self.threshold)
        return state

    def _constant_advance(self, state, elapsed, record_spikes):
        v, context, ref = (state[k] for k in ("voltage", "context", "refractory_remaining"))
        threshold = state.get("held_threshold", torch.full_like(v, self.threshold))
        current = self.current_scale * torch.tanh(context)
        wait, available = torch.minimum(elapsed, ref), (elapsed - ref).clamp(min=0)
        attainable = current > threshold
        denominator, numerator = (current-threshold).clamp(min=1e-12), (current-v).clamp(min=1e-12)
        first = self.membrane_tau * torch.log(numerator/denominator).clamp(min=0)
        first = torch.where(attainable, first, available+1.)
        cycle = self.refractory + self.membrane_tau * torch.log(current.clamp(min=1e-12)/denominator).clamp(min=0)
        fires = attainable & (available >= first) & (available > 0)
        hard = torch.where(fires, 1.+torch.floor(((available-first)/cycle).clamp(min=0)), torch.zeros_like(v))
        if bool((hard > self.max_interval_spikes).any()):
            raise RuntimeError("interval spike work cap exceeded")
        unreset = current + (v-current)*torch.exp(-available/self.membrane_tau)
        unreset = torch.where(available > 0, unreset, v)
        soft = torch.sigmoid(self.surrogate_slope*(unreset-threshold)) * (1.+torch.relu((available-first)/cycle))
        count = _surrogate(hard, torch.where(available > 0, soft, torch.zeros_like(soft)))
        last_time = wait+first+(hard-1.)*cycle
        after = torch.where(fires, (elapsed-last_time).clamp(min=0), torch.zeros_like(v))
        post_voltage = current*(-torch.expm1(-(after-self.refractory).clamp(min=0)/self.membrane_tau))
        updated = dict(state)
        updated["voltage"] = torch.where(fires, post_voltage, unreset)
        updated["refractory_remaining"] = torch.where(fires, (self.refractory-after).clamp(min=0), (ref-elapsed).clamp(min=0))

        def trace(old, tau):
            increment = torch.exp(-after/tau)*(-torch.expm1(-count*cycle/tau))/(-torch.expm1(-cycle/tau)).clamp(min=1e-15)
            return old*torch.exp(-elapsed/tau)+increment

        updated["spike_trace"] = trace(state["spike_trace"], self.trace_tau)
        if self.variant == "alif_held":
            updated["adaptation_trace"] = trace(state["adaptation_trace"], self.adaptation_tau)
        events = []
        if record_spikes:
            start = state["time"].detach().cpu().numpy()
            a, b, c = [x.detach().cpu().numpy() for x in (wait, first, cycle)]
            for row, component in np.argwhere(hard.detach().cpu().numpy() > 0):
                for ordinal in range(int(hard[row, component].detach())):
                    events.append({"batch": int(row), "component": int(component),
                                   "time": float(start[row]+a[row, component]+b[row, component]+ordinal*c[row, component]),
                                   "cause": "constant_current_threshold"})
        return updated, count, events

    def _alif_crossing(self, voltage, current, adaptation, remaining):
        # For adaptation_tau >= membrane_tau, a trajectory starting below
        # threshold cannot cross upwards and return below before this endpoint.
        v, i, a, duration = [x.detach().cpu().double().numpy() for x in
                            (voltage, current, adaptation, remaining)]
        def gap(t):
            return i+(v-i)*np.exp(-t/self.membrane_tau)-self.threshold-self.adaptation_strength*a*np.exp(-t/self.adaptation_tau)
        occurs = (duration > 0) & ((gap(duration) >= 0) | (gap(0.) >= 0))
        low, high = np.zeros_like(duration), duration.copy()
        for _ in range(54):
            middle = (low+high)/2
            positive = gap(middle) >= 0
            high = np.where(positive, middle, high)
            low = np.where(positive, low, middle)
        hard = voltage.new_tensor(np.where(occurs, (low+high)/2, duration))
        firing = torch.as_tensor(occurs, device=voltage.device)
        # Implicit crossing derivative on a fixed event sequence; event-count
        # boundary gradients below remain explicitly biased surrogates.
        gap_at = current+(voltage-current)*torch.exp(-hard/self.membrane_tau)-self.threshold-self.adaptation_strength*adaptation*torch.exp(-hard/self.adaptation_tau)
        derivative = -(voltage-current)*torch.exp(-hard/self.membrane_tau)/self.membrane_tau + self.adaptation_strength*adaptation*torch.exp(-hard/self.adaptation_tau)/self.adaptation_tau
        correction = (gap_at-gap_at.detach()) / derivative.detach().clamp(min=1e-7)
        crossing = torch.where(firing, hard-correction, remaining)
        return crossing, firing

    def _alif_advance(self, state, elapsed, record_spikes):
        v, current = state["voltage"], self.current_scale*torch.tanh(state["context"])
        ref, trace, adapt = state["refractory_remaining"], state["spike_trace"], state["adaptation_trace"]
        remaining = elapsed.expand_as(v)
        clock, count = torch.zeros_like(v), torch.zeros_like(v)
        events = []
        for _ in range(self.max_interval_spikes+1):
            if not bool((remaining > 0).any()):
                break
            wait = torch.minimum(remaining, ref)
            trace, adapt = trace*torch.exp(-wait/self.trace_tau), adapt*torch.exp(-wait/self.adaptation_tau)
            remaining, clock, ref = (remaining-wait).clamp(min=0), clock+wait, (ref-wait).clamp(min=0)
            active = remaining > 0
            duration, firing = self._alif_crossing(v, current, adapt, remaining)
            unreset_end = current+(v-current)*torch.exp(-remaining/self.membrane_tau)
            end_threshold = self.threshold+self.adaptation_strength*adapt*torch.exp(-remaining/self.adaptation_tau)
            soft = torch.sigmoid(self.surrogate_slope*(unreset_end-end_threshold))*active.to(v.dtype)
            increment = _surrogate(firing.to(v.dtype), soft)
            v = current+(v-current)*torch.exp(-duration/self.membrane_tau)
            trace, adapt = trace*torch.exp(-duration/self.trace_tau), adapt*torch.exp(-duration/self.adaptation_tau)
            clock, remaining = clock+duration, (remaining-duration).clamp(min=0)
            if record_spikes:
                times = (state["time"][:, None]+clock).detach().cpu().numpy()
                for row, component in np.argwhere(firing.detach().cpu().numpy()):
                    events.append({"batch": int(row), "component": int(component),
                                   "time": float(times[row, component]), "cause": "continuous_alif_threshold"})
            v, trace, adapt = v*(1-increment), trace+increment, adapt+increment
            ref = torch.where(firing, torch.full_like(ref, self.refractory), ref)
            count = count+increment
        if bool((remaining > 1e-10).any()) or bool((count > self.max_interval_spikes).any()):
            raise RuntimeError("ALIF interval event work cap exceeded")
        updated = dict(state)
        updated.update(voltage=v, refractory_remaining=ref, spike_trace=trace, adaptation_trace=adapt)
        return updated, count, events

    def _readout(self, state):
        if self.readout_mode == "spike":
            return torch.tanh(state["spike_trace"])
        return torch.tanh(state["voltage"])+.25*state["context"]+.20*torch.tanh(state["spike_trace"])

    def step(self, state, observation, dt_elapsed, event_mask=True, record_spikes=False):
        v = state["voltage"]
        dt, mask = _elapsed(dt_elapsed, v), _mask(event_mask, v)
        advance = self._alif_advance if self.variant == "alif" else self._constant_advance
        state, count, events = advance(state, dt[:, None], record_spikes)
        state["time"] = state["time"]+dt
        immediate = torch.zeros_like(v)
        if bool(mask.any()):
            if observation is None or observation.shape != (v.shape[0], self.input_size):
                raise ValueError("observation must have shape [B,input_size]")
            observation = torch.where(mask[:, None], observation, torch.zeros_like(observation))
            if not bool(torch.isfinite(observation).all()):
                raise ValueError("nonfinite observed feature")
            previous = state["context"]
            feedback = torch.tanh(state["spike_trace"]) if self.feedback_mode == "spike" else previous
            proposed = torch.tanh(self.input_layer(observation)+self.recurrent_layer(feedback))
            context = torch.where(mask[:, None], proposed, previous)
            if self.variant in ("alif", "alif_held"):
                threshold = self.threshold+self.adaptation_strength*state["adaptation_trace"]
            elif self.variant == "resource_lif":
                threshold = (self.threshold+self.resource_penalty*(1-observation[:, 4:5].clamp(0, 1))).expand_as(v)
            else:
                threshold = torch.full_like(v, self.threshold)
            available = (state["refractory_remaining"] <= 0) & mask[:, None]
            candidate = state["voltage"]+torch.where(available, self.kick_scale*(context-previous), torch.zeros_like(v))
            hard = ((candidate >= threshold) & available).to(v.dtype)
            soft = torch.sigmoid(self.surrogate_slope*(candidate-threshold))*available.to(v.dtype)
            immediate = _surrogate(hard, soft)
            state["context"], state["voltage"] = context, candidate*(1-immediate)
            state["refractory_remaining"] = torch.where(hard.bool(), torch.full_like(v, self.refractory), state["refractory_remaining"])
            state["spike_trace"] = state["spike_trace"]+immediate
            if self.variant in ("alif", "alif_held"):
                state["adaptation_trace"] = state["adaptation_trace"]+immediate
                threshold = self.threshold+self.adaptation_strength*state["adaptation_trace"]
            if self.variant in ("alif_held", "resource_lif"):
                state["held_threshold"] = torch.where(mask[:, None], threshold, state["held_threshold"])
            if record_spikes:
                for row, component in np.argwhere(hard.detach().cpu().numpy() > 0):
                    events.append({"batch": int(row), "component": int(component),
                                   "time": float(state["time"][row].detach()), "cause": "observation_kick"})
        count = count+immediate
        if not all(bool(torch.isfinite(value).all()) for value in state.values()):
            raise FloatingPointError("nonfinite spiking state")
        events.sort(key=lambda e: (e["time"], e["batch"], e["component"]))
        return state, {"latent": self._readout(state), "spikes": count,
                       "actual_counts": count.detach().round().to(torch.int64),
                       "immediate_counts": immediate, "spike_times": events}

    def forward(self, x, dt, event_mask=None, generator=None, record_spikes=False):
        if x.ndim != 3 or x.shape[-1] != self.input_size or dt.shape != x.shape[:2]:
            raise ValueError("expected x[B,T,F] and dt[B,T]")
        if bool((dt[:, 0] != 0).any()):
            raise ValueError("initial observation must have dt=0")
        masks = torch.ones(x.shape[:2], device=x.device, dtype=torch.bool) if event_mask is None else event_mask
        state, outputs = self.initial_state(x.shape[0], x.device, x.dtype), []
        for index in range(x.shape[1]):
            state, output = self.step(state, x[:, index], dt[:, index], masks[:, index], record_spikes)
            outputs.append(output)
        result = {k: torch.stack([o[k] for o in outputs], dim=1)
                  for k in ("latent", "spikes", "actual_counts", "immediate_counts")}
        result.update(final_state=state, spike_times=[e for o in outputs for e in o["spike_times"]])
        return result

    def metadata(self):
        components = {k: self.hidden_size for k in ("voltage", "context", "refractory_remaining", "spike_trace")}
        components["time"] = 1
        if self.variant in ("alif", "alif_held"):
            components["adaptation_trace"] = self.hidden_size
        if self.variant in ("alif_held", "resource_lif"):
            components["held_threshold"] = self.hidden_size
        return {"model": "event_"+self.variant, "encoder_parameters": sum(p.numel() for p in self.parameters()),
                "persistent_state_components": components, "persistent_state_scalars": sum(components.values()),
                "persistent_state_bytes_float32": 4*sum(components.values()), "shared_constant_buffer_bytes": 0,
                "readout_mode": self.readout_mode, "feedback_mode": self.feedback_mode,
                "forward": "closed constant-current evolution; ALIF continuously decaying threshold uses a 54-step bracketed crossing root",
                "backward": "biased event-count surrogate; ALIF additionally differentiates crossing within a fixed event sequence",
                "recurrent_refresh": "real observation events only; no-op splits do not refresh controls",
                "communication_output_cost": "owned by common task, not inferred from internal spike count",
                "energy_measurement": False, "full_lsnn_reproduction": False,
                "state_excludes": "weights, task state, event logs, temporary tensors, autograd history and process overhead"}


class TimeBasisEncoder(nn.Module):
    def __init__(self, input_size=22, hidden_size=8, modes=1, readout_mode="memory", **unused):
        super().__init__()
        if modes < 1 or readout_mode not in ("memory", "analog"):
            raise ValueError("invalid continuous-time comparator configuration")
        self.input_size, self.hidden_size, self.modes, self.readout_mode = input_size, hidden_size, modes, readout_mode
        self.input_layer = nn.Linear(input_size, hidden_size)
        self.recurrent_layer = nn.Linear(hidden_size, hidden_size, bias=False)
        self.register_buffer("taus", torch.logspace(-.90309, 1.20412, modes) if modes > 1 else torch.tensor([1.25]))
        nn.init.xavier_uniform_(self.input_layer.weight, gain=.7)
        nn.init.zeros_(self.input_layer.bias)
        nn.init.orthogonal_(self.recurrent_layer.weight, gain=.25)

    def initial_state(self, batch_size, device=None, dtype=None):
        p = self.input_layer.weight
        device, dtype = device or p.device, dtype or p.dtype
        return {"memory": torch.zeros(batch_size, self.hidden_size, self.modes, device=device, dtype=dtype),
                "context": torch.zeros(batch_size, self.hidden_size, device=device, dtype=dtype),
                "time": torch.zeros(batch_size, device=device, dtype=dtype)}

    def step(self, state, observation, dt_elapsed, event_mask=True, record_spikes=False):
        context = state["context"]
        dt, mask = _elapsed(dt_elapsed, context), _mask(event_mask, context)
        memory = context[..., None]+(state["memory"]-context[..., None])*torch.exp(-dt[:, None, None]/self.taus)
        if bool(mask.any()):
            if observation is None or observation.shape != (context.shape[0], self.input_size):
                raise ValueError("observation must have shape [B,input_size]")
            observation = torch.where(mask[:, None], observation, torch.zeros_like(observation))
            if not bool(torch.isfinite(observation).all()):
                raise ValueError("nonfinite observed feature")
            proposed = torch.tanh(self.input_layer(observation)+self.recurrent_layer(context))
            context = torch.where(mask[:, None], proposed, context)
        latent = memory.mean(-1)
        if self.readout_mode == "analog":
            latent = latent+.25*context
        new_state = {"memory": memory, "context": context, "time": state["time"]+dt}
        if not all(bool(torch.isfinite(v).all()) for v in new_state.values()):
            raise FloatingPointError("nonfinite continuous-time state")
        return new_state, {"latent": latent, "spikes": torch.zeros_like(latent),
                           "actual_counts": torch.zeros_like(latent, dtype=torch.int64), "spike_times": []}

    def forward(self, x, dt, event_mask=None, generator=None, record_spikes=False):
        if x.ndim != 3 or x.shape[-1] != self.input_size or dt.shape != x.shape[:2]:
            raise ValueError("expected x[B,T,F] and dt[B,T]")
        if bool((dt[:, 0] != 0).any()):
            raise ValueError("initial observation must have dt=0")
        masks = torch.ones(x.shape[:2], device=x.device, dtype=torch.bool) if event_mask is None else event_mask
        state, outputs = self.initial_state(x.shape[0], x.device, x.dtype), []
        for index in range(x.shape[1]):
            state, output = self.step(state, x[:, index], dt[:, index], masks[:, index])
            outputs.append(output)
        return {"latent": torch.stack([o["latent"] for o in outputs], 1),
                "spikes": torch.stack([o["spikes"] for o in outputs], 1),
                "actual_counts": torch.stack([o["actual_counts"] for o in outputs], 1),
                "final_state": state, "spike_times": []}

    def metadata(self):
        scalars = self.hidden_size*(self.modes+1)+1
        return {"model": "exact_time_basis_ctrnn", "encoder_parameters": sum(p.numel() for p in self.parameters()),
                "modes": self.modes, "persistent_state_scalars": scalars,
                "persistent_state_bytes_float32": 4*scalars,
                "shared_constant_buffer_bytes": self.taus.numel()*self.taus.element_size(),
                "readout_mode": self.readout_mode, "forward": "exact held-context exponential relaxation",
                "backward": "autograd of exact interval formula", "fixed_control_semigroup_exact": True,
                "cfc_reproduction": False, "internal_spikes": False,
                "state_excludes": "weights, task state, temporaries, autograd history and process overhead"}


def make_encoder(variant, input_size=22, hidden_size=8, **kwargs):
    if variant in ("ctrnn", "ctrnn_matched"):
        kwargs.setdefault("modes", 20 if variant == "ctrnn_matched" else 1)
        return TimeBasisEncoder(input_size, hidden_size, **kwargs)
    return EventSpikingEncoder(variant, input_size, hidden_size, **kwargs)
