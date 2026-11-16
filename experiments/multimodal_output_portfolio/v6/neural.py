"""Small real neural text/image generator and a bounded NDU training profile.

This is a CPU research mechanism for the constructed MNIST-pair domain. The
terminal entropic profile is an explicit special case, not the repository's
general endogenous-preference FBSDE solver. Model parameters are fixed during
inference; controls change learned latent states, including shared semantics.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import io
import math
from pathlib import Path
import time

import torch
from torch import nn
from torch.nn import functional as F

from .data import BOS, CAPTION_LENGTH, Observation, Target, VOCAB, make_batch


ACTIONS = ("refine_semantic", "refine_image", "refine_text", "couple")
PROFILES = ("supervised", "terminal_entropic_ndu")
LEGACY_ARCHITECTURE = "legacy"
CONDITIONED_ARCHITECTURE = "public-command-film-layernorm-v1"
CONDITIONED_SCHEMA = "hepta.ndu-v6.conditioned-snapshot.v2"


@dataclass(frozen=True)
class NeuralState:
    h: torch.Tensor
    image: torch.Tensor
    text: torch.Tensor
    context: torch.Tensor
    snapshot_digest: str = ""


@dataclass(frozen=True)
class NeuralOutput:
    image_logits: torch.Tensor
    text_logits: torch.Tensor
    token_ids: torch.Tensor
    digit_logits: torch.Tensor


@dataclass(frozen=True)
class TrainConfig:
    seed: int = 17
    steps: int = 300
    batch_size: int = 64
    hidden: int = 96
    learning_rate: float = .001
    scenarios: int = 2
    risk_aversion: float = 2.
    noise_scale: float = .15
    refinement_steps: int = 3
    threads: int = 2
    architecture: str = LEGACY_ARCHITECTURE


def parameter_hash(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str(value.dtype).encode())
        digest.update(str(tuple(value.shape)).encode())
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def checkpoint_file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_checkpoint(path, expected_file_sha256=None):
    """Verify caller-pinned bytes before safely reading a checkpoint record."""
    raw = Path(path).read_bytes()
    if (expected_file_sha256 is not None
            and hashlib.sha256(raw).hexdigest() != expected_file_sha256):
        raise ValueError("Checkpoint file SHA-256 mismatch")
    return torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)


def model_from_config(config):
    config = dict(config)
    architecture = config.pop("architecture", LEGACY_ARCHITECTURE)
    if architecture == LEGACY_ARCHITECTURE:
        return NeuralPortfolio(**config)
    if architecture == CONDITIONED_ARCHITECTURE:
        from .conditioned import ConditionedPortfolio
        return ConditionedPortfolio(**config)
    raise ValueError(f"Unsupported neural architecture: {architecture}")


def snapshot_from_model(model, metadata=None):
    architecture = model.config.get("architecture", LEGACY_ARCHITECTURE)
    if architecture == LEGACY_ARCHITECTURE:
        return NeuralSnapshot(model, metadata)
    if architecture == CONDITIONED_ARCHITECTURE:
        from .conditioned import ConditionedSnapshot
        return ConditionedSnapshot(model, metadata)
    raise ValueError(f"Unsupported neural architecture: {architecture}")


def snapshot_from_record(record):
    if record.get("schema") == "hepta.ndu-v6.neural-snapshot.v1":
        return NeuralSnapshot._from_record(record)
    if record.get("schema") == CONDITIONED_SCHEMA:
        from .conditioned import ConditionedSnapshot
        return ConditionedSnapshot._from_record(record)
    raise ValueError("Unsupported neural snapshot schema")


def load_snapshot(path, *, expected_file_sha256=None):
    return snapshot_from_record(read_checkpoint(path, expected_file_sha256))


class NeuralPortfolio(nn.Module):
    """Shared encoder, recurrent controlled cells, autoregressive/pixel heads."""

    def __init__(self, hidden=96, noise_scale=.15):
        super().__init__()
        if hidden < 16 or not 0 <= noise_scale <= 1:
            raise ValueError("Invalid bounded model configuration")
        self.config = {"hidden": hidden, "noise_scale": noise_scale}
        self.hidden = hidden
        self.noise_scale = noise_scale
        self.token_embedding = nn.Embedding(len(VOCAB), 24)
        self.text_encoder = nn.GRU(24, hidden // 2, batch_first=True)
        self.pixel_encoder = nn.Sequential(
            nn.Conv2d(2, 12, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(12, 24, 3, stride=2, padding=1), nn.ReLU(),
            nn.Flatten(), nn.Linear(24 * 7 * 14, hidden), nn.Tanh(),
        )
        self.fuse = nn.Sequential(nn.Linear(hidden + hidden // 2, hidden), nn.Tanh())
        self.initial_image = nn.Linear(hidden, hidden)
        self.initial_text = nn.Linear(hidden, hidden)
        self.semantic_cell = nn.Sequential(nn.Linear(4 * hidden, hidden), nn.Tanh())
        self.image_cell = nn.Sequential(nn.Linear(3 * hidden, hidden), nn.Tanh())
        self.text_cell = nn.Sequential(nn.Linear(3 * hidden, hidden), nn.Tanh())
        self.coupling_cell = nn.Sequential(nn.Linear(4 * hidden, 3 * hidden), nn.Tanh())
        self.pixel_decoder = nn.Sequential(
            nn.Linear(2 * hidden, 256), nn.ReLU(), nn.Linear(256, 28 * 56),
        )
        self.text_initial = nn.Linear(2 * hidden, hidden)
        self.text_decoder = nn.GRU(24, hidden, batch_first=True)
        self.text_projection = nn.Linear(hidden, len(VOCAB))
        self.digit_head = nn.Linear(hidden, 20)

    def encode(self, observation, noise=None):
        if not isinstance(observation, Observation):
            raise TypeError("Inference encoder accepts Observation only")
        if observation.pixels.ndim != 4 or observation.pixels.shape[1:] != (1, 28, 56):
            raise ValueError("Expected Bx1x28x56 public pixels")
        if observation.mask.shape != observation.pixels.shape:
            raise ValueError("Pixel/missingness shape mismatch")
        visual = self.pixel_encoder(torch.cat((observation.pixels, observation.mask), dim=1))
        _, language = self.text_encoder(self.token_embedding(observation.text_tokens))
        context = self.fuse(torch.cat((visual, language[-1]), dim=1))
        h = context if noise is None else context + self.noise_scale * noise
        if h.shape != context.shape:
            raise ValueError("Initial latent noise shape mismatch")
        return NeuralState(h, torch.tanh(self.initial_image(h)),
                           torch.tanh(self.initial_text(h)), context)

    def step(self, state, action):
        """Return a new state; modality-only actions preserve shared h exactly."""
        if action not in ACTIONS:
            raise ValueError(f"Unknown neural control: {action}")
        h, image, text, context = state.h, state.image, state.text, state.context
        if action == "refine_semantic":
            h = h + .25 * self.semantic_cell(torch.cat((h, image, text, context), dim=1))
        elif action == "refine_image":
            image = image + .25 * self.image_cell(torch.cat((h, image, context), dim=1))
        elif action == "refine_text":
            text = text + .25 * self.text_cell(torch.cat((h, text, context), dim=1))
        else:
            changes = self.coupling_cell(torch.cat((h, image, text, context), dim=1))
            dh, di, dt = changes.chunk(3, dim=1)
            h, image, text = h + .25 * dh, image + .25 * di, text + .25 * dt
        return NeuralState(h, image, text, context, state.snapshot_digest)

    def decode(self, state, teacher_tokens=None):
        image_logits = self.pixel_decoder(torch.cat((state.h, state.image), dim=1))
        image_logits = image_logits.reshape(-1, 1, 28, 56)
        hidden = torch.tanh(self.text_initial(torch.cat((state.h, state.text), dim=1))).unsqueeze(0)
        if teacher_tokens is not None:
            hidden_sequence, _ = self.text_decoder(self.token_embedding(teacher_tokens[:, :-1]), hidden)
            text_logits = self.text_projection(hidden_sequence)
            bos = torch.full((len(state.h), 1), BOS, dtype=torch.long, device=state.h.device)
            tokens = torch.cat((bos, text_logits.argmax(-1)), dim=1)
        else:
            token = torch.full((len(state.h), 1), BOS, dtype=torch.long, device=state.h.device)
            emitted, logits = [token], []
            for _ in range(CAPTION_LENGTH - 1):
                hidden_sequence, hidden = self.text_decoder(self.token_embedding(token), hidden)
                step_logits = self.text_projection(hidden_sequence)
                token = step_logits.argmax(-1)
                emitted.append(token)
                logits.append(step_logits)
            tokens, text_logits = torch.cat(emitted, dim=1), torch.cat(logits, dim=1)
        digit_logits = self.digit_head(state.h).reshape(-1, 2, 10)
        return NeuralOutput(image_logits, text_logits, tokens, digit_logits)

    def state_features(self, state):
        return torch.cat((state.h, state.image, state.text, state.context), dim=1)

    def loss(self, output, target):
        if not isinstance(target, Target):
            raise TypeError("Training loss requires Target")
        image_loss = F.binary_cross_entropy_with_logits(
            output.image_logits, target.pixels, reduction="none").flatten(1).mean(1)
        text_loss = F.cross_entropy(output.text_logits.transpose(1, 2),
                                    target.text_tokens[:, 1:], reduction="none").mean(1)
        digit_loss = F.cross_entropy(output.digit_logits.transpose(1, 2),
                                     target.labels, reduction="none").mean(1)
        joint = image_loss + .5 * text_loss + .15 * digit_loss
        return {"image_bce": image_loss, "text_ce": text_loss,
                "digit_ce": digit_loss, "joint": joint, "reward": -joint}


class NeuralSnapshot:
    """Independent frozen parameter copy; public methods never accept Target."""

    def __init__(self, model, metadata=None):
        if (type(self) is NeuralSnapshot
                and model.config.get("architecture", LEGACY_ARCHITECTURE) != LEGACY_ARCHITECTURE):
            raise ValueError("Use snapshot_from_model for an explicit nonlegacy architecture")
        self._model = deepcopy(model).cpu().eval()
        for parameter in self._model.parameters():
            parameter.requires_grad_(False)
        self.fingerprint = parameter_hash(self._model)
        self.metadata = deepcopy(metadata or {})
        self.config = dict(self._model.config)

    def verify_integrity(self):
        if parameter_hash(self._model) != self.fingerprint:
            raise RuntimeError("Inference snapshot parameters changed")
        return self.fingerprint

    def _check_state(self, state):
        if not isinstance(state, NeuralState) or state.snapshot_digest != self.fingerprint:
            raise ValueError("Neural state belongs to a different inference snapshot")

    @torch.inference_mode()
    def encode(self, observation, noise_seed=0, *, content_control=True):
        if type(content_control) is not bool:
            raise TypeError("content_control must be a boolean policy flag")
        self.verify_integrity()
        rng = torch.Generator().manual_seed(int(noise_seed))
        noise = torch.randn((len(observation.pixels), self.config["hidden"]), generator=rng)
        state = self._model.encode(observation, noise=noise)
        return replace(state, snapshot_digest=self.fingerprint)

    @torch.inference_mode()
    def step(self, state, action):
        self._check_state(state)
        return self._model.step(state, action)

    @torch.inference_mode()
    def decode(self, state):
        self._check_state(state)
        return self._model.decode(state)

    @torch.inference_mode()
    def state_features(self, state):
        self._check_state(state)
        return self._model.state_features(state)

    def state_key(self, state):
        self._check_state(state)
        digest = hashlib.sha256(self.fingerprint.encode())
        for tensor in (state.h, state.image, state.text, state.context):
            digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
        return digest.hexdigest()

    def observation_identity(self, state):
        self._check_state(state)
        digest = hashlib.sha256(self.fingerprint.encode())
        digest.update(state.context.detach().cpu().contiguous().numpy().tobytes())
        return digest.hexdigest()

    def save(self, path):
        self.verify_integrity()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(self.to_record(), temporary)
        temporary.replace(path)
        return self.fingerprint

    def to_record(self):
        self.verify_integrity()
        return {"schema": "hepta.ndu-v6.neural-snapshot.v1",
                "config": self.config, "state_dict": self._model.state_dict(),
                "parameter_sha256": self.fingerprint, "metadata": self.metadata}

    @classmethod
    def load(cls, path, *, expected_file_sha256=None):
        return cls._from_record(read_checkpoint(path, expected_file_sha256))

    @classmethod
    def _from_record(cls, record):
        if record.get("schema") != "hepta.ndu-v6.neural-snapshot.v1":
            raise ValueError("Unsupported neural snapshot schema")
        model = NeuralPortfolio(**record["config"])
        model.load_state_dict(record["state_dict"], strict=True)
        snapshot = cls(model, record.get("metadata"))
        if snapshot.fingerprint != record["parameter_sha256"]:
            raise ValueError("Neural snapshot parameter hash mismatch")
        return snapshot


def train_profiles(corpus, config=None, progress=None):
    """Match initial weights, data, latent scenarios, actions and optimizer steps.

    For each input, K latent-noise scenarios have terminal loss L. The baseline
    minimizes mean(L); the NDU profile minimizes log(mean(exp(eta*L)))/eta.
    Equivalently it maximizes entropic certainty equivalent of reward -L. This
    finite empirical conditional distribution is declared, not an estimator of
    arbitrary real-world generation risk. There is no gradient through a free
    reward scale, and no online parameter adaptation during inference.
    """
    config = config or TrainConfig()
    if config.steps < 1 or config.batch_size < 1 or config.scenarios < 2:
        raise ValueError("Training requires positive steps/batch and >=2 scenarios")
    if config.risk_aversion <= 0 or config.refinement_steps < 0:
        raise ValueError("Invalid entropic or refinement configuration")
    torch.set_num_threads(config.threads)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        original = model_from_config({"hidden": config.hidden, "noise_scale": config.noise_scale,
                                      "architecture": config.architecture})
    initial_sha = parameter_hash(original)
    snapshots, reports = {}, {}
    for profile in PROFILES:
        model = deepcopy(original).train()
        optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
        history, schedule_digest = [], hashlib.sha256()
        start = time.perf_counter()
        gradient_evidence = {name: 0. for name in
                             ("pixel_encoder", "pixel_decoder", "text_decoder",
                              "semantic_cell", "image_cell", "text_cell", "coupling_cell")}
        if config.architecture == CONDITIONED_ARCHITECTURE:
            gradient_evidence.update({"command_embedding": 0., "command_film": 0., "fuse": 0.})
        for iteration in range(config.steps):
            batch_seed = config.seed * 1000003 + iteration
            batch = make_batch(corpus, "train", config.batch_size, batch_seed)
            repeats = config.scenarios
            observation = Observation(*(value.repeat_interleave(repeats, dim=0)
                                        for value in (batch.observation.pixels,
                                                      batch.observation.mask,
                                                      batch.observation.text_tokens)))
            target = Target(*(value.repeat_interleave(repeats, dim=0)
                              for value in (batch.target.pixels, batch.target.text_tokens,
                                            batch.target.labels)))
            rng = torch.Generator().manual_seed(batch_seed + 104729)
            noise = torch.randn((config.batch_size * repeats, config.hidden), generator=rng)
            state = model.encode(observation, noise=noise)
            horizon = iteration % (config.refinement_steps + 1)
            action_indices = torch.randint(len(ACTIONS), (horizon,), generator=rng).tolist()
            for action_index in action_indices:
                state = model.step(state, ACTIONS[action_index])
            output = model.decode(state, teacher_tokens=target.text_tokens)
            terms = model.loss(output, target)
            scenario_losses = terms["joint"].reshape(config.batch_size, repeats)
            if profile == "supervised":
                objective = scenario_losses.mean()
            else:
                objective = ((torch.logsumexp(config.risk_aversion * scenario_losses, dim=1)
                              - math.log(repeats)) / config.risk_aversion).mean()
            if not torch.isfinite(objective):
                raise FloatingPointError(f"Non-finite {profile} objective at {iteration}")
            optimizer.zero_grad(set_to_none=True)
            objective.backward()
            for name, parameter in model.named_parameters():
                prefix = name.split(".")[0]
                if prefix in gradient_evidence and parameter.grad is not None:
                    gradient_evidence[prefix] = max(gradient_evidence[prefix],
                                                   float(parameter.grad.detach().abs().sum()))
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            schedule_digest.update(f"{batch_seed}:{action_indices}\n".encode())
            record = {"step": iteration + 1, "objective": float(objective.detach()),
                      "joint_mean": float(terms["joint"].detach().mean()),
                      "image_bce": float(terms["image_bce"].detach().mean()),
                      "text_ce": float(terms["text_ce"].detach().mean()),
                      "horizon": horizon}
            history.append(record)
            if progress is not None and (iteration == 0 or (iteration + 1) % 25 == 0):
                progress(profile, record)
        metadata = {"profile": profile, "config": asdict(config),
                    "initial_parameter_sha256": initial_sha,
                    "source_manifest_sha256": corpus.manifest["manifest_sha256"]}
        snapshots[profile] = snapshot_from_model(model, metadata)
        reports[profile] = {
            **metadata, "final_parameter_sha256": parameter_hash(model),
            "final_snapshot_sha256": snapshots[profile].fingerprint,
            "batch_action_schedule_sha256": schedule_digest.hexdigest(),
            "optimizer_updates": config.steps, "history": history,
            "gradient_abs_sum_max": gradient_evidence,
            "elapsed_seconds": time.perf_counter() - start,
            "parameter_count": sum(p.numel() for p in model.parameters()),
            "conditional_noise_scenarios": repeats,
            "training_reward": "-(pixel_bce + 0.5*teacher_forced_text_ce + 0.15*digit_ce)",
            "training_reward_is_independent_emitted_output_score": False,
            "text_inference": "autoregressive_greedy_without_target_tokens",
            "general_ndu_fbsde_claim": False,
        }
    return snapshots, reports
