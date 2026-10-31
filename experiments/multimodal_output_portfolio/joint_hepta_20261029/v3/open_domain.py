"""Local free-text decoding from an actual Hepta state; public development only.

This adds a real causal LM, not an ontology-to-sentence template. The tiny
source-disjoint documentation exercise tests the interface and its failures;
it cannot qualify open-domain competence or natural audio/video generation.
"""

import argparse
import bisect
import csv
from dataclasses import dataclass
import functools
import gzip
import hashlib
import inspect
from importlib.metadata import version
import json
from pathlib import Path
import platform
import re
import statistics
import textwrap
import time
import urllib.parse

try:
    import resource
except ImportError:
    resource = None

import torch
from torch import nn

from ..model import tensor_digest
from .model import JointGenerator


MODEL_ID = "HuggingFaceTB/SmolLM2-135M-Instruct"
MODEL_REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"
MODEL_WEIGHTS_SHA256 = "5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c"
ARMS = ("state", "zero_state", "shuffled_state")


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


@dataclass(frozen=True)
class GenerationRequest:
    """Only evidence available to the generator; no reference or score fields."""

    case_id: str
    question: str
    context: str
    source_id: str

    def prompt(self):
        return ("Use the documentation below to answer the question in one or two "
                "complete sentences. Do not invent facts.\n\nDocumentation:\n"
                + self.context + "\n\nQuestion: " + self.question)


@dataclass(frozen=True)
class DevelopmentCase:
    request: GenerationRequest
    role: str
    reference: str
    required: tuple
    contradictions: tuple = ()


def public_documentation_cases():
    """Real CPython docstrings, disjoint by module; all cases are public dev.

    Pretraining contamination is unknown. References are authored supervision,
    not generated predictions. No external dataset or calibration path is read.
    """
    specs = [
        ("json.loads", json.loads, "fit", "What input does loads accept and what does it produce?",
         "It converts a JSON document in a string, bytes, or bytearray into a Python object.", ()),
        ("textwrap.dedent", textwrap.dedent, "fit", "What does dedent remove from the text?",
         "It removes common leading whitespace from each line of the text.", ()),
        ("bisect.bisect_left", bisect.bisect_left, "fit", "Where does bisect_left place a value already in a sorted list?",
         "It returns an insertion index before the leftmost existing equal value in the sorted list.", ()),
        ("urllib.parse.urlsplit", urllib.parse.urlsplit, "fit", "What are the five components returned by urlsplit?",
         "The five components are scheme, netloc, path, query, and fragment.", ()),
        ("statistics.mean", statistics.mean, "development_evaluation",
         "What does mean compute, and what happens when its input data is empty?",
         "It computes the arithmetic mean and raises StatisticsError for empty data.",
         (r"arithmetic\s+(?:mean|average)|(?:mean|average)\s+of", r"(?:rais\w*|throw\w*|error|exception).*statisticserror|statisticserror"),
         (r"(?:return\w*|yield\w*)\s+(?:a\s+)?(?:zero|0|null|none)\b", r"(?:not|never|no)\s+(?:rais\w*|throw\w*|error|exception)")),
        ("functools.lru_cache", functools.lru_cache, "development_evaluation",
         "How large can the cache become with maxsize=None, and what property must arguments have?",
         "With maxsize=None the cache can grow without bound, and the arguments must be hashable.",
         (r"without\s+(?:a\s+)?(?:bound|limit)|unbound\w*|unlimit\w*|indefinite", r"\bhashable\b"),
         (r"unhashable|need\s+not\s+be\s+hashable|not\s+(?:need|require).*hashable", r"cach(?:e|ing)\s+is\s+disabled")),
        ("gzip.open", gzip.open, "development_evaluation",
         "Which file format does open handle, and is its default mode text or binary?",
         "It opens gzip-compressed files and defaults to binary read mode, rb.",
         (r"\bgzip\b", r"\bbinary\b|\brb\b"),
         (r"default\w*.{0,35}\btext\b",)),
        ("csv.reader", csv.reader, "development_evaluation",
         "What does reader return and what does each iteration provide?",
         "It returns an iterator, and each iteration returns one CSV row.",
         (r"\biterator\b|iterable", r"(?:each|one|single|every).{0,45}\brow\b|\brow\s+at\s+a\s+time"),
         (r"(?:return\w*|yield\w*).{0,30}(?:entire|whole)\s+file",)),
    ]
    cases = []
    for name, function, role, question, reference, required, *bad in specs:
        context = inspect.getdoc(function)
        if not context:
            raise ValueError("Missing natural source docstring: " + name)
        module = name.rsplit(".", 1)[0]
        request = GenerationRequest(name, question, context, "cpython:" + module)
        cases.append(DevelopmentCase(request, role, reference, required, bad[0] if bad else ()))
    validate_source_isolation(cases)
    return cases


def validate_source_isolation(cases):
    groups = {}
    for case in cases:
        if case.role not in {"fit", "development_evaluation"}:
            raise ValueError("This runner accepts public development roles only")
        if case.request.source_id in groups and groups[case.request.source_id] != case.role:
            raise ValueError("Source appears in both fit and evaluation")
        groups[case.request.source_id] = case.role
    if len({case.request.case_id for case in cases}) != len(cases):
        raise ValueError("Duplicate case identity")


def independent_development_score(case, completion):
    """Fixed factual predicates, independent of state, training loss and LM.

    This deliberately modest scorer is not a general semantic judge. A human
    blind-review packet accompanies every experiment; its results stay pending.
    """
    text = " ".join(completion.casefold().split())
    checks = [bool(re.search(pattern, text)) for pattern in case.required]
    contradictions = [pattern for pattern in case.contradictions if re.search(pattern, text)]
    words = re.findall(r"\b\w+\b", completion)
    return {"fact_matches": checks, "fact_fraction": sum(checks) / max(1, len(checks)),
            "contradictions": contradictions,
            "all_fixed_facts_without_flagged_contradiction": bool(checks) and all(checks) and not contradictions,
            "word_count": len(words), "general_semantic_validity": "requires_independent_human_review"}


def text_public_input(request, max_characters=2048):
    """Use the inherited real text encoder; other modalities are explicitly absent.

    Its character-mean embedding is a small-capacity text representation, not a
    pretrained language encoder. The full evidence remains in the LM prompt.
    """
    text = (request.question + "\n" + request.context).encode("ascii", errors="replace")
    if len(text) > max_characters:
        raise ValueError("Source exceeds the declared Hepta input bound")
    zeros = torch.zeros
    return {"image": zeros(1, 3, 16, 16), "image_mask": zeros(1, 3, 16, 16),
            "audio": zeros(1, 1024), "audio_mask": zeros(1, 1024),
            "video": zeros(1, 4, 3, 16, 16), "video_mask": zeros(1, 4, 3, 16, 16),
            "tokens": torch.tensor([list(text)], dtype=torch.long)}


def validate_local_model(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "material-manifest.json").read_text())
    if (manifest["model"], manifest["revision"]) != (MODEL_ID, MODEL_REVISION):
        raise ValueError("Model identity differs from this development registration")
    if manifest["files"]["model.safetensors"]["sha256"] != MODEL_WEIGHTS_SHA256:
        raise ValueError("Model weight manifest identity differs")
    checked = {}
    for name, metadata in manifest["files"].items():
        if Path(name).name != name:
            raise ValueError("Local model manifest path must be a filename")
        path = directory / name
        actual = file_digest(path)
        if path.stat().st_size != metadata["size"] or actual != metadata["sha256"]:
            raise ValueError("Model material hash/size mismatch: " + name)
        checked[name] = {"sha256": actual, "bytes": metadata["size"]}
    return {"model": MODEL_ID, "revision": MODEL_REVISION, "files": checked}


class StateConditionedText(nn.Module):
    """Hepta shared/slot state -> learned continuous prefix -> frozen causal LM."""

    def __init__(self, hepta, language_model, tokenizer, prefix_tokens=2):
        super().__init__()
        self.hepta, self.language_model, self.tokenizer = hepta, language_model, tokenizer
        self.prefix_tokens = prefix_tokens
        self.hidden = language_model.config.hidden_size
        self.prefix = nn.Sequential(nn.LayerNorm(5 * hepta.width),
                                    nn.Linear(5 * hepta.width, prefix_tokens * self.hidden), nn.Tanh())
        nn.init.normal_(self.prefix[1].weight, std=0.002)
        nn.init.zeros_(self.prefix[1].bias)
        for parameter in language_model.parameters():
            parameter.requires_grad_(False)
        # Only the content path is trained. Portfolio actor/critics and old
        # ontology/media emission heads have no role in this text experiment.
        for name, parameter in hepta.named_parameters():
            if name.startswith(("actor.", "critic.", "delivery_critic.", "emissions.")):
                parameter.requires_grad_(False)

    def generation_state(self, request):
        public = text_public_input(request)
        state = self.hepta.encode(public)
        for action in ("shared", "text"):
            state, _ = self.hepta.advance(state, action, public)
        return torch.cat((state.shared, state.slots.flatten(1)), -1)

    def prefix_embeddings(self, vector):
        if vector.shape != (1, 5 * self.hepta.width) or not bool(torch.isfinite(vector).all()):
            raise ValueError("Condition must be the finite shared-plus-slots Hepta state")
        return 0.05 * self.prefix(vector).reshape(1, self.prefix_tokens, self.hidden)

    def prompt_ids(self, request):
        ids = self.tokenizer.apply_chat_template(
            [{"role": "user", "content": request.prompt()}],
            add_generation_prompt=True, return_tensors="pt")
        if ids.shape[1] > 1024:
            raise ValueError("Full prompt exceeds the declared LM token bound")
        return ids

    def training_loss(self, case):
        prompt = self.prompt_ids(case.request)
        target = self.tokenizer(case.reference, add_special_tokens=False, return_tensors="pt")["input_ids"]
        target = torch.cat((target, torch.tensor([[self.tokenizer.eos_token_id]])), 1)
        all_ids = torch.cat((prompt, target), 1)
        embedded = self.language_model.get_input_embeddings()(all_ids)
        prefix = self.prefix_embeddings(self.generation_state(case.request))
        embeddings = torch.cat((prefix, embedded), 1)
        labels = torch.full((1, embeddings.shape[1]), -100, dtype=torch.long)
        labels[:, -target.shape[1]:] = target
        return self.language_model(inputs_embeds=embeddings, attention_mask=torch.ones_like(labels),
                                   labels=labels, use_cache=False).loss

    @torch.no_grad()
    def generate(self, request, vector, max_new_tokens=64):
        """Greedy unconstrained vocabulary decoding; no inserted answer text."""
        if not 1 <= max_new_tokens <= 256:
            raise ValueError("max_new_tokens must be between 1 and 256")
        ids = self.prompt_ids(request)
        prefix = self.prefix_embeddings(vector)
        embeddings = torch.cat((prefix, self.language_model.get_input_embeddings()(ids)), 1)
        attention = torch.ones(1, embeddings.shape[1], dtype=torch.long)
        output = self.language_model(inputs_embeds=embeddings, attention_mask=attention, use_cache=True)
        first_logits = output.logits[:, -1].clone()
        generated = []
        for _ in range(max_new_tokens):
            token = output.logits[:, -1].argmax(-1, keepdim=True)
            generated.append(int(token.item()))
            if generated[-1] == self.tokenizer.eos_token_id:
                break
            attention = torch.cat((attention, torch.ones(1, 1, dtype=torch.long)), 1)
            output = self.language_model(input_ids=token, attention_mask=attention,
                                         past_key_values=output.past_key_values, use_cache=True)
        return {"text": self.tokenizer.decode(generated, skip_special_tokens=True),
                "generated_token_ids": generated, "new_tokens": len(generated),
                "prompt_tokens": ids.shape[1], "prefix_tokens": self.prefix_tokens,
                "stopped_on_eos": generated[-1] == self.tokenizer.eos_token_id}, first_logits


def run(model_path, checkpoint, output, updates=16, max_new_tokens=64, seed=419, threads=2):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if type(updates) is not int or not 1 <= updates <= 256:
        raise ValueError("A bounded positive training update count is required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    cases = public_documentation_cases()
    fit = [case for case in cases if case.role == "fit"]
    evaluation = [case for case in cases if case.role == "development_evaluation"]
    source_directory = Path(__file__).resolve().parents[1]
    source_files = (Path(__file__).resolve(), Path(__file__).resolve().parent / "model.py",
                    source_directory / "model.py", source_directory / "hepta_core.py")
    protocol = {"schema": "hepta.free-text-development.v3", "status": "registered_before_training",
                "seed": seed, "updates": updates, "max_new_tokens": max_new_tokens,
                "threads": threads, "arms": ARMS, "prefix_tokens": 2, "prefix_scale": 0.05,
                "base_checkpoint_sha256": file_digest(checkpoint), "code_sha256": file_digest(__file__),
                "source_files": {str(path.relative_to(source_directory)): file_digest(path) for path in source_files},
                "runtime": {"python": platform.python_version(), "torch": str(torch.__version__),
                            "transformers": version("transformers")},
                "source_split_unit": "CPython module; publisher and pretraining may overlap",
                "never_seen_claim": False, "fresh_calibration_access": False,
                "all_data_roles": "public_development", "checkpoint_selection": "last_update_only",
                "full_prompt_identical_across_arms": True, "lm_frozen": True,
                "hepta_and_prefix_trained": True, "optimizer": "Adam; lr=0.0003; clip_norm=1",
                "hepta_action_schedule": ["shared", "text"],
                "sources": [{"case_id": c.request.case_id, "source_id": c.request.source_id,
                             "source_uri": "https://docs.python.org/3/library/" + c.request.source_id.split(":")[1] + ".html",
                             "context_sha256": hashlib.sha256(c.request.context.encode()).hexdigest(),
                             "context": c.request.context, "question": c.request.question, "role": c.role,
                             "reference": c.reference, "required_patterns": c.required,
                             "contradiction_patterns": c.contradictions} for c in cases]}
    write_json(output / "protocol.json", protocol)
    identity = validate_local_model(model_path)
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    hepta = JointGenerator(**payload["config"])
    hepta.load_state_dict(payload["state_dict"], strict=True)
    initial_hepta = tensor_digest(hepta.state_dict())
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    lm = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True,
                                            trust_remote_code=False, dtype=torch.float32).eval()
    model = StateConditionedText(hepta, lm, tokenizer)
    initial_prefix = tensor_digest(model.prefix.state_dict())
    initial_lm = tensor_digest(lm.state_dict())
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=0.0003)
    phases = {"preflight_and_load": {"wall_seconds": time.perf_counter() - started,
                                     "cpu_seconds": time.process_time() - cpu}}
    training_started, training_cpu = time.perf_counter(), time.process_time()
    losses, gradients = [], {}
    for update in range(updates):
        case = fit[update % len(fit)]
        optimizer.zero_grad(set_to_none=True)
        loss = model.training_loss(case)
        loss.backward()
        for name, parameter in model.named_parameters():
            if parameter.grad is not None:
                if not bool(torch.isfinite(parameter.grad).all()):
                    raise ValueError("Nonfinite gradient: " + name)
                group = ".".join(name.split(".")[:2])
                gradients[group] = max(gradients.get(group, 0.), float(parameter.grad.abs().sum()))
        torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1., error_if_nonfinite=True)
        optimizer.step()
        losses.append({"update": update, "case_id": case.request.case_id, "loss": float(loss.detach())})
        if update % 4 == 0:
            print(json.dumps({"open_text_update": update, "loss": losses[-1]["loss"]}), flush=True)
    phases["adaptation_training"] = {"wall_seconds": time.perf_counter() - training_started,
                                      "cpu_seconds": time.process_time() - training_cpu}
    generation_started, generation_cpu = time.perf_counter(), time.process_time()
    model.eval()
    with torch.no_grad():
        vectors = [model.generation_state(case.request).detach() for case in evaluation]
    rows, effects = [], []
    for index, case in enumerate(evaluation):
        logits, texts = {}, {}
        for arm in ARMS:
            vector = (vectors[index] if arm == "state" else torch.zeros_like(vectors[index])
                      if arm == "zero_state" else vectors[(index + 1) % len(vectors)])
            before, before_cpu = time.perf_counter(), time.process_time()
            generated, logits[arm] = model.generate(case.request, vector, max_new_tokens)
            row = {"case_id": case.request.case_id, "source_id": case.request.source_id, "arm": arm,
                   "state_sha256": tensor_digest(vector), **generated,
                   "wall_seconds": time.perf_counter() - before,
                   "cpu_seconds": time.process_time() - before_cpu}
            rows.append(row)
            texts[arm] = generated["text"]
            print(json.dumps({"open_text_case": row["case_id"], "arm": arm, "new_tokens": row["new_tokens"]}), flush=True)
        effects.append({"case_id": case.request.case_id,
                        "state_vs_zero_logit_l2": float((logits["state"] - logits["zero_state"]).norm()),
                        "state_vs_shuffle_logit_l2": float((logits["state"] - logits["shuffled_state"]).norm()),
                        "state_changes_text_vs_zero": texts["state"] != texts["zero_state"],
                        "state_changes_text_vs_shuffle": texts["state"] != texts["shuffled_state"]})
    phases["state_encoding_and_all_decoding"] = {"wall_seconds": time.perf_counter() - generation_started,
                                                 "cpu_seconds": time.process_time() - generation_cpu}
    postprocess_started, postprocess_cpu = time.perf_counter(), time.process_time()
    # Evaluation begins only after every completion has been fixed. No score is
    # fed into gradient updates, generation, arm selection or checkpoint choice.
    lookup = {case.request.case_id: case for case in evaluation}
    for row in rows:
        row["independent_development_evaluation"] = independent_development_score(lookup[row["case_id"]], row["text"])
    with (output / "completions.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
    blind, key = [], {}
    order = torch.randperm(len(rows), generator=torch.Generator().manual_seed(seed + 1)).tolist()
    for number, index in enumerate(order):
        row, blind_id = rows[index], f"review-{number:03d}"
        request = lookup[row["case_id"]].request
        blind.append({"blind_id": blind_id, "question": request.question, "context": request.context,
                      "completion": row["text"], "rubric": ["factual_correctness", "coverage", "unsupported_claims", "fluency"],
                      "human_ratings": None})
        key[blind_id] = {"case_id": row["case_id"], "arm": row["arm"]}
    write_json(output / "blind_review.json", blind)
    write_json(output / "blind_key.json", key)
    torch.save({"config": hepta.config, "state_dict": hepta.state_dict(),
                "prefix_state_dict": model.prefix.state_dict(), "prefix_tokens": 2,
                "prefix_scale": 0.05, "model_identity": identity}, output / "adapter.pt")
    final_lm = tensor_digest(lm.state_dict())
    if initial_lm != final_lm:
        raise ValueError("Frozen LM weights changed during adaptation")
    phases["evaluation_evidence_and_weight_audit"] = {"wall_seconds": time.perf_counter() - postprocess_started,
                                                       "cpu_seconds": time.process_time() - postprocess_cpu}
    report = {"schema": protocol["schema"], "status": "completed_public_development",
              "model_identity": identity, "python": platform.python_version(), "torch": torch.__version__,
              "base_checkpoint_sha256": protocol["base_checkpoint_sha256"],
              "initial_hepta_sha256": initial_hepta, "final_hepta_sha256": tensor_digest(hepta.state_dict()),
              "initial_prefix_sha256": initial_prefix, "final_prefix_sha256": tensor_digest(model.prefix.state_dict()),
              "frozen_lm_before_sha256": initial_lm, "frozen_lm_after_sha256": final_lm,
              "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
              "frozen_lm_parameters": sum(p.numel() for p in lm.parameters()), "losses": losses,
              "decoder_vocabulary_size": lm.config.vocab_size,
              "decoding_rule": "greedy full vocabulary; only EOS and maximum token count terminate generation",
              "adapter_checkpoint_bytes": (output / "adapter.pt").stat().st_size,
              "reused_local_model_bytes": sum(item["bytes"] for item in identity["files"].values()),
              "gradient_max_l1_by_group": gradients, "causal_state_interventions": effects,
              "fixed_fact_passes_by_arm": {arm: sum(bool(row["independent_development_evaluation"]["all_fixed_facts_without_flagged_contradiction"])
                                                       for row in rows if row["arm"] == arm) for arm in ARMS},
              "cases_per_arm": len(evaluation), "generated_tokens": sum(row["new_tokens"] for row in rows),
              "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
              "timing_scope": "run() after Python/dependency imports; includes model verification/loading, adaptation, all inference and evidence work",
              "process_cpu_seconds_including_imports": time.process_time(),
              "phase_costs": phases,
              "process_peak_rss_bytes": (None if resource is None else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                                         * (1 if platform.system() == "Darwin" else 1024)),
              "per_completion_timing_scope": "LM prefill and decoding; shared state encoding/loading/training is included only in total run timing",
              "natural_audio_generation": False, "natural_video_generation": False,
              "open_domain_qualified": False, "natural_multimodal_gain_claim": False,
              "human_evaluation": "pending; no ratings invented", "fresh_calibration_access": False,
              "scope": "Real free-form LM plus learned Hepta-state prefix; small public technical-QA development slice"}
    write_json(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--updates", type=int, default=16)
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    result = run(args.model_path, args.checkpoint, args.output, args.updates, args.max_new_tokens, threads=args.threads)
    print(json.dumps({"status": result["status"], "fixed_fact_passes_by_arm": result["fixed_fact_passes_by_arm"]}), flush=True)
