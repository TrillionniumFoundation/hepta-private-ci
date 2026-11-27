"""Integer-only planning inventory; creates no tensors, data or trained model.

One MAC means one multiply-accumulate, not one CPU instruction or FLOP.
Backward MACs include weight gradients and only learned input gradients.
Bias/nonlinear/loss/optimizer/RNG/IO costs are separate, never free.
"""

import json
from fractions import Fraction


def affine(inputs, outputs, copies=1, learned_inputs=None):
    learned = inputs if learned_inputs is None else learned_inputs
    return {
        "inputs": inputs,
        "outputs": outputs,
        "copies": copies,
        "parameters": (inputs + 1) * outputs,
        "forward_MAC": copies * inputs * outputs,
        "backward_MAC": copies * (inputs + learned) * outputs,
    }


def inventory():
    modules = {
        "C": affine(784, 64, learned_inputs=0),
        "T_initial": affine(64, 32),
        "I_initial": affine(82, 16, 49, learned_inputs=64),
        "text_head": affine(32, 10),
        "image_head": affine(16, 16, 49),
        "qT": affine(42, 16),
        "qI": affine(48, 16, 49, learned_inputs=32),
        "feedback": affine(96, 32),
        "T_update": affine(144, 32),
        "I_update": affine(130, 16, 49, learned_inputs=128),
    }
    policy = {
        "hidden": affine(32, 8, learned_inputs=0),
        "values": affine(8, 3),
    }
    costs = {}
    for direction in ("forward_MAC", "backward_MAC"):
        base = sum(modules[n][direction] for n in (
            "C", "T_initial", "I_initial", "text_head", "image_head"
        ))
        observe = sum(modules[n][direction] for n in ("qT", "qI", "feedback"))
        updates = {
            "T": modules["T_update"][direction] + modules["text_head"][direction],
            "I": modules["I_update"][direction] + modules["image_head"][direction],
        }
        updates["J"] = updates["T"] + updates["I"]
        reobserve = {
            "T": modules["qT"][direction] + modules["feedback"][direction],
            "I": modules["qI"][direction] + modules["feedback"][direction],
            "J": observe,
        }
        costs[direction] = {
            "initial": base,
            "observe": observe,
            "updates": updates,
            "reobserve": reobserve,
            "sequences": {
                a + b: base + observe + updates[a] + reobserve[a] + updates[b]
                for a in "TIJ" for b in "TIJ"
            },
        }
    f, b = costs["forward_MAC"], costs["backward_MAC"]
    totals = {key: f["sequences"][key] + b["sequences"][key]
              for key in f["sequences"]}
    average = Fraction(sum(totals.values()), 9)
    content_p = sum(m["parameters"] for m in modules.values())
    policy_p = sum(m["parameters"] for m in policy.values())
    # Three first-step states share the computed T/I update and their heads.
    # Their feedback shares qT(new)/qI(new), but has three distinct global f.
    all_nine = (f["initial"] + f["observe"] + f["updates"]["J"]
                + modules["qT"]["forward_MAC"] + modules["qI"]["forward_MAC"]
                + 3 * modules["feedback"]["forward_MAC"]
                + 3 * f["updates"]["J"])
    direct = [affine(784, 64), affine(64, 10), affine(64, 784)]
    deep = [affine(784, 320), affine(320, 192), affine(192, 128),
            affine(128, 10), affine(128, 784)]
    # Same-resolution 3x3 convolutions: parameter copies=1, spatial MAC x784.
    cnn_p = (9 + 1) * 4 + (9 * 4 + 1) * 8 + (8 + 1) + (8 * 784 + 1) * 10
    cnn_f = 784 * (9 * 4 + 9 * 4 * 8 + 8) + 8 * 784 * 10
    # FP64 explicit buffer inventory: retained activations for a JJ tape.
    tape_per_row = (784 + 784 + 64 + 32 + 49 * 16 + 10 + 784
                    + 2 * (16 + 49 * 16 + 32 + 32 + 49 * 16 + 10 + 784)
                    + 4 * (784 + 784 + 1))
    concat_per_row = 49 * 82 + 2 * (42 + 49 * 48 + 96 + 144 + 49 * 130)
    bytes_one_tape = 64 * tape_per_row * 8
    concat_bytes = 64 * concat_per_row * 8

    def adam(p, arrays):
        return {"scalar_ops": 13 * p + 4 * arrays, "div_ops": 3 * p + 1,
                "sqrt_ops": p + 1, "pow_ops": 2 * arrays, "compare_ops": 2}

    return {
        "schema": "hepta.fashion-candidate.integer-inventory.v1",
        "scope": "Analytic affine MACs and explicitly listed buffers, no model execution.",
        "content_modules": modules,
        "policy_modules": policy,
        "parameters": {"content": content_p, "policy": policy_p,
                       "total": content_p + policy_p, "parameter_arrays": 24},
        "content_costs": costs,
        "content_forward_backward_MAC_per_image": totals,
        "uniform_nine_sequence_mean_MAC": str(average),
        "policy_MAC_per_row": {key: sum(m[key] for m in policy.values())
                               for key in ("forward_MAC", "backward_MAC")},
        "shared_label_forward_MAC_per_image": {
            "one_J_prefix_three_final_actions": f["sequences"]["JJ"],
            "all_nine_sequences": all_nine,
        },
        "planning_workloads_MAC": {
            "content_40000_fit_4_epochs_3_seeds_uniform_mean": int(average * 40000 * 4 * 3),
            "content_same_workload_JJ_worst": totals["JJ"] * 40000 * 4 * 3,
            "three_actions_512_fit_sources_3_seeds": f["sequences"]["JJ"] * 512 * 3,
            "all_nine_512_fit_sources_3_seeds": all_nine * 512 * 3,
            "all_nine_10000_select_rows_3_seeds_once": all_nine * 10000 * 3,
            "actor_three_OOF_folds_plus_full_256_steps_B64_3_seeds":
                sum(m["forward_MAC"] + m["backward_MAC"] for m in policy.values())
                * 4 * 256 * 64 * 3,
        },
        "static_inventory": {
            "direct_MLP": {"parameters": sum(m["parameters"] for m in direct),
                           "forward_MAC": sum(m["forward_MAC"] for m in direct)},
            "deep_MLP": {"parameters": sum(m["parameters"] for m in deep),
                         "forward_MAC": sum(m["forward_MAC"] for m in deep)},
            "CNN": {"parameters": cnn_p, "forward_MAC": cnn_f},
        },
        "memory_bytes": {
            "weights_FP64": (content_p + policy_p) * 8,
            "weights_grad_Adam_m_v_FP64": (content_p + policy_p) * 8 * 4,
            "B64_explicit_JJ_tape_and_K4_terminal_arrays": bytes_one_tape,
            "B64_all_affine_concat_input_reservation": concat_bytes,
            "same_size_backward_workspace_reservation": bytes_one_tape + concat_bytes,
            "TRAIN_uint8_images": 60000 * 784,
            "TRAIN_float32_images_if_materialized": 60000 * 784 * 4,
            "transport_gray_float32_per_output": 784 * 4,
            "transport_RGB_replication_per_output": 784 * 3 * 4,
        },
        "JJ_forward_non_MAC_inventory_per_image": {
            "tanh_calls": 64 + 32 + 784 + 2 * (16 + 784 + 32 + 32 + 784),
            "softmax_exp_calls": 3 * 10,
            "softmax_max_compare_ops": 3 * 9,
            "softmax_sub_ops": 3 * 10,
            "softmax_sum_add_ops": 3 * 9,
            "softmax_div_ops": 3 * 10,
            "bias_add_ops": 64 + 32 + 784 + 10 + 784 + 2 * (16 + 784 + 32 + 32 + 784 + 10 + 784),
            "residual_add_ops": 3 * 784 + 2 * (32 + 784),
            "mean_qI_add_ops": 2 * (49 - 1) * 16,
            "mean_qI_div_ops": 2 * 16,
            "decoded_mu_clip_values": 3 * 784,
            "terminal_K4_Gaussian_random_variables": 4 * 784,
            "terminal_sample_clip_values": 4 * 784,
            "terminal_sample_multiply_and_add_each": 4 * 784,
            "terminal_MSE_difference_square_each": 4 * 784,
            "terminal_MSE_sum_add_ops": 4 * (784 - 1),
            "terminal_quality_exp_calls": 4,
            "entropic_exp_calls": 4,
            "entropic_log_calls": 1,
            "boundary": "Forward known primitives only; clipping comparisons, RNG backend primitives, anchor/gradient scalar operations and dispatch memory work require implementation-level ledger before fit.",
        },
        "Adam_one_update_existing_inventory_convention": {
            "content": adam(content_p, 20), "policy": adam(policy_p, 4),
            "boundary": "Convention from existing independent learning inventory; not measured hardware instruction counts.",
        },
        "not_in_MAC_total": [
            "tanh and derivatives, softmax, bias/residual/clip/reductions",
            "K4 Gaussian RNG, terminal samples, exp/log risk and gradients",
            "Adam, policy labels/scoring, path selection and input preprocessing",
            "data IO, memory traffic, dispatch/packing, compiler, serialization",
        ],
        "CPU_feasibility": {
            "measured": False,
            "uniform_content_GMAC_per_second_needed_if_entire_1800s_available":
                float(average * 40000 * 4 * 3 / (1800 * 10**9)),
            "warning": "Other costs make the real requirement higher; no throughput promise.",
        },
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2, sort_keys=True))
