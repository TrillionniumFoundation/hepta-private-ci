"""Batch the input-only operators before sequential finite-population transport.

Every window still has its own physical intervals, density and moving boundary.
Only independent matrix operations are scheduled together. The finite generator,
remap, signed-content law and FP64 transport match hcsn_scale's serial reference.
This executor returns window features, not a persistent backend state. Preparing
operators increases working memory and retains an AD tape proportional to B*T;
there is no fixed-memory training claim and no cross-call operator cache.
"""

from dataclasses import dataclass

import torch

from qualification.hcsn_scale.model import SequenceModel


@dataclass(frozen=True)
class WindowOperators:
    boundaries: torch.Tensor
    marks: torch.Tensor
    actions: torch.Tensor
    first_hits: torch.Tensor
    values: torch.Tensor
    durations: torch.Tensor


class PreparedSequenceModel(SequenceModel):
    """An opt-in executor with identical parameters and a distinct identity."""

    max_prepared_events = 2048
    max_operator_entries = 2_000_000
    representation_batch_size = 32

    def _validate_windows(self, windows, intervals):
        parameter = next(self.parameters())
        if (windows.ndim != 3 or windows.shape[2] != self.config.input_size
                or not 1 <= windows.shape[0] <= 256 or not 1 <= windows.shape[1] <= 256
                or windows.numel() // self.config.input_size > self.max_prepared_events
                or windows.dtype != parameter.dtype or windows.device != parameter.device
                or not bool(torch.isfinite(windows).all())):
            raise ValueError("bounded matching [batch,time,input] windows required")
        duration = torch.as_tensor(intervals, dtype=torch.float64, device=windows.device).detach()
        micros = (duration * 1_000_000).round()
        if (duration.shape != windows.shape[:2] or not bool(torch.isfinite(duration).all())
                or bool((micros < 1).any()) or bool((micros > 10**9).any())
                or not bool(torch.allclose(micros, duration * 1_000_000, rtol=0, atol=1e-6))):
            raise ValueError("one positive integer-microsecond interval per event required")
        return duration

    def prepare_windows(self, windows, intervals):
        """Materialize input-dependent operators; reuse after weight edits is invalid."""
        if self.config.kind != "hcsn":
            raise ValueError("operator preparation is specific to HCSN")
        duration = self._validate_windows(windows, intervals)
        batch, steps, _ = windows.shape
        c, encoder = self.encoder.config, self.encoder
        size = c.bins + c.stages + 1
        entries = batch * steps * ((size + 2)**2 + (c.bins + 2)**2)
        if entries > self.max_operator_entries:
            raise ValueError("prepared operator memory capacity exceeded")
        flat = windows.reshape(-1, self.config.input_size)
        work = flat.to(dtype=encoder.edges.dtype)
        boundary = self.config.boundary_scale * self.boundary(flat).tanh().squeeze(-1)
        drift = (c.base_drift + c.drift_scale * encoder.drive(flat).squeeze(-1).tanh()).to(work)
        boundary = boundary.to(work)
        mark = encoder.writer(flat).tanh().to(work)
        generator, event, spatial = encoder._generator(drift)
        active = torch.cat((work.new_ones(c.bins), work.new_zeros(c.stages + 1)))
        weights = torch.stack((event, active.expand_as(event)), -1)
        augmented = torch.cat((torch.cat((generator, weights), -1),
                               work.new_zeros(len(flat), 2, size + 2)), -2)
        elapsed = duration.reshape(-1, 1, 1)
        action = torch.matrix_exp(augmented * elapsed)
        first = torch.matrix_exp(spatial * elapsed)[:, :c.bins, c.bins]
        reward = torch.cat((c.gain * (boundary[:, None] + encoder.centers) - c.maintenance,
                            work.new_zeros(len(flat), c.stages + 1)), -1) - c.spike_cost * event
        value = torch.linalg.solve(
            c.discount * torch.eye(size, dtype=work.dtype, device=work.device) - generator,
            reward[..., None]).squeeze(-1)
        return WindowOperators(boundary.reshape(batch, steps), mark.reshape(batch, steps, -1),
                               action.reshape(batch, steps, size + 2, size + 2),
                               first.reshape(batch, steps, c.bins),
                               value.reshape(batch, steps, size), duration)

    def propagate_prepared(self, operators):
        """Consume prepared operators once in time order, preserving every interval."""
        c, encoder = self.encoder.config, self.encoder
        boundaries, actions = operators.boundaries, operators.actions
        batch, steps = boundaries.shape
        initial = encoder.initial_state(batch)
        density, previous = initial.density, initial.boundary
        outputs = []
        old_lo, old_hi = encoder.edges[:-1], encoder.edges[1:]
        widths = old_hi - old_lo
        for t in range(steps):
            boundary = boundaries[:, t]
            shift = boundary - previous
            new_lo, new_hi = shift[:, None] + old_lo, shift[:, None] + old_hi
            overlap = (torch.minimum(old_hi[None, :, None], new_hi[:, None, :])
                       - torch.maximum(old_lo[None, :, None], new_lo[:, None, :])).clamp_min(0)
            overlap = overlap / widths[None, :, None]
            lower = ((shift[:, None] - old_lo) / widths).clamp(0, 1)
            upper = ((old_hi - shift[:, None] - c.extent) / widths).clamp(0, 1)
            active = density[..., :c.bins]
            jump = (active * lower[:, None]).sum(-1)
            escaped = (active * upper[:, None]).sum(-1)
            retained = active @ overlap
            last = torch.zeros_like(retained)
            last[..., -1] = 1
            retained = retained + escaped[..., None] * last
            phase = density[..., c.bins:-1]
            first = torch.zeros_like(phase)
            first[..., 0] = 1
            remapped = torch.cat((retained, phase + jump[..., None] * first,
                                  density[..., -1:]), -1)
            content = ((1 - c.write_fraction) * remapped[:, 1:, :c.bins]
                       + c.write_fraction * operators.marks[:, t, :, None] * remapped[:, :1, :c.bins])
            written = torch.cat((remapped[:, :1],
                                 torch.cat((content, remapped[:, 1:, c.bins:]), -1)), 1)
            size = density.shape[-1]
            density = written @ actions[:, t, :size, :size]
            increments = written @ actions[:, t, :size, size:]
            hits = jump + increments[..., 0]
            risk = jump[:, 0] + (retained[:, 0] * operators.first_hits[:, t]).sum(-1)
            p = density[:, 0]
            margin = (p[:, :c.bins] * encoder.centers).sum(-1) / c.extent
            call = (p * operators.values[:, t]).sum(-1)
            features = torch.cat((hits, torch.stack((risk, margin,
                                  increments[:, 0, 1] / operators.durations[:, t], call), -1)), -1)
            # The serial FP64 transport checks remain at every observation edge.
            if (not bool(torch.isfinite(density).all()) or bool((p < -1e-10).any())
                    or bool((density[:, 1:].abs() > p[:, None] + 1e-10).any())
                    or not bool(torch.allclose(p.sum(-1), torch.ones_like(p.sum(-1)), rtol=0, atol=1e-10))
                    or bool((density[..., -1].abs() > 1e-10).any())
                    or not bool(torch.isfinite(features).all())):
                raise FloatingPointError("prepared population invariant failed")
            outputs.append(features.to(encoder.drive.weight))
            previous = boundary
        return torch.stack(outputs, 1)

    def encode_batch(self, windows, intervals):
        if self.config.kind == "hcsn":
            return self.propagate_prepared(self.prepare_windows(windows, intervals))
        duration = self._validate_windows(windows, intervals)
        timing = torch.log1p(duration / self.config.clock_scale_seconds).to(windows)
        state, outputs = None, []
        for t in range(windows.shape[1]):
            state = self.encoder(torch.cat((windows[:, t], timing[:, t, None]), -1), state)
            outputs.append(state)
        return torch.stack(outputs, 1)

    def encode_one(self, sequence, intervals):
        return self.encode_batch(sequence.unsqueeze(0),
                                 torch.as_tensor(intervals, dtype=torch.float64).unsqueeze(0))[0]

    def next_sensor_loss(self, windows, intervals):
        duration = self._validate_windows(windows, intervals)
        if windows.shape[1] < 2:
            raise ValueError("next-sensor learning needs at least two observations")
        features = self.encode_batch(windows[:, :-1], duration[:, :-1])
        loss = (self.predictor(features) - windows[:, 1:]).square().mean()
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError("nonfinite self-supervised loss")
        return loss

    @torch.no_grad()
    def representations(self, windows, intervals):
        duration = torch.as_tensor(intervals, dtype=torch.float64, device=windows.device)
        if (windows.ndim != 3 or duration.shape != windows.shape[:2]
                or not len(windows) or not 2 <= windows.shape[1] <= 256):
            raise ValueError("nonempty windows with matching intervals required")
        embeddings, losses = [], []
        chunk = min(self.representation_batch_size, self.max_prepared_events // windows.shape[1])
        if chunk < 1 or windows.shape[1] < 2:
            raise ValueError("unsupported window length")
        for start in range(0, len(windows), chunk):
            inputs = windows[start:start + chunk]
            features = self.encode_batch(inputs, duration[start:start + chunk])
            embeddings.append(torch.cat((features[:, -1], features.mean(1)), -1))
            losses.append((self.predictor(features[:, :-1]) - inputs[:, 1:]).square().mean((1, 2)))
        result, loss = torch.cat(embeddings), torch.cat(losses).mean()
        if not bool(torch.isfinite(result).all()) or not bool(torch.isfinite(loss)):
            raise FloatingPointError("nonfinite frozen encoder representation")
        return result, float(loss)

    def identity(self):
        result = super().identity()
        result["executor"] = {"schema": "hcsn-prepared-window-v1",
                              "max_prepared_events": self.max_prepared_events,
                              "max_operator_entries": self.max_operator_entries,
                              "representation_batch_size": self.representation_batch_size,
                              "streaming_state_returned": False,
                              "historical_qualification_transferred": False}
        return result
