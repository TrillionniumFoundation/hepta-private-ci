"""Separate exploratory selective-witness fixture, not frozen v4 primary evidence."""
import json
from finite_portfolio import Model, Portfolio, State, evaluate_exact


def main():
    law = Model(common_flip=.03, cost_penalty=.01,
                witness_accuracy=.98, witness_cost=1)
    policy = Portfolio(law)
    root = State((0, 0, 0, 0), budget=6)
    action = policy.solve(root).action
    result = {
        'scope': 'exploratory_synthetic_selective_query',
        'root_action': action,
        'after_feedback_0': policy.solve(root.after(action, 0, 1)).action,
        'after_feedback_1': policy.solve(root.after(action, 1, 1)).action,
        'comparisons': {mode: evaluate_exact(Portfolio(law), law, mode, 6)
                        for mode in ('dynamic', 'static', 'myopic')},
        'no_natural_or_continuation_claim': True,
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
