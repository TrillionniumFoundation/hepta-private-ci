"""Integer arithmetic on proposed shapes only; no arrays, data or model execution."""

import json
import time
from pathlib import Path


def inventory():
    # Each affine is shared across positions. Positions affect MACs, not weights.
    shapes = {
        "condition": (608, 64), "text_init": (96, 32), "image_init": (66, 32),
        "text_head": (32, 15), "relations": (64, 4), "rgb_head": (32, 48),
        "feedback_text": (83, 32), "feedback_image": (80, 32),
        "feedback_global": (128, 64), "residual": (195, 32),
        "policy_hidden": (65, 16), "policy_head": (16, 3),
    }
    params = {name: source * target + target for name, (source, target) in shapes.items()}

    def affine(name, positions=1):
        source, target = shapes[name]
        return source * target * positions

    heads_t = affine("text_head", 10) + affine("relations", 90)
    heads_i = affine("rgb_head", 64)
    initial = affine("condition") + affine("text_init", 10) + affine("image_init", 64) + heads_t + heads_i
    feedback = affine("feedback_text", 10) + affine("feedback_image", 64) + affine("feedback_global")
    positions = {"T": 10, "I": 64, "J": 74}
    decode = {"T": heads_t, "I": heads_i, "J": heads_t + heads_i}
    updates = {action: feedback + affine("residual", count) + decode[action]
               for action, count in positions.items()}
    policy = affine("policy_hidden") + affine("policy_head")
    # The unchanged modality's local observation is exactly reusable at step2.
    feedback_after = {
        "T": affine("feedback_text", 10) + affine("feedback_global"),
        "I": affine("feedback_image", 64) + affine("feedback_global"),
        "J": feedback,
    }
    feedback_tanh_after = {"T": 384, "I": 2112, "J": 2432}
    sequences = {}
    for first in positions:
        for second in positions:
            actions = first + second
            text_decodes = 1 + sum(action in "TJ" for action in actions)
            image_decodes = 1 + sum(action in "IJ" for action in actions)
            sequences[actions] = {
                "static_optimized_reuse_forward_MACs": initial + updates[first] + updates[second] - feedback + feedback_after[first],
                "dynamic_optimized_same_path_forward_MACs": initial + updates[first] + updates[second] - feedback + feedback_after[first] + 2 * policy,
                "tanh_calls_static_optimized": 2432 + 2432 + feedback_tanh_after[first] + sum(32 * positions[action] for action in actions),
                "static_forward_MACs": initial + sum(updates[action] for action in actions),
                "dynamic_same_path_forward_MACs": initial + sum(updates[action] for action in actions) + 2 * policy,
                "tanh_calls_static": 2432 + 2 * 2432 + sum(32 * positions[action] for action in actions),
                "tanh_calls_dynamic": 2432 + 2 * 2432 + sum(32 * positions[action] for action in actions) + 32,
                "RGB_sigmoid_calls": 3072 * image_decodes,
                "relation_sigmoid_calls": 360 * text_decodes,
                "attribute_softmax_groups": 40 * text_decodes,
                "attribute_exp_calls": 150 * text_decodes,
                "attribute_comparisons": 110 * text_decodes,
                "attribute_subtractions": 150 * text_decodes,
                "attribute_reduction_adds": 110 * text_decodes,
                "attribute_divisions": 150 * text_decodes,
                "residual_scalar_adds": sum(32 * positions[action] for action in actions),
                "RGB_normal_draws_if_sampled_after_every_changed_head": 3072 * image_decodes,
                "attribute_categorical_draws": 40 * text_decodes,
                "relation_uniform_draws": 360 * text_decodes,
                "relation_sampling_comparisons": 360 * text_decodes,
            }
    # Initial state once; feedback once per visited prefix; all three children.
    children = sum(affine("residual", n) + decode[a] for a, n in positions.items())
    all_nine = initial + 4 * feedback + 4 * children
    all_nine_reused = initial + feedback + sum(feedback_after.values()) + 4 * children
    content_params = sum(value for name, value in params.items() if not name.startswith("policy_"))
    policy_params = sum(value for name, value in params.items() if name.startswith("policy_"))
    # Explicit conservative trace storage, not an observed peak or allocator bound.
    # Three content states; two feedbacks plus packed residual input/preactivation.
    state = 320 + 2048 + 150 + 360 + 3072
    saved_trace = 608 + 64 + 3 * state + 2 * (830 + 5120 + 128 + 2368 + 64 + 74 * 195 + 2368)
    B, K = 16, 4
    worst = sequences["JJ"]["dynamic_same_path_forward_MACs"]
    traces = 3 * 3 * 256 * B * K
    shared_K = initial + K * (worst - initial)
    return {
        "schema": "hepta.clevr-conditional-shape-inventory.v1",
        "status": "Analytic hypothetical model only; current task not recommended for training.",
        "no_data_or_model_execution": True,
        "affine_shapes": {name: {"in": shape[0], "out": shape[1], "parameters_including_bias": params[name]} for name, shape in shapes.items()},
        "content_parameters": content_params, "policy_parameters": policy_params,
        "initial_forward_MACs": initial, "paid_feedback_forward_MACs_per_decision": feedback,
        "update_forward_MACs_including_feedback": updates, "policy_MACs_per_decision": policy,
        "feedback_MACs_at_second_step_after_first_action": feedback_after,
        "all_nine_fixed_sequences_shared_prefix_MACs": all_nine,
        "all_nine_fixed_sequences_shared_prefix_and_observation_reuse_MACs": all_nine_reused,
        "all_nine_external_reward_evaluations": 9,
        "reuse_scope": "All methods cache unchanged modality observations and share deterministic initial computation across K draws; unchanged output samples are retained rather than resampled. Dense figures are retained as an explicitly unoptimized implementation inventory, never the required static comparator.",
        "sequences": sequences,
        "linear_operation_convention": "One biased dot of length d uses d multiplies and d additions counting the bias; each listed MAC denotes one nominal pair, not a measured hardware instruction. Nonlinear, RNG, memory, codec and external reward costs are separate.",
        "dynamic_additional_per_trace": {"policy_softmax_groups": 2, "policy_exp_calls": 6, "policy_comparisons": 4, "policy_subtractions": 6, "policy_reduction_adds": 4, "policy_divisions": 6, "policy_categorical_draws": 2},
        "K4_JJ_sampling_and_nonlinear_inventory": {
            "hidden_tanh_calls_with_shared_initial_and_without_policy": 40832,
            "sigmoid_calls_with_shared_initial": 30888,
            "tanh_calls_if_sigmoid_is_half_scaled_tanh_without_policy": 71720,
            "policy_hidden_tanh_calls": 128,
            "attribute_softmax_exp_and_div_calls_each": 1350,
            "policy_softmax_exp_and_div_calls_each": 24,
            "normal_random_variables": 36864,
            "text_and_relation_uniform_variables": 4800,
            "policy_categorical_draws": 8,
            "Box_Muller_if_chosen_log_sqrt_sin_cos_calls_each": 18432,
            "Box_Muller_if_chosen_uniform_variables": 36864,
            "boundary": "Specified stochastic path only; probability computation can be shared while independent samples cannot. RNG backend, clipping/quantization, scalar derivatives and actual primitive prices must be frozen separately, not taken free from old inventories.",
        },
        "Adam_one_update_existing_public_inventory_convention": {
            "content": {"parameter_arrays": 20, "scalar_ops": 13 * content_params + 4 * 20, "div_ops": 3 * content_params + 1, "sqrt_ops": content_params + 1, "pow_ops": 40, "compare_ops": 2},
            "policy": {"parameter_arrays": 4, "scalar_ops": 13 * policy_params + 4 * 4, "div_ops": 3 * policy_params + 1, "sqrt_ops": policy_params + 1, "pow_ops": 8, "compare_ops": 2},
            "scope": "Operator convention from independent/learning.py; not executed hardware operations or a full new loss/critic/observer inventory.",
        },
        "memory_bytes": {
            "content_FP64_parameters_grad_Adam_m_v": 4 * 8 * content_params,
            "policy_FP64_parameters_grad_Adam_m_v": 4 * 8 * policy_params,
            "inference_weights_only_FP64": 8 * (content_params + policy_params),
            "declared_saved_values_per_trace": saved_trace,
            "B16_K4_declared_FP64_trace_arrays": B * K * 8 * saved_trace,
            "B16_K4_trace_arrays_plus_same_size_adjoint_and_all_optimizer_arrays": 2 * B * K * 8 * saved_trace + 4 * 8 * (content_params + policy_params),
            "nine_final_content_states_B16_K4_FP64": 9 * B * K * state * 8,
            "boundary": "Explicit proposed arrays only; not actual RSS, framework tape, BLAS workspace, data cache or a complete peak bound. Nine leaves can be evaluated sequentially; no claim of free recomputation.",
        },
        "illustrative_MAC_budget_arithmetic_not_execution": {
            "seeds": 3, "LR_candidates_per_seed": 3, "updates_per_candidate": 256,
            "source_batch": B, "joint_samples_K": K, "joint_traces": traces,
            "dense_forward_backward_MAC_upper_inventory_three_times_forward": traces * 3 * worst,
            "shared_initial_pass_K4_worst_dynamic_forward_MACs": shared_K,
            "shared_initial_K4_dense_forward_backward_upper_inventory": (traces // K) * 3 * shared_K,
            "training_boundary": "Three dense products per affine when every input adjoint is computed; not a full training cost bound. Activation backward, all sampling, losses, optimizers, observer and policy labels remain additional.",
            "source_screen_512_all_nine_K4_forward_MACs": 512 * K * all_nine,
            "source_screen_512_all_nine_K4_with_both_reuses_MACs": 512 * (initial + K * (all_nine_reused - initial)),
            "screen_three_selected_seeds_MACs": 3 * 512 * (initial + K * (all_nine_reused - initial)),
            "screen_three_selected_seeds_external_reward_calls": 3 * 512 * K * 9,
            "serving_10000_worst_path_MACs": 10000 * worst,
            "serving_10000_per_seed_three_seeds_MACs": 3 * 10000 * worst,
            "known_three_seed_affine_subtotal": (traces // K) * 3 * shared_K + 3 * 512 * (initial + K * (all_nine_reused - initial)) + 3 * 10000 * worst,
        },
        "unpriced_work_never_zero": [
            "Official assets/scene parsing, download, rendering or reference acquisition and compatibility work",
            "RGB-only semantic observer training, qualification, every K-sample reward and nine-branch label",
            "Cross entropy, Gaussian log probability, bounded reward, entropic logsumexp and score-function loss",
            "Nonlinear derivatives, reductions, categorical/normal RNG and per-trace risk weights",
            "Adam state updates, all candidate optimization/selection and useful budget reinvestment",
            "Packing/gather/scatter, materialization, allocator/framework and BLAS workspace",
            "Clipping/quantization, readable text realization, PNG/JSON compression, storage and all serving CPU",
        ],
    }


if __name__ == "__main__":
    start_cpu, start_wall = time.process_time_ns(), time.monotonic_ns()
    result = inventory()
    result["arithmetic_execution"] = {
        "CPU_ns_before_serialization": time.process_time_ns() - start_cpu,
        "wall_ns_before_serialization": time.monotonic_ns() - start_wall,
        "scope": "Pure integer arithmetic only; no matrices allocated, model or data code imported, or timing benchmark performed.",
    }
    out = Path(__file__).with_name("analytic-budget.json")
    with out.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("content_parameters", "policy_parameters", "initial_forward_MACs", "all_nine_fixed_sequences_shared_prefix_MACs", "illustrative_MAC_budget_arithmetic_not_execution")}))
