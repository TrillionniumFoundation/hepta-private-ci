"""Frozen Florence execution with causal, pre-selection decoder interventions.

The fixed task adapter translates the requested category to Florence's native
phrase-grounding prompt. Boxes are decoded from model tokens, never repaired
with reference annotations. Text is a declared rendering of those same boxes.
"""

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import time

from PIL import Image
import torch
from transformers import AutoProcessor, Florence2ForConditionalGeneration
from transformers.generation.logits_process import (
    ForcedBOSTokenLogitsProcessor,
    ForcedEOSTokenLogitsProcessor,
    LogitsProcessorList,
    NoRepeatNGramLogitsProcessor,
)


MODEL_REVISION = "00921df66db728a9ceb750f5eca43e5c203a2051"
WEIGHT_SHA256 = "62f3e696da74f8869a68ddb529a9b3e14eb25b21c592cb3dea6179bf944df6a0"
OBSERVATION_FIELDS = frozenset(
    ("task_id", "image_path", "image_sha256", "prompt", "target_category")
)
TASK = "<CAPTION_TO_PHRASE_GROUNDING>"


@dataclass
class EncodedObservation:
    observation: dict
    encoder_outputs: object
    attention_mask: torch.Tensor
    image_size: tuple
    costs: dict
    encoder_feature: torch.Tensor


def explanation(category, boxes):
    """Render the declared count and side task without adding external facts."""
    first = f"There are {len(boxes)} {category} instances."
    if not boxes:
        return first + " No largest instance."
    largest = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    side = "left" if (largest[0] + largest[2]) / 2 < 0.5 else "right"
    return first + f" The largest instance is on the {side}."


def tensor_sha256(model):
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        digest.update(name.encode())
        digest.update(str(tuple(value.shape)).encode())
        digest.update(str(value.dtype).encode())
        digest.update(memoryview(value.detach().cpu().contiguous().numpy()).cast("B"))
    return digest.hexdigest()


class FlorenceBackend:
    """One frozen shared backbone; cached encoders are fully charged per arm."""

    def __init__(self, model_path, threads=4):
        started = time.perf_counter()
        self.model_path = Path(model_path)
        with (self.model_path / "model.safetensors").open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != WEIGHT_SHA256:
            raise ValueError("checkpoint weight SHA256 does not match the fixed base")
        torch.set_num_threads(threads)
        self.processor = AutoProcessor.from_pretrained(
            str(self.model_path), trust_remote_code=False, local_files_only=True
        )
        self.tokenizer = self.processor.tokenizer
        self.model = Florence2ForConditionalGeneration.from_pretrained(
            str(self.model_path), dtype=torch.float32,
            attn_implementation="eager", local_files_only=True,
        ).eval()
        self.model.requires_grad_(False)
        self.hidden_size = self.model.config.text_config.hidden_size
        self.vocab_size = self.model.config.text_config.vocab_size
        self.location_token_ids = self.tokenizer.convert_tokens_to_ids(
            [f"<loc_{index}>" for index in range(1000)]
        )
        self.start_token_id = self.model.generation_config.decoder_start_token_id
        self.eos_token_id = self.tokenizer.eos_token_id
        self.frozen_before = tensor_sha256(self.model)
        self.load_seconds = time.perf_counter() - started

    @torch.no_grad()
    def encode(self, observation):
        if set(observation) != OBSERVATION_FIELDS:
            raise ValueError("backend observation must contain exactly the five public fields")
        if not all(isinstance(value, str) and value for value in observation.values()):
            raise ValueError("observation values must be nonempty strings")
        started = time.perf_counter()
        path = Path(observation["image_path"])
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != observation["image_sha256"]:
            raise ValueError("observation image hash mismatch")
        with Image.open(path) as source:
            image = source.convert("RGB")
        inputs = self.processor(
            text=TASK + observation["target_category"], images=image, return_tensors="pt"
        )
        preprocessed = time.perf_counter()
        embeddings = self.model.model.get_input_embeddings()(inputs["input_ids"])
        image_features = self.model.get_image_features(inputs["pixel_values"]).pooler_output
        mask = self.model.get_placeholder_mask(inputs["input_ids"], embeddings, image_features)
        embeddings = embeddings.masked_scatter(mask, image_features)
        vision_finished = time.perf_counter()
        encoded = self.model.model.language_model.encoder(
            inputs_embeds=embeddings, attention_mask=inputs["attention_mask"], return_dict=True
        )
        ended = time.perf_counter()
        costs = {
            "encoder_seconds": ended - started,
            "preprocessor_seconds": preprocessed - started,
            "vision_seconds": vision_finished - preprocessed,
            "text_encoder_seconds": ended - vision_finished,
            "encoder_calls": 1,
            "input_tokens": int(inputs["input_ids"].numel()),
            "visual_tokens": int(image_features.shape[1]),
        }
        return EncodedObservation(
            dict(observation), encoded, inputs["attention_mask"], image.size, costs,
            encoded.last_hidden_state.mean(dim=1).squeeze(0).detach(),
        )

    def _processors(self, max_new_tokens):
        processors = LogitsProcessorList()
        config = self.model.generation_config
        if config.no_repeat_ngram_size:
            processors.append(NoRepeatNGramLogitsProcessor(config.no_repeat_ngram_size))
        if config.forced_bos_token_id is not None:
            processors.append(ForcedBOSTokenLogitsProcessor(config.forced_bos_token_id))
        if config.forced_eos_token_id is not None:
            processors.append(ForcedEOSTokenLogitsProcessor(
                max_new_tokens + 1, config.forced_eos_token_id
            ))
        return processors

    @torch.no_grad()
    def generate(self, encoded, modifier=None, max_new_tokens=48, checkpoint_stride=4,
                 max_checkpoints=8, max_wall_seconds=60.0, do_sample=False,
                 temperature=1.0, seed=0):
        if min(max_new_tokens, checkpoint_stride, max_checkpoints) < 1:
            raise ValueError("token and checkpoint limits must be positive")
        if not math.isfinite(max_wall_seconds) or max_wall_seconds <= 0:
            raise ValueError("wall budget must be finite and positive")
        if do_sample and (not math.isfinite(temperature) or temperature <= 0):
            raise ValueError("sampling temperature must be finite and positive")
        started = time.perf_counter()
        encoder_seconds = encoded.costs["encoder_seconds"]
        prefix = [self.start_token_id]
        past = None
        controls = []
        decoder_seconds = modifier_seconds = cell_seconds = controller_seconds = 0.0
        decoder_calls = 0
        termination = "max_tokens"
        processors = self._processors(max_new_tokens)
        generator = torch.Generator(device="cpu").manual_seed(seed)
        for step in range(max_new_tokens):
            if encoder_seconds + time.perf_counter() - started >= max_wall_seconds:
                termination = "budget"
                break
            forward_started = time.perf_counter()
            output = self.model.model.language_model.decoder(
                input_ids=torch.tensor([[prefix[-1]]]),
                encoder_hidden_states=encoded.encoder_outputs.last_hidden_state,
                encoder_attention_mask=encoded.attention_mask,
                past_key_values=past, use_cache=True, return_dict=True,
            )
            past = output.past_key_values
            hidden = output.last_hidden_state[0, -1]
            raw_logits = self.model.lm_head(hidden)
            decoder_seconds += time.perf_counter() - forward_started
            decoder_calls += 1
            prefix_tensor = torch.tensor([prefix])
            base_logits = processors(prefix_tensor, raw_logits.unsqueeze(0).clone())[0]
            base_argmax = int(base_logits.argmax())
            checkpoint = min(step // checkpoint_stride, max_checkpoints - 1)
            checkpoint_changed = step % checkpoint_stride == 0 and step // checkpoint_stride < max_checkpoints
            logits, update = base_logits.clone(), {}
            if modifier is not None:
                state = {
                    "hidden": hidden.detach(), "logits": base_logits.clone(),
                    "token_ids": list(prefix), "checkpoint": checkpoint, "step": step,
                    "checkpoint_changed": checkpoint_changed,
                    "remaining_seconds": max(0.0, max_wall_seconds - encoder_seconds - time.perf_counter() + started),
                }
                control_started = time.perf_counter()
                update = modifier(state)
                modifier_seconds += time.perf_counter() - control_started
                if not isinstance(update, dict) or ("delta" in update) == ("logits" in update):
                    raise ValueError("modifier must return exactly one of delta or logits")
                value = torch.as_tensor(update.get("delta", update.get("logits")), dtype=logits.dtype)
                if value.shape != logits.shape or torch.isnan(value).any() or torch.isposinf(value).any():
                    raise ValueError("modifier returned invalid logit shape or values")
                logits = base_logits + value if "delta" in update else value.clone()
                logits = processors(prefix_tensor, logits.unsqueeze(0))[0]
                if not torch.isfinite(logits).any():
                    raise ValueError("modifier masked every token")
                extra = update.get("extra", {})
                cell_seconds += float(extra.get("cell_seconds", 0.0))
                controller_seconds += float(extra.get("controller_seconds", 0.0))
            if encoder_seconds + time.perf_counter() - started >= max_wall_seconds:
                termination = "budget"
                break
            controlled_argmax = int(logits.argmax())
            sampling_logits = logits / temperature if do_sample else logits
            selected = int(torch.multinomial(torch.softmax(sampling_logits, -1), 1, generator=generator)) if do_sample else controlled_argmax
            controls.append({
                "step": step, "checkpoint": checkpoint, "checkpoint_changed": checkpoint_changed,
                "modifier_applied": modifier is not None,
                "weights": update.get("weights", []), "action": int(update.get("action", -1)),
                "base_argmax": base_argmax, "controlled_argmax": controlled_argmax,
                "argmax_changed": base_argmax != controlled_argmax,
                "selected_id": selected,
                "base_logprob": float(torch.log_softmax(base_logits, -1)[selected]),
                "controlled_logprob": float(torch.log_softmax(logits, -1)[selected]),
                "extra": update.get("extra", {}),
            })
            prefix.append(selected)
            if selected == self.eos_token_id:
                termination = "eos" if step + 1 < max_new_tokens else "max_tokens"
                break
        parse_started = time.perf_counter()
        raw_text = self.tokenizer.decode(prefix, skip_special_tokens=False)
        parsed = self.processor.post_process_generation(
            raw_text, task=TASK, image_size=encoded.image_size
        )[TASK]
        width, height = encoded.image_size
        boxes = [[x1 / width, y1 / height, x2 / width, y2 / height]
                 for x1, y1, x2, y2 in parsed["bboxes"]]
        text = explanation(encoded.observation["target_category"], boxes)
        parsing_seconds = time.perf_counter() - parse_started
        elapsed = time.perf_counter() - started
        costs = {
            **encoded.costs,
            "decoder_seconds": decoder_seconds, "modifier_seconds": modifier_seconds,
            "cell_seconds": cell_seconds, "controller_seconds": controller_seconds,
            "parsing_seconds": parsing_seconds,
            "loop_overhead_seconds": max(0.0, elapsed - decoder_seconds - modifier_seconds - parsing_seconds),
            "backbone_seconds": encoded.costs["vision_seconds"] + encoded.costs["text_encoder_seconds"] + decoder_seconds,
            "charged_seconds": encoder_seconds + elapsed,
            "actual_generate_seconds": elapsed,
            "encoder_cache_reused": True,
            "executed_encoder_calls_in_generate": 0,
            "decoder_forward_calls": decoder_calls, "generated_tokens": len(prefix) - 1,
            "actual_checkpoints": sum(item["checkpoint_changed"] and item["modifier_applied"] for item in controls),
            "decoder_checkpoints_visited": sum(item["checkpoint_changed"] for item in controls),
            "max_wall_seconds": max_wall_seconds,
            "budget_overrun_seconds": max(0.0, encoder_seconds + elapsed - max_wall_seconds),
        }
        return {
            "task_id": encoded.observation["task_id"], "raw_text": raw_text,
            "tokens": prefix, "boxes": boxes, "labels": parsed["labels"], "text": text,
            "controls": controls, "costs": costs, "termination": termination,
        }

    @torch.no_grad()
    def teacher_forced_features(self, encoded, target_text, token_subset=None):
        """Training-only teacher prefixes; references never enter generation."""
        started = time.perf_counter()
        target_ids = torch.tensor(self.tokenizer.encode(target_text, add_special_tokens=True))
        decoder_ids = torch.cat((torch.tensor([self.start_token_id]), target_ids[:-1]))
        output = self.model.model.language_model.decoder(
            input_ids=decoder_ids.unsqueeze(0),
            encoder_hidden_states=encoded.encoder_outputs.last_hidden_state,
            encoder_attention_mask=encoded.attention_mask,
            use_cache=False, return_dict=True,
        )
        hidden = output.last_hidden_state[0].detach()
        logits = self.model.lm_head(hidden)
        normalizer = torch.logsumexp(logits, dim=-1)
        target_log_probs = logits.gather(1, target_ids[:, None]).squeeze(1) - normalizer
        subset = None if token_subset is None else torch.as_tensor(token_subset, dtype=torch.long)
        if subset is not None and (subset.ndim != 1 or subset.numel() != subset.unique().numel()
                                   or (subset < 0).any() or (subset >= self.vocab_size).any()):
            raise ValueError("token_subset must contain unique valid vocabulary IDs")
        selected = None if subset is None else logits.index_select(1, subset).clone()
        return {
            "hidden": hidden, "target_ids": target_ids,
            "decoder_prefixes": [decoder_ids[:index + 1].tolist() for index in range(len(target_ids))],
            "logits": selected, "token_subset": subset,
            "full_logsumexp": normalizer, "target_log_probs": target_log_probs,
            "costs": {"teacher_decoder_seconds": time.perf_counter() - started,
                      "encoder_seconds": encoded.costs["encoder_seconds"],
                      "teacher_tokens": int(target_ids.numel())},
        }

    def frozen_receipt(self):
        after = tensor_sha256(self.model)
        return {
            "repository": "florence-community/Florence-2-base", "revision": MODEL_REVISION,
            "checkpoint_sha256": WEIGHT_SHA256,
            "tensor_sha256_before": self.frozen_before, "tensor_sha256_after": after,
            "frozen_unchanged": self.frozen_before == after,
            "trainable_parameters": sum(p.numel() for p in self.model.parameters() if p.requires_grad),
            "parameters": sum(p.numel() for p in self.model.parameters()),
            "load_seconds": self.load_seconds, "device": "cpu", "dtype": "float32",
        }
