"""A separate tiny-decoder mechanism experiment, not natural future evidence."""

import argparse
from pathlib import Path

from evolution_common import digest, retain


def protocol():
    cases = [
        dict(
            case_id=f"edge_{i}",
            hint="warm" if i % 2 == 0 else "cool",
            color=value,
            leaf="color-a" if i % 2 == 0 else "color-b",
        )
        for i, value in enumerate(["red", "blue", "yellow", "green", "orange", "cyan"])
    ]
    return dict(
        schema="hepta.edge-mechanism.protocol.v1",
        seed=24031,
        scope="edge-mechanism-20261024",
        cases=cases,
        source_templates=[
            "What is the hint for {entity}?",
            "Recall the hint of {entity}.",
        ],
        final_template="Give {entity}'s hint.",
        training_templates=[
            "What is the {relation} for {entity}?",
            "Recall the {relation} of {entity}.",
        ],
        cells=["hint", "color-a", "color-b"],
        rank=4,
        steps_per_training=256,
        learning_rate=0.01,
        train_initial_cells=3,
        train_after_withdrawal=1,
        decoder_optimizer_updates=1024,
        router_updates=400,
        source_utility_cases=12,
        final_cases=6,
        arms=[
            "no-edges",
            "fixed",
            "random",
            "learned-next-cell",
            "capability",
            "direct-parameter",
            "exact-source",
        ],
        maximum_calls_per_graph_task=2,
        maximum_total_decoder_queries=122,
        tiny_base=dict(
            architecture="LlamaForCausalLM",
            hidden_size=16,
            intermediate_size=32,
            layers=1,
            heads=2,
            context=256,
            pretrained=False,
        ),
        topology_sequence=[
            "bootstrap-three-cells",
            "split-hint-reuse-by-source-partition",
            "merge-hint-using-already-joint-replayed-checkpoint",
            "rollback-to-split-as-new-generation",
            "rollback-to-merged-as-new-generation",
            "source-utility-measurement",
            "freeze-learned-edge-policy",
            "all-final-arms",
            "withdraw-first-hint-source",
            "reject-old-rollback-and-ancestry",
            "fresh-base-replay-remaining-hints",
            "one-admitted-post-rebuild-read",
        ],
        source_scope="all six stored entities; final uses another wording of the same entities",
        source_utility="exact actual next-cell raw answer and successful source admission; zero for denied/incomplete outcomes",
        causal_limit="raw first-cell output changes next prompt and learned transition features; this does not establish that it is necessary for solving the task",
        strong_controls="metadata can route directly to a supported leaf; exact source can answer without any decoder",
        split_choice="fixed source partition; no claim of learned fission or capacity pressure",
        execution_costs="shared physical training and source matrix counted once; arm marginal and required dependency allocation reported separately",
        final_policy_dispatch="actual live dispatch, never selecting from a precomputed final expert matrix",
        equal_total_cost=False,
        source_overlay_in_parameter_scores=False,
        natural_task_groups=0,
        prospective=False,
        confirmation=False,
        production_accepted=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = protocol()
    retain(args.output, value)
    print(digest(value))
