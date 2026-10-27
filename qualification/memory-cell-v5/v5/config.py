"""Bounded candidates and selection rule, declared before development fitting."""


FEATURES = {
    "word": {"analyzer": "word", "ngram_range": [1, 3], "max_features": 12000},
    "char": {"analyzer": "char", "ngram_range": [3, 5], "max_features": 12000},
    "char_small": {"analyzer": "char", "ngram_range": [3, 5], "max_features": 4096},
    "unigram_small": {"analyzer": "word", "ngram_range": [1, 1], "max_features": 2048},
}
BASE_CANDIDATES = (
    {"name": "word-lr-c1", "features": ["word"], "learner": "logistic", "C": 1.0},
    {"name": "word-lr-c4", "features": ["word"], "learner": "logistic", "C": 4.0},
    {"name": "mixed-svm-c0.5", "features": ["word", "char"], "learner": "linear_svm", "C": 0.5},
    {"name": "mixed-svm-c2", "features": ["word", "char"], "learner": "linear_svm", "C": 2.0},
    {"name": "char4096-lr-c4", "features": ["char_small"], "learner": "logistic", "C": 4.0},
    {"name": "unigram2048-lr-c4", "features": ["unigram_small"], "learner": "logistic", "C": 4.0},
)
SUBCLASS_CANDIDATES = (
    {"name": "word-lr-c4-negative-families", "features": ["word"], "learner": "logistic", "C": 4.0, "negative_subclasses": True},
    {"name": "mixed-svm-c2-negative-families", "features": ["word", "char"], "learner": "linear_svm", "C": 2.0, "negative_subclasses": True},
)
CANDIDATES = (*BASE_CANDIDATES, *SUBCLASS_CANDIDATES)
NEGATIVE_TRAINING_FAMILIES = (
    "different-window-or-alignment",
    "generated-ordered-operand-contrast",
    "manual-near-ood",
    "unsupported-statistic-or-output",
    "wrong-address",
)
DEFAULT_CONFIG = {
    "schema": "memory-cell-v5.routing-config.v1",
    "candidates": list(CANDIDATES),
    "features": FEATURES,
    "negative_subclass_revision": {
        "name": "V5b",
        "families": list(NEGATIVE_TRAINING_FAMILIES),
        "taxonomy_source": "existing V5a training-row family metadata; no new-held fields read",
        "canonical_score_mapping": "Keep six positive scores; take maximum over learned negative-subclass scores for the unified reject score. This preserves the argmax class decision after subclass-to-reject mapping.",
        "score_scope": "Softmax after max-negative mapping is a normalized decision score, not a calibrated probability.",
        "training_weight_policy": "Preserve the original seven-class balanced per-example weights: every negative subclass uses the original unified-reject sample weight. Do not silently raise total negative mass by balancing eleven classes.",
        "additional_candidates": 2,
        "prior_six_candidate_development_retained": True,
    },
    "logistic_solver": "saga",
    "solver_max_iter": 2000,
    "solver_tolerance": 1e-5,
    "class_weight": "balanced",
    "confidence_grid": [0.0, 0.25, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995],
    "margin_grid": [0.0, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8],
    "minimum_correct_known_coverage": 0.8,
    "maximum_ood_false_accept": 0.05,
    "selection_rule": (
        "Among selection risk-feasible candidate/calibration pairs, maximize correctly "
        "accepted known count, then minimize accepted wrong known, OOD false accepts, "
        "actual serialized selected-state bytes, candidate name, confidence, margin. "
        "Coverage >=0.8 remains a separate mandatory gate. Include explicit reject-all "
        "fallback. Development diagnostic results never select a candidate."
    ),
    "score_semantics": (
        "Softmax of learned linear scores. Logistic scores are multinomial logits; "
        "SVM softmax scores are normalized decision scores, not calibrated probabilities."
    ),
    "seeds": [1019, 1021, 1031, 1033, 1039],
    "no_pretrained_encoder": True,
    "training_data_kind": "author-written synthetic English plus explicitly generated training combinations",
    "independent_language_unit": "authored query template, not slot repetitions or training seeds",
}
