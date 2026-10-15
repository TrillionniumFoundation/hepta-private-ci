"""Physical, pinned Granite97 token Encoder and matched Reader CPU canary.

This has a public Hugging Face acquisition path, but no credentials, remote
model code, production promotion, synthetic-success substitution or full V5
campaign claim. The original V5 source/future-task admission stays separate.
All output artifacts are numeric/checksum receipts, never model tensors/text.
"""
import argparse
import json
from pathlib import Path
import resource
import time


MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
EXPECTED_PARAMETERS = 97_441_152
HIDDEN_WIDTH = 384
EXPECTED_LAYERS = 12
EXPECTED_MAX_CONTEXT = 32_768


def validate_profile(*, model_id, revision, parameter_count, hidden_width, layers, context):
    if (model_id != MODEL_ID or revision != REVISION
            or type(parameter_count) is not int or parameter_count != EXPECTED_PARAMETERS
            or type(hidden_width) is not int or hidden_width != HIDDEN_WIDTH
            or type(layers) is not int or layers != EXPECTED_LAYERS
            or type(context) is not int or context != EXPECTED_MAX_CONTEXT):
        raise ValueError("loaded pretrained checkpoint does not match frozen Granite97 R2")
    return dict(model_id=MODEL_ID, revision=REVISION, parameter_count=parameter_count,
                hidden_width=hidden_width, encoder_layers=layers, context_tokens=context)


def exclusive_json(path, data):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def run(*, output, checkpoint=None, acquire_public=False):
    import torch
    import transformers
    from torch.nn import functional as F

    from cross_fact_bridge import matched_reader_pair
    from group_encoder import FrozenTokenEncoder, MODEL_ID as SOURCE_ID
    from group_encoder import REVISION as SOURCE_REVISION
    from group_encoder import acquire, file_digest
    from token_features import TokenBank
    from token_protocol import build_binding_cases
    from token_reader_training import parameter_digest

    if bool(acquire_public) == bool(checkpoint):
        raise ValueError("provide exactly one of --acquire-public and --snapshot")
    if (SOURCE_ID, SOURCE_REVISION) != (MODEL_ID, REVISION):
        raise ValueError("existing Granite loader pins changed")
    if transformers.__version__ != "4.57.1":
        raise ValueError("pinned Transformers 4.57.1 required")
    torch.set_num_threads(1)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("write-once canary output already exists")
    source_dir = Path(__file__).resolve().parents[2]
    if source_dir == output or source_dir in output.parents:
        raise ValueError("model evidence must stay outside the repository")
    output.mkdir(parents=True, exist_ok=False)
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        root = acquire(output / "pinned-public-model") if acquire_public else Path(checkpoint)
        encoder = FrozenTokenEncoder(root, max_tokens=64)
        cfg = encoder.model.config
        model_profile = validate_profile(
            model_id=encoder.material["model_id"], revision=encoder.material["revision"],
            parameter_count=sum(p.numel() for p in encoder.model.parameters()),
            hidden_width=cfg.hidden_size, layers=cfg.num_hidden_layers,
            context=cfg.max_position_embeddings)
        if encoder.model.training or any(p.requires_grad for p in encoder.model.parameters()):
            raise ValueError("pretrained Stem must be completely frozen")

        # TRAIN-only four-group controlled tasks. No official validation or
        # new-source evaluation data is loaded, scored or used to fit.
        cases = build_binding_cases("train", groups=4, seed=41)
        bank = TokenBank(encoder, batch_size=8, chunk_tokens=64)
        bank.register(cases)
        data = bank.batch(cases)
        data.validate(HIDDEN_WIDTH)
        unique_sources = len(set(case.source_hash for case in cases))
        if len(cases) != 16 or unique_sources < 4 or bank.forward_batches < 1:
            raise RuntimeError("actual physical Encoder feature acquisition missing")

        arms = {}
        cross, local = matched_reader_pair(384, 32, seed=41)
        initial = parameter_digest(cross)
        if parameter_digest(local) != initial:
            raise RuntimeError("matched Head and Reader initializations differ")
        for arm, reader in (("cross_fact", cross), ("local", local)):
            reader.train()
            optimizer = torch.optim.AdamW(reader.parameters(), lr=.001, foreach=False)
            arm_wall, arm_cpu = time.perf_counter_ns(), time.process_time_ns()
            for _ in range(2):
                optimizer.zero_grad(set_to_none=True)
                logits = reader(*data.features(), steps=3)
                loss = F.cross_entropy(logits, data.targets)
                if not bool(torch.isfinite(loss).item()):
                    raise FloatingPointError("nonfinite real-Encoder-fed Reader loss")
                loss.backward()
                if any(p.grad is None or not bool(torch.isfinite(p.grad).all().item())
                       for p in reader.parameters()):
                    raise FloatingPointError("nonfinite or missing Reader gradients")
                optimizer.step()
            reader.eval().requires_grad_(False)
            arms[arm] = dict(initial_parameter_sha256=initial,
                trained_parameter_sha256=parameter_digest(reader),
                parameter_count=sum(p.numel() for p in reader.parameters()),
                steps=2, exposures=32, last_train_CE=float(loss.detach().item()),
                cpu_ns=time.process_time_ns()-arm_cpu,
                wall_ns=time.perf_counter_ns()-arm_wall)
        if (arms["cross_fact"]["parameter_count"] != arms["local"]["parameter_count"]
                or arms["cross_fact"]["trained_parameter_sha256"] == initial
                or arms["local"]["trained_parameter_sha256"] == initial):
            raise RuntimeError("matched actual adapter updates or parameter parity missing")
        summary = dict(schema="hepta.granite97.physical-shared-stem-canary.v1",
            model=model_profile,
            model_config_sha256=encoder.material["sha256"]["config.json"],
            model_weights_sha256=encoder.material["sha256"]["model.safetensors"],
            tokenizer_sha256=encoder.tokenizer_digest,
            preprocessing_sha256=bank.preprocess_sha256,
            checkpoint_material_sha256=file_digest(root / "material.json"),
            direct_train_cases=len(cases), train_source_groups=unique_sources,
            physical_encoder_forward_batches=bank.forward_batches,
            encoded_sequences=bank.encoded_sequences, distinct_public_texts=len(bank.values),
            rows_shape=[*data.facts.shape],
            head_comparators=arms,
            total_cpu_ns=time.process_time_ns()-started_cpu,
            total_wall_ns=time.perf_counter_ns()-started_wall,
            max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            encoder_frozen=True, exact_pretrained_loading_verified=True,
            physical_forward_executed=True,
            input_cohort="synthetic_train_4_groups_only",
            original_v5_cache_regenerated=False,
            original_full_six_arm_campaign_executed=False,
            future_multirc_or_natural_efficacy_established=False,
            independent_attestation=False,
            production_authorized=False)
        exclusive_json(output/"probe.json", summary)
        return summary
    except Exception as exc:
        exclusive_json(output/"FAILED.json", dict(schema="hepta.granite97.failed-canary.v1",
            error_type=type(exc).__name__, public_model_id=MODEL_ID, revision=REVISION,
            completed=False, production_authorized=False))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--acquire-public", action="store_true")
    source.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(output=args.output, checkpoint=args.snapshot, acquire_public=args.acquire_public)
    print(json.dumps(dict(schema=result["schema"], model=result["model"],
                          physical_encoder_forward_batches=result["physical_encoder_forward_batches"],
                          head_comparators=result["head_comparators"],
                          original_full_six_arm_campaign_executed=False,
                          production_authorized=False), sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
