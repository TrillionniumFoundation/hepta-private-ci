"""Detached mechanism measurements; none enter the model's forward calculation."""

import math
import torch
from torch import nn


class CommunicationObserver:
    def __init__(self, neurons):
        self.neurons, self.phase, self.statistics = neurons, "setup", {}

    def attach(self, model):
        model.observer = self
        model.recurrent.weight.register_hook(self.gradient)
        model.register_forward_hook(self.output)

    def group(self):
        if self.phase not in self.statistics:
            self.statistics[self.phase] = {
                "observations_per_unit": 0, "frames": 0, "control_observations": 0,
                "raw_sum": torch.zeros(3, self.neurons, dtype=torch.float64),
                "raw_square": torch.zeros(3, self.neurons, dtype=torch.float64),
                "delivered_sum": torch.zeros(3, self.neurons, dtype=torch.float64),
                "delivered_square": torch.zeros(3, self.neurons, dtype=torch.float64),
                "contribution_sum": torch.zeros(3, self.neurons, dtype=torch.float64),
                "contribution_square": torch.zeros(3, self.neurons, dtype=torch.float64),
                "drive_saturated": 0, "mark_saturated": 0, "drive_due_saturated": 0,
                "drive_square_sum": 0., "mark_square_sum": 0.,
                "preclip_recurrent_gradient_norm_by_update": [], "maximum_complete_state_tensor_bytes": 0,
                "maximum_control_state_tensor_bytes": 0}
        return self.statistics[self.phase]

    @torch.no_grad()
    def __call__(self, model, raw_frame, control_frame, raw_message, transformed_message, step):
        group, n = self.group(), self.neurons
        message = transformed_message.to(raw_frame)
        mask = raw_frame.new_tensor((1., 1., 1.) if model.config.message_mode == "full" else
                                   (1., 0., 0.) if model.config.message_mode == "boundary" else (0., 1., 1.))
        structural_sender = model.synaptic_mask.reshape(n, 3, n).abs().sum(0) > 0
        delivered = message*mask[None, :, None]*structural_sender[None].to(message)
        weight = model.recurrent.weight*model.synaptic_mask
        contribution = torch.stack([nn.functional.linear(delivered[:, k], weight[:, k*n:(k+1)*n])
                                    for k in range(3)], 1)
        rec = nn.functional.linear(delivered.flatten(1), weight)
        drive = nn.functional.pad(nn.functional.linear(control_frame, model.input_drive.weight,
                                                       model.input_drive.bias), (0, n//2))+rec
        mark = nn.functional.pad(nn.functional.linear(raw_frame, model.input_mark.weight,
                                                      model.input_mark.bias), (0, n//2))+rec
        for prefix, value in (("raw", raw_message), ("delivered", delivered), ("contribution", contribution)):
            value = value.detach().double().cpu()
            group[prefix+"_sum"] += value.sum(0)
            group[prefix+"_square"] += value.square().sum(0)
        count = raw_frame.shape[0]
        group["observations_per_unit"] += count
        group["frames"] += 1
        group["drive_saturated"] += int((drive.tanh().abs() >= .95).sum())
        group["mark_saturated"] += int((mark.tanh().abs() >= .95).sum())
        group["drive_square_sum"] += float(drive.double().square().sum())
        group["mark_square_sum"] += float(mark.double().square().sum())
        if step % model.config.slow_every == 0:
            group["control_observations"] += count*n
            group["drive_due_saturated"] += int((drive.tanh().abs() >= .95).sum())

    def gradient(self, gradient):
        n = self.neurons
        values = [float(gradient[:, k*n:(k+1)*n].detach().double().norm()) for k in range(3)]
        self.group()["preclip_recurrent_gradient_norm_by_update"].append(values)
        return gradient

    def output(self, model, inputs, output):
        if not isinstance(output, tuple) or len(output) != 3:
            return
        state = output[2]
        physical = sum(getattr(state, key).numel()*getattr(state, key).element_size()
                       for key in ("density", "boundary", "drift", "cost", "message"))
        control = sum(t.numel()*t.element_size() for t in (state.control.pending, state.control.held))
        group = self.group()
        group["maximum_complete_state_tensor_bytes"] = max(group["maximum_complete_state_tensor_bytes"], physical+control)
        group["maximum_control_state_tensor_bytes"] = max(group["maximum_control_state_tensor_bytes"], control)

    def export(self):
        result = {}
        for phase, group in self.statistics.items():
            count = group["observations_per_unit"]
            out = {k:v for k,v in group.items() if not isinstance(v, torch.Tensor)}
            for prefix in ("raw", "delivered", "contribution"):
                mean = group[prefix+"_sum"]/max(count, 1)
                square = group[prefix+"_square"]/max(count, 1)
                out[prefix+"_channel_mean"] = mean.mean(-1).tolist()
                out[prefix+"_channel_rms"] = square.mean(-1).sqrt().tolist()
                out[prefix+"_channel_temporal_dc_rms"] = mean.square().mean(-1).sqrt().tolist()
                out[prefix+"_mean_by_unit"] = mean.tolist()
            total = max(count*self.neurons, 1)
            out["drive_saturation_fraction"] = group["drive_saturated"]/total
            out["raw_mark_saturation_fraction"] = group["mark_saturated"]/total
            out["drive_due_saturation_fraction"] = group["drive_due_saturated"]/max(group["control_observations"], 1)
            out["drive_rms"] = math.sqrt(group["drive_square_sum"]/total)
            out["raw_mark_rms"] = math.sqrt(group["mark_square_sum"]/total)
            result[phase] = out
        return {"channels": ["boundary", "unsigned", "signed"], "phases": result,
            "saturation_rule": "abs(tanh(preactivation)) >= .95",
            "gradient_scope": "Recurrent parameter gradient before global clipping, one row per leaf-hook call; masked columns retain zero gradients.",
            "scope": "Detached observations only. Training phases combine changing weights; evaluation phases use a frozen loaded checkpoint. No statistic feeds normalization or model control."}
