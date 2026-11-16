"""FP32 belief-state observer and measured execution costs for the pilot."""

import math
import platform
import time

import numpy as np


def make_model(arrays, arm, channel, seed, device="cpu", mass_tolerance=5e-5):
    import torch
    from torch import nn

    torch.manual_seed(seed)
    state_count = arrays[arm + "__matrix"].shape[-1]

    class BeliefObserver(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = nn.Sequential(nn.Linear(3, 32), nn.Tanh(), nn.Linear(32, state_count))
            self.gate = nn.Linear(6, 1)
            self.readout = nn.Linear(state_count, 1)
            for kind in ("matrix", "first_step", "features"):
                self.register_buffer(kind, torch.from_numpy(arrays[arm + "__" + kind].copy()))
            self.channel = channel
            self.mass_tolerance = mass_tolerance
            if sum(p.numel() for p in self.parameters()) != 34 * state_count + 136:
                raise RuntimeError("The registered learned architecture must contain 34*S+136 parameters")

        def forward(self, observations, dt_indices, return_trace=False):
            if observations.ndim != 3 or observations.shape[-1] != 3 or dt_indices.shape != observations.shape[:2]:
                raise ValueError("Expected observations [batch,time,3] and dt indices [batch,time]")
            if observations.dtype != torch.float32 or dt_indices.dtype != torch.int64:
                raise ValueError("Pilot execution is FP32 with integer dt indices")
            cohort = (dt_indices[:, 0] >= 2).to(torch.int64)
            posterior = None
            defects, negatives, evidence_values, trajectory, profiles = [], [], [], [], []
            for step in range(observations.shape[1]):
                dt = dt_indices[:, step]
                if posterior is None:
                    pred = self.first_step[cohort, dt]
                    incoming_defect = pred.new_zeros(())
                else:
                    incoming_defect = (posterior.sum(-1) - 1).abs().max()
                    defects.append(incoming_defect)
                    pred = torch.bmm(posterior.unsqueeze(1), self.matrix[cohort, dt]).squeeze(1)
                predicted_defect = (pred.sum(-1) - 1).abs().max()
                defects.append(predicted_defect)
                negatives.append((-pred).clamp_min(0).max())
                raw = torch.bmm(pred.unsqueeze(1), self.features[cohort, dt]).squeeze(1)
                transformed = torch.stack((raw[:, 0] / (1 + raw[:, 0]), raw[:, 1] / (1 + raw[:, 1]), raw[:, 2]), -1)
                if self.channel == "dual":
                    channels = transformed
                else:
                    index = {"margin": 0, "call": 1, "risk": 2}[self.channel]
                    z = transformed[:, index]
                    channels = torch.stack((z, z.square(), z.pow(3)), -1)
                obs = observations[:, step]
                gate = torch.sigmoid(self.gate(torch.cat((obs, channels), -1)))
                likelihood = torch.exp(gate * torch.tanh(self.encoder(obs)))
                weighted = pred * likelihood
                evidence = weighted.sum(-1, keepdim=True)
                posterior = weighted / evidence
                posterior_defect = (posterior.sum(-1) - 1).abs().max()
                defects.append(posterior_defect)
                profiles.append(torch.stack((incoming_defect, predicted_defect, posterior_defect)))
                evidence_values.append(evidence)
                if return_trace:
                    trajectory.append(dict(pred=pred, posterior=posterior, channels=channels, cohort=cohort, gate=gate))
            mass_defect = torch.stack(defects).max()
            negative_mass = torch.stack(negatives).max()
            ev = torch.cat(evidence_values, 0)
            audit = torch.stack((mass_defect, negative_mass, ev.min(), ev.max()))
            combined = torch.cat((audit, torch.stack(profiles).flatten())).detach().cpu().tolist()
            values = combined[:4]
            if (not all(math.isfinite(v) for v in values) or values[0] > self.mass_tolerance
                    or values[1] > self.mass_tolerance or values[2] <= 0):
                raise FloatingPointError("Unconditioned state/evidence invariant failed: " + str(values))
            diagnostics = dict(maximum_unconditioned_and_posterior_mass_defect=values[0],
                               maximum_negative_predicted_mass=values[1], minimum_evidence=values[2],
                               maximum_evidence=values[3], normalizations="Bayesian observation evidence only",
                               mass_defect_columns=["incoming_belief", "unconditioned_prediction", "observation_posterior"],
                               mass_defects_by_time_step=[combined[i:i + 3] for i in range(4, len(combined), 3)])
            output = self.readout(posterior)
            return (output, diagnostics, trajectory) if return_trace else (output, diagnostics)

    return BeliefObserver().to(device)


class GradientAudit:
    """Observed support is separate from static, nominal trainability."""

    def __init__(self, model):
        import torch
        self.masks = {name: torch.zeros_like(parameter, dtype=torch.bool) for name, parameter in model.named_parameters()}
        self.steps = {name: torch.zeros((), device=parameter.device, dtype=torch.int64) for name, parameter in model.named_parameters()}
        self.observations = {name: torch.zeros((), device=parameter.device, dtype=torch.int64) for name, parameter in model.named_parameters()}
        self.updates = 0

    def observe(self, model):
        import torch
        finite = []
        for name, parameter in model.named_parameters():
            if parameter.grad is None:
                continue
            nonzero = parameter.grad != 0
            self.masks[name] |= nonzero
            self.steps[name] += nonzero.any().to(torch.int64)
            self.observations[name] += nonzero.sum()
            finite.append(torch.isfinite(parameter.grad).all())
        if not finite or not bool(torch.stack(finite).all().item()):
            raise FloatingPointError("Missing or nonfinite training gradients")
        self.updates += 1

    def report(self):
        return dict(observed_updates=self.updates,
                    parameter_tensors={name: dict(static_elements=mask.numel(),
                                                  ever_nonzero_gradient_elements=int(mask.sum().item()),
                                                  steps_with_any_nonzero_gradient=int(self.steps[name].item()),
                                                  cumulative_nonzero_element_observations=int(self.observations[name].item()))
                                       for name, mask in self.masks.items()},
                    total_ever_nonzero_gradient_elements=sum(int(mask.sum().item()) for mask in self.masks.values()))


def memory_report(model, optimizer=None, batch_size=64):
    def parameters(module):
        values = list(module.parameters())
        return dict(parameters=sum(v.numel() for v in values),
                    trainable_parameters=sum(v.numel() for v in values if v.requires_grad),
                    parameter_bytes=sum(v.numel() * v.element_size() for v in values))
    result = dict(encoder=parameters(model.encoder), core_gate=parameters(model.gate), decoder=parameters(model.readout),
                  total=parameters(model), resident_buffer_bytes=sum(v.numel() * v.element_size() for v in model.buffers()),
                  buffers={name: dict(shape=list(v.shape), bytes=v.numel() * v.element_size()) for name, v in model.named_buffers()},
                  dynamic_belief_state_bytes=batch_size * model.matrix.shape[-1] * model.matrix.element_size(),
                  dynamic_state_scope="One persistent belief vector per example; temporary/autograd buffers excluded",
                  dynamic_state_batch_size=batch_size)
    if optimizer is not None:
        result["optimizer_state_tensor_bytes"] = sum(v.numel() * v.element_size()
            for state in optimizer.state.values() for v in state.values() if hasattr(v, "numel"))
    return result


def synchronize(device):
    if str(device).startswith("cuda"):
        import torch
        torch.cuda.synchronize(device)


class DeviceEnergy:
    """NVML device interval only. It never supplies full physical energy."""

    def __init__(self, device):
        self.start = None
        self.reason = "CPU or unavailable device energy counter"
        self.handle = None
        self.uuid = None
        if str(device).startswith("cuda"):
            try:
                import torch
                import pynvml
                pynvml.nvmlInit()
                self.uuid = str(torch.cuda.get_device_properties(device).uuid)
                self.handle = pynvml.nvmlDeviceGetHandleByUUID(self.uuid)
                self.start = pynvml.nvmlDeviceGetTotalEnergyConsumption(self.handle)
                self.reason = None
            except Exception as error:
                self.reason = type(error).__name__ + ": " + str(error)

    def finish(self):
        joules = None
        if self.start is not None:
            try:
                import pynvml
                value = pynvml.nvmlDeviceGetTotalEnergyConsumption(self.handle)
                if value < self.start:
                    raise ValueError("NVML counter reset")
                joules = (value - self.start) / 1000
            except Exception as error:
                self.reason = type(error).__name__ + ": " + str(error)
        return dict(device_interval_joules=joules, device_uuid=self.uuid, unavailable_reason=self.reason,
                    device_interval_scope="NVML cumulative GPU device counter; includes other processes if present",
                    full_physical_energy_joules=None, provider_charges=None)


def environment(device):
    import torch
    result = dict(python=platform.python_version(), numpy=np.__version__, torch=torch.__version__,
                  cuda_build=torch.version.cuda, device=str(device), deterministic_algorithms=torch.are_deterministic_algorithms_enabled(),
                  cpu_threads=torch.get_num_threads(), physical_energy_joules=None)
    if str(device).startswith("cuda"):
        p = torch.cuda.get_device_properties(device)
        result["gpu"] = dict(name=p.name, total_memory=p.total_memory, uuid=str(getattr(p, "uuid", "unknown")),
                             compute_capability=[p.major, p.minor])
    return result


def benchmark(model, x, dt, plan, device):
    import torch
    durations = []
    model.eval()
    with torch.inference_mode():
        for _ in range(plan["latency_warmup"]):
            model(x[:1].to(device), dt[:1].to(device))
            synchronize(device)
        for _ in range(plan["latency_repeats"]):
            synchronize(device)
            start = time.perf_counter()
            output, _ = model(x[:1].to(device), dt[:1].to(device))
            output.cpu()
            synchronize(device)
            durations.append(time.perf_counter() - start)
        synchronize(device)
        start = time.perf_counter()
        for _ in range(plan["throughput_repeats"]):
            output, _ = model(x[:plan["throughput_batch"]].to(device), dt[:plan["throughput_batch"]].to(device))
            output.cpu()
        synchronize(device)
        wall = time.perf_counter() - start
    return dict(latency_seconds={name: float(value) for name, value in zip(("p50", "p95", "p99"), np.quantile(durations, [.5, .95, .99]))},
                latency_repeats=len(durations), latency_warmup=plan["latency_warmup"],
                throughput_examples_per_second=plan["throughput_batch"] * plan["throughput_repeats"] / wall,
                throughput_wall_seconds=wall, throughput_batch=plan["throughput_batch"],
                throughput_repeats=plan["throughput_repeats"],
                scope="Complete 64-step observer and readout, input/output transfers, mass checks and device synchronization; data generation/checkpoint load excluded")
