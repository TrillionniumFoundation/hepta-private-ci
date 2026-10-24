"""Matched supervised/surrogate pretraining; true-output NDU is a later stage."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import math
import time

import torch

from ..v6.data import Observation, Target
from ..v6.neural import ACTIONS, PROFILES, parameter_hash
from .data import make_batch
from .model import SlotPortfolio
from .snapshot import Snapshot


@dataclass(frozen=True)
class TrainConfig:
    seed: int = 17
    steps: int = 2000
    batch_size: int = 64
    scenarios: int = 2
    learning_rate: float = .001
    risk_aversion: float = 2.
    noise_scale: float = .15
    horizon: int = 4
    threads: int = 2


def train_profiles(corpus, config=None, progress=None):
    config = config or TrainConfig()
    if (config.steps < 1 or config.batch_size < 1 or config.scenarios < 2
            or config.horizon != 4 or config.threads not in {1, 2}
            or config.risk_aversion <= 0 or config.learning_rate <= 0):
        raise ValueError("Invalid registered pretraining configuration")
    torch.set_num_threads(config.threads)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        original = SlotPortfolio(noise_scale=config.noise_scale)
    initial_sha = parameter_hash(original)
    snapshots, reports = {}, {}
    for profile in PROFILES:
        model = deepcopy(original).train()
        optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
        rng = torch.Generator().manual_seed(config.seed + 104729)
        schedule, gradients, histories = hashlib.sha256(), {}, []
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        for step in range(config.steps):
            batch_seed = config.seed * 1000003 + step
            batch = make_batch(corpus, "train", config.batch_size, batch_seed)
            observation = Observation(*(value.repeat_interleave(config.scenarios, 0)
                                        for value in (batch.observation.pixels, batch.observation.mask,
                                                      batch.observation.text_tokens)))
            target = Target(*(value.repeat_interleave(config.scenarios, 0)
                              for value in (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
            noise = torch.randn((config.batch_size * config.scenarios, 96), generator=rng)
            state = model.encode(observation, noise)
            actions = torch.randint(4, (step % (config.horizon + 1),), generator=rng).tolist()
            for action in actions:
                state = model.step(state, ACTIONS[action])
            terms = model.loss(model.decode(state, teacher_tokens=target.text_tokens), target)
            losses = terms["joint"].reshape(config.batch_size, config.scenarios)
            objective = (losses.mean() if profile == "supervised" else
                         ((torch.logsumexp(config.risk_aversion * losses, 1)
                           - math.log(config.scenarios)) / config.risk_aversion).mean())
            if not torch.isfinite(objective):
                raise FloatingPointError(f"Nonfinite objective at {profile}:{step}")
            optimizer.zero_grad(set_to_none=True)
            objective.backward()
            for name, parameter in model.named_parameters():
                if parameter.grad is not None:
                    module = name.split(".")[0]
                    gradients[module] = max(gradients.get(module, 0), float(parameter.grad.abs().sum()))
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            schedule.update(f"{batch_seed}:{actions}\n".encode())
            record = {"step": step + 1, "objective": float(objective.detach()), "horizon": len(actions),
                      **{key: float(value.detach().mean()) for key, value in terms.items()}}
            histories.append(record)
            if progress and (step == 0 or (step + 1) % 100 == 0):
                progress(profile, record)
        metadata = {"profile": profile, "training_config": asdict(config),
                    "source_manifest_sha256": corpus.manifest["manifest_sha256"],
                    "initial_parameter_sha256": initial_sha}
        snapshots[profile] = Snapshot(model, metadata)
        reports[profile] = {
            **metadata, "final_snapshot_sha256": snapshots[profile].fingerprint,
            "final_parameter_sha256": parameter_hash(model), "history": histories,
            "optimizer_updates": config.steps, "gradient_abs_sum_max": gradients,
            "schedule_sha256": schedule.hexdigest(),
            "wall_ns": time.perf_counter_ns() - start_wall,
            "cpu_ns": time.process_time_ns() - start_cpu,
            "parameter_count": sum(p.numel() for p in model.parameters()),
            "reward": "-(pixel_bce + 0.5*teacher_forced_text_ce + 0.3*semantic_digit_ce)",
            "actual_emitted_output_ndu_objective": False,
            "role": "supervised_or_conditional_latent_noise_surrogate_pretraining",
        }
    return snapshots, reports
