"""Answer-content scoring on shared CLIP projections, never fixed answer slots.

The same existing gated Head scores all four candidates. Three matched residual
arms isolate a frozen image/text similarity prior from trainable capacity. No
claim that similarity is a sufficient QA representation; no new runtime owner.
"""
from pathlib import Path

import torch
from torch import nn

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell.calibrated_fusion import score

MODES = ("visual_prior", "visual_zero", "text_only")


def candidate_texts(row):
    """Public content only. No letter/index, answer, lecture or solution enters."""
    from experiments.shared_stem_cell.public_media import prompt
    if prompt(row) is None:
        raise e.InputError("complete four-choice public question required")
    stem = row["question"] + ("\n" + row["hint"] if row["hint"] else "")
    return [stem + "\nAnswer: " + answer for answer in row["choices"]]


def validate(x, labels=None, *, width=None):
    if (not isinstance(x, torch.Tensor) or x.device.type != "cpu" or x.dtype != torch.float32
            or x.ndim != 3 or not 1 <= len(x) <= 256 or x.shape[1] != 4
            or x.shape[2] % 2 or not 2 <= x.shape[2] <= 2048
            or x.numel() * x.element_size() > 16 * 1024**2
            or not bool(torch.isfinite(x).all()) or (width is not None and x.shape[2] != width)):
        raise e.InputError("bounded finite four-candidate shared projections required")
    text, image = x.chunk(2, -1)
    if (not torch.equal(image, image[:, :1].expand_as(image))
            or not torch.allclose(text.norm(dim=-1), torch.ones(x.shape[:2]), atol=1e-5, rtol=1e-5)
            or not torch.allclose(image.norm(dim=-1), torch.ones(x.shape[:2]), atol=1e-5, rtol=1e-5)):
        raise e.InputError("unit projected vectors and the SAME image for every option required")
    if labels is not None and (not isinstance(labels, torch.Tensor) or labels.device.type != "cpu"
            or labels.dtype != torch.long or labels.shape != (len(x),)
            or bool(((labels < 0) | (labels >= 4)).any())):
        raise e.InputError("bounded question-level labels required")
    return x.shape[2]


class ChoiceHead(nn.Module):
    """One shared scalar scoring function; parameter count independent of slot index."""
    def __init__(self, width, mode, logit_scale):
        super().__init__()
        e.integer(width, 1, 1024, "projected width")
        if mode not in MODES or type(logit_scale) not in (int, float) or not 0 < logit_scale <= 1000:
            raise e.InputError("fixed candidate mode and finite CLIP scale required")
        self.width, self.mode = width, mode
        self.register_buffer("prior_scale", torch.tensor(float(logit_scale if mode == "visual_prior" else 0)))
        self.head = e.Head(3 * width, 2, "gated", min(8, 3 * width))
        # Preserve cosine prior (or uniform logits) exactly at initialization.
        nn.init.zeros_(self.head.base.weight)
        nn.init.zeros_(self.head.base.bias)
        nn.init.zeros_(self.head.up.weight)

    def forward(self, flat):
        text, image = flat.reshape(-1, 4, 2 * self.width).chunk(2, -1)
        if self.mode == "text_only":
            image = torch.zeros_like(image)
        features = torch.cat([text, text * image, (text - image).abs()], -1)
        residual = self.head(features.reshape(-1, 3 * self.width)).reshape(-1, 4, 2)
        return self.prior_scale * (text * image).sum(-1) + residual[..., 1] - residual[..., 0]


def fit_choices(train, train_labels, calibration, calibration_labels, *, logit_scale, steps=20, seed=20261013):
    """No heldout features/labels. Original fit/AdamW/sample/clipping implementation."""
    width = validate(train, train_labels)
    validate(calibration, calibration_labels, width=width)
    e.integer(steps, 1, 1000, "candidate steps")
    e.integer(seed, 0, 2**63 - 1, "candidate seed")
    if type(logit_scale) not in (int, float) or not 0 < logit_scale <= 1000:
        raise e.InputError("finite CLIP scale required before allocation")
    models, histories, costs = {}, {}, {}
    with torch.random.fork_rng(devices=[]), e.measured() as whole:
        for mode in MODES:
            torch.manual_seed(seed)
            initial = ChoiceHead(width // 2, mode, logit_scale)
            trained, costs[mode] = e.fit(initial, train.flatten(1), train_labels, steps=steps, seed=seed)
            history = []
            for role, model in (("frozen", initial), ("final", trained)):
                model.eval().requires_grad_(False)
                key = f"{mode}:{role}"
                models[key] = model
                with torch.no_grad(), e.measured() as timing:
                    p = model(calibration.flatten(1)).softmax(-1)
                history.append({"key": key, "step": 0 if role == "frozen" else steps,
                    **score(p, calibration_labels), "probabilities": p.tolist(),
                    "model_sha256": e.parameters(model)["sha256"], "calibration_cost": timing})
            histories[mode] = history
        records = [r for h in histories.values() for r in h]
        selected = min(records, key=lambda r: (-r["correct"], r["nll"], r["step"], r["key"]))["key"]
    selection = {"schema": "hepta.choice-content-fusion.v1", "feature_width": width,
        "selected_key": selected, "histories": histories, "training_costs": costs,
        "model_identities": {k: e.parameters(m)["sha256"] for k, m in models.items()},
        "whole_fitting_and_selection": whole, "steps_per_arm": steps,
        "rule": "calibration_correct_desc,nll_asc,earlier_step,lexical_key",
        "same_calibration_selects_arm_and_checkpoint": True, "production_accepted": False}
    return models, selection


@torch.no_grad()
def predict_choices(models, selection, x):
    """One common candidate function; cyclic option probe uses no extra tower calls."""
    validate(x, width=selection["feature_width"])
    keys = {f"{m}:{r}" for m in MODES for r in ("frozen", "final")}
    if (selection.get("schema") != "hepta.choice-content-fusion.v1" or set(models) != keys
            or set(selection["model_identities"]) != keys or selection["selected_key"] not in keys):
        raise e.InputError("complete sealed choice model inventory required")
    for key, model in models.items():
        if (type(model) is not ChoiceHead or model.mode != key.split(":")[0]
                or model.width * 2 != selection["feature_width"]
                or model.training or any(p.requires_grad for p in model.parameters())
                or e.parameters(model)["sha256"] != selection["model_identities"][key]):
            raise e.InputError("candidate parameter or mode drift")
    probabilities, work, probes = {}, {}, {}
    permutation = torch.tensor([1, 2, 3, 0])
    for key, model in models.items():
        with e.measured() as timing:
            logits = model(x.flatten(1))
            probabilities[key] = logits.softmax(-1).tolist()
        work[key] = {**timing, "question_rows": len(x), "candidate_rows": 4 * len(x)}
        with e.measured() as timing:
            changed = model(x[:, permutation].flatten(1))
        expected = logits[:, permutation]
        if not bool(torch.isfinite(logits).all()) or not bool(torch.isfinite(changed).all()):
            raise e.InputError("nonfinite choice prediction")
        probes[key] = {"permutation": permutation.tolist(), "logits": changed.tolist(),
            "max_absolute_error": float((changed - expected).abs().max()),
            "within_tolerance": bool(torch.allclose(changed, expected, atol=1e-6, rtol=1e-5)),
            "original_top_ties": int(((logits == logits.max(-1, keepdim=True).values).sum(-1) > 1).sum()),
            "cost": timing}
    return {"probabilities": probabilities, "inference_costs": work, "option_permutation": probes,
            "selected_key": selection["selected_key"], "production_accepted": False}


def run(root, output, public, cohort, manifest):
    """Same staged public source/CLIP; no new acquisition or answer-text parsing."""
    from experiments.shared_stem_cell import media_execution as media
    output.mkdir(parents=True, exist_ok=False)
    e.write_once(output / "plan.json", {"schema": "hepta.choice-content-study.v1", "manifest": manifest,
        "source_sha256": e.sha(Path(__file__).read_bytes()), "steps": 20,
        "candidate_order_equivariant_scores": True, "permutation_probe_is_feature_only": True,
        "pretrained_backbone_training": False, "production_accepted": False})
    try:
        cases, labels = media.read_cases(root, manifest["dataset"], 4)
        index = {f"scienceqa:{r['source_split']}:{r['source_index']}": r for group in cohort.values() for r in group}
        if set(index) != {c.case_id for c in cases}:
            raise e.InputError("complete public candidate/cohort identity required")
        prompts = []
        for case in cases:
            item = index[case.case_id]
            row = public[item["source_split"]][item["source_index"]]
            from experiments.shared_stem_cell.public_media import prompt, source_image
            if (prompt(row) != case.inputs["text"]
                    or e.sha(source_image(row)) != case.inputs["image"]["sha256"]):
                raise e.InputError("structured public candidate source drift")
            prompts.append(candidate_texts(row))
        input_record = {"case_ids": [c.case_id for c in cases], "texts": prompts,
            "input_digests": [c.input_digest for c in cases], "labels_provided_to_encoder": False}
        e.write_once(output / "inputs.json", input_record)
        with e.measured() as loading:
            towers = media.LocalTowers(root, manifest["models"])
        tokenizer = towers.processors["clip"].tokenizer
        # Every candidate string is preflighted before the first encoder call.
        for texts in prompts:
            for text in texts:
                if len(tokenizer(text, truncation=False)["input_ids"]) > 77:
                    raise e.InputError("candidate context exceeds original CLIP capacity; no truncation")
        with e.measured() as encoding:
            x = torch.stack([towers.encode_choices(texts, c.inputs["image"], root)
                             for c, texts in zip(cases, prompts)])
        scale = float(towers.models["clip"].logit_scale.detach().exp())
        train = [i for i, c in enumerate(cases) if c.split == "train"]
        cal = [i for i, c in enumerate(cases) if c.split == "calibration"]
        heldout = [i for i, c in enumerate(cases) if c.split == "holdout"]
        models, selection = fit_choices(x[train], torch.tensor([labels[cases[i].case_id] for i in train]),
            x[cal], torch.tensor([labels[cases[i].case_id] for i in cal]), logit_scale=scale)
        selection["binding"] = {"models": towers.identities, "dataset": manifest["dataset"],
            "cohort_sha256": e.sha(e.canonical(cohort)), "input_record_sha256": e.sha(e.canonical(input_record)),
            "train_ids": [cases[i].case_id for i in train], "calibration_ids": [cases[i].case_id for i in cal]}
        seal = e.write_once(output / "selection.json", selection)
        prediction = predict_choices(models, e.decode(e.bound_file(output / "selection.json", seal)), x[heldout])
        prediction.update(case_ids=[cases[i].case_id for i in heldout],
                          input_digests=[cases[i].input_digest for i in heldout], selection_sha256=seal)
        towers.close()
        media.read_cases(root, manifest["dataset"], 4)
        pseal = e.write_once(output / "predictions.json", prediction)
        saved = e.decode(e.bound_file(output / "predictions.json", pseal))
        gold = torch.tensor([labels[i] for i in saved["case_ids"]])
        scores = {key: score(torch.tensor(p), gold) for key, p in saved["probabilities"].items()}
        report = {"prediction_sha256": pseal, "selection_sha256": seal, "scores": scores,
            "selected_key": saved["selected_key"], "model_loading": loading, "encoding": encoding,
            "tower_calls": towers.calls, "text_candidate_rows": 4 * len(cases), "image_rows": len(cases),
            "logit_scale": scale, "simulated_towers": towers.simulated,
            "heldout_option_permutation_passed": all(p["within_tolerance"] for p in saved["option_permutation"].values()),
            "independent_evaluation": False, "production_accepted": False}
        e.write_once(output / "report.json", report)
        return report
    except Exception as error:
        e.write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error),
                                               "production_accepted": False})
        raise
