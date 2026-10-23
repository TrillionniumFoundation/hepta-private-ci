"""Deterministic exploratory mechanism experiment. Not a confirmatory model run."""
import json
from finite_portfolio import Model, Portfolio, evaluate_exact


def main():
    nominal = Model(common_flip=.18)
    shifted = Model(common_flip=.36)
    results = {
        'schema': 'hepta.ndu.output-portfolio.finite-symbolic.v4',
        'evidence_level': 'exploratory_synthetic_only',
        'four_outputs': ['text-symbol','audio-symbol','image-symbol','video-symbol'],
        'source_correlation': 'hidden-common-flip + independent sensor errors',
        'independent_evaluation': 'enumerated 32 truth/common-cause worlds and 16 public reports',
        'cost_unit': 'declared symbolic units, not physical time, FLOPs or energy',
        'comparisons': {},
        'not_claimed': ['natural multimodal generation','true FBSDE solver',
                        'global learning optimum','independent real training attribution',
                        'real-world distribution-shift robustness','production authorization'],
    }
    for scenario, law in (('nominal',nominal), ('shared_cause_shift',shifted)):
        for mode in ('dynamic','static','myopic'):
            # Under shift, do NOT secretly recalibrate or access true hidden law.
            value = evaluate_exact(Portfolio(nominal), law, mode, 6)
            results['comparisons'][f'{scenario}/{mode}'] = value
    print(json.dumps(results, indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()