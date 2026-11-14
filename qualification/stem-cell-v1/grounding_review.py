"""Independent stdlib V9 auxiliary replay, with explicit full/compact coverage.

Compact updates authenticate selected-probability span CE and recorded scalar
contrastive reductions. Only fixed full observations rederive vectors, duplicate
means, normalization, cosine scores, masks and logsumexp. No network is rerun.
"""
from collections import defaultdict
from hashlib import sha256
import math
import struct

from binding_review import _check, _digest
from retention_v7_review import same

ARMS = ("latent_chain", "grounded_chain", "grounded_reset", "latent_reset")


def logsumexp(values):
    _check(values and all(math.isfinite(v) for v in values), "nonempty finite logsumexp inputs required")
    peak = max(values)
    return peak + math.log(sum(math.exp(v - peak) for v in values))


def flatten(value):
    if isinstance(value, list):
        return [v for item in value for v in flatten(item)]
    return [value]


def nested(value, address):
    for index in address:
        value = value[index]
    return value


def probability(value):
    _check(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1,
           "finite saved probability in [0,1] required")
    return value


def fp32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def mention_spec(target, indices):
    """Reconstruct trainer flattening and context identities from bound targets."""
    result = []
    for role in ("fact", "question", "candidate"):
        for batch_row, source_row in enumerate(indices):
            if role == "fact":
                for fact, pair in enumerate(target["fact_supervision_mask"][source_row]):
                    for slot, active in enumerate(pair):
                        if active:
                            result.append(dict(role=role, address=[batch_row, fact, slot], source=source_row,
                                entity=target["mention_entity_keys"][source_row][fact][slot],
                                context=target["mention_context_keys"][source_row][fact][slot],
                                target=target["fact_attention_targets"][source_row][fact][slot]))
            elif target[role + "_supervision_mask"][source_row]:
                result.append(dict(role=role, address=[batch_row], source=source_row,
                    entity=target[role + "_entity_keys"][source_row], context=target[role + "_context_keys"][source_row],
                    target=target[role + "_attention_targets"][source_row]))
    return result


def context_spec(mentions):
    groups, owners = defaultdict(list), {}
    for index, mention in enumerate(mentions):
        context, entity = mention["context"], mention["entity"]
        _check(isinstance(context, str) and len(context) == 64 and isinstance(entity, str)
               and (context not in owners or owners[context] == entity), "one typed canonical entity per public context required")
        owners[context] = entity
        groups[(context, entity)].append(index)
    keys = sorted(groups)
    eligible = [[j for j in range(len(keys)) if i != j] for i in range(len(keys))]
    positive = [[j for j in eligible[i] if keys[j][1] == keys[i][1]] for i in range(len(keys))]
    chosen = [i for i in range(len(keys)) if positive[i] and len(positive[i]) < len(eligible[i])]
    return groups, keys, eligible, positive, chosen


def audit_auxiliary(aux, target=None, indices=None, *, full=False, target_sha256=None):
    if target is None:
        _check(aux["auxiliary_available"] is False and aux["span_count"] == 0
               and aux["span_loss"] == aux["contrastive"]["loss"] == 0.
               and aux["span_mention_ce"] == aux["span_selected_probabilities"] == aux["span_token_counts"] == []
               and aux["contrastive"]["retrieval_correct"] == aux["contrastive"]["retrieval_queries"] == 0,
               "natural updates must not invent auxiliary supervision")
        return dict(passed=True, span_loss=0., contrastive_loss=0., span_mentions=0, full_dot_recomputed=False)
    _check(aux["auxiliary_available"] is True and aux["source_targets_sha256"] == (target_sha256 or _digest(target)), "auxiliary target source changed")
    _check(aux["span_probability_floor"] == 1e-9
           and aux["span_reduction"] == "mean_all_supervised_mentions_including_context_duplicates", "span floor/reduction policy changed")
    mentions = mention_spec(target, indices)
    _check(aux["span_count"] == len(mentions) == len(aux["span_mention_ce"])
           == len(aux["span_selected_probabilities"]) == len(aux["span_token_counts"]), "complete selected span mention coverage required")
    terms = []
    for mention, saved, probabilities, count in zip(mentions, aux["span_mention_ce"], aux["span_selected_probabilities"], aux["span_token_counts"]):
        weights = [fp32(weight) for weight in mention["target"] if weight > 0]
        _check(type(count) is int and count == len(weights) == len(probabilities) and count > 0, "span token counts differ from immutable targets")
        for value in probabilities:
            probability(value)
        expected = -sum(weight * math.log(max(p, 1e-9)) for weight, p in zip(weights, probabilities))
        same(saved, expected, "selected-probability span CE mismatch")
        terms.append(expected)
    span = sum(terms) / len(terms) if terms else 0.
    same(aux["span_loss"], span, "span mention mean reduction mismatch")
    groups, keys, eligible, positive, chosen = context_spec(mentions)
    contrastive = aux["contrastive"]
    _check(contrastive["temperature"] == .1 and contrastive["normalization_epsilon"] == 1e-8
           and contrastive["reduction"] == "mean_logsumexp_eligible_minus_logsumexp_positive_mass"
           and contrastive["negative_types"] == "all_other_canonical_entities_including_other_types"
           and contrastive["duplicate_reduction"] == "mean_then_L2_normalize"
           and contrastive["queries_require_positive_and_negative"] is True,
           "registered typed-context contrastive objective changed")
    _check(contrastive["raw_mentions"] == len(mentions) and contrastive["unique_contexts"] == len(keys)
           and contrastive["duplicate_mentions"] == len(mentions) - len(keys)
           and contrastive["context_identity_sha256"] == _digest([[c, e, len(groups[(c, e)])] for c, e in keys])
           and contrastive["query_indices"] == chosen
           and contrastive["positive_counts"] == [len(positive[i]) for i in chosen]
           and contrastive["negative_counts"] == [len(eligible[i]) - len(positive[i]) for i in chosen],
           "context deduplication, positive mask or negative eligibility changed")
    numerator, denominator = contrastive["numerator_logsumexp"], contrastive["denominator_logsumexp"]
    _check(len(numerator) == len(denominator) == len(chosen) and all(type(v) in (int, float) and math.isfinite(v)
           for v in numerator + denominator) and all(d + 2e-6 >= n for n, d in zip(numerator, denominator)),
           "finite aligned positive/eligible logsumexp reductions required")
    alignment = sum(d - n for n, d in zip(numerator, denominator)) / len(chosen) if chosen else 0.
    same(contrastive["loss"], alignment, "contrastive query mean reduction mismatch")
    _check(type(contrastive["retrieval_correct"]) is int and contrastive["retrieval_queries"] == len(chosen)
           and 0 <= contrastive["retrieval_correct"] <= len(chosen), "retrieval count bounds/query coverage changed")
    report = dict(passed=True, span_loss=span, contrastive_loss=alignment, span_mentions=len(mentions),
        unique_contexts=len(keys), contrastive_queries=len(chosen), full_dot_recomputed=False,
        scope="all_saved_selected_span_probabilities_and_scalar_contrastive_reductions")
    if full:
        report.update(audit_full_auxiliary(aux, target, indices, mentions, (groups, keys, eligible, positive, chosen)))
    return report


def audit_full_auxiliary(aux, target, indices, mentions, context):
    groups, keys, eligible, positive, chosen = context
    _check(aux["slot_addresses"] == [[m["role"], *m["address"]] for m in mentions], "full auxiliary slot address order changed")
    text_keys = {(r["row"], r.get("role", "fact"), r.get("fact"), r.get("slot")): r["public_text_sha256"]
                 for r in target["span_records"]}
    for role in ("fact", "question", "candidate"):
        attention, gold = aux["attention_distributions"][role], aux["attention_targets"][role]
        mask, valid = aux["supervision_masks"][role], aux["public_token_masks"][role]
        expected_mask = [target[role + "_supervision_mask"][i] for i in indices]
        _check(mask == expected_mask and len(attention) == len(gold) == len(valid) == len(indices), "full attention supervision or public batch shape changed")
        _check(all(type(v) is bool for v in flatten(valid)), "boolean full public token masks required")
    for index, mention in enumerate(mentions):
        role, address = mention["role"], mention["address"]
        attention = nested(aux["attention_distributions"][role], address)
        gold = nested(aux["attention_targets"][role], address)
        valid_address = address[:2] + [0] if role == "fact" else address
        valid = nested(aux["public_token_masks"][role], valid_address)
        text_key = text_keys[(mention["source"], role, address[1] if role == "fact" else None,
                              address[2] if role == "fact" else None)]
        content = len(target["public_token_alignments"][text_key]["cached_input_ids"])
        _check(content <= len(valid) and valid == [True] * content + [False] * (len(valid) - content),
               "full public mask differs from immutable cached token geometry")
        _check(len(attention) == len(gold) == len(valid) and gold == [fp32(v) for v in mention["target"][:len(gold)]]
               and not any(mention["target"][len(gold):]), "full target padding/cropping changed")
        for p in attention:
            probability(p)
        same(sum(attention), 1., "full supervised attention must normalize", atol=2e-5, rtol=2e-5)
        _check(all(not (p or g) or active for p, g, active in zip(attention, gold, valid)), "attention/target entered public padding")
        selected = [p for p, g in zip(attention, gold) if g > 0]
        _check(selected == aux["span_selected_probabilities"][index], "compact selected span probabilities differ from full attention")
    contrastive = aux["contrastive"]
    vectors = contrastive["raw_mention_vectors"]
    _check(len(vectors) == len(mentions) and all(len(v) == 32 and all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 1.000001 for x in v) for v in vectors),
           "complete finite bounded 32d raw metric mention vectors required")
    _check(all(sum(x * x for x in vector) <= 1. + 2e-5 for vector in vectors),
           "epsilon-normalized raw mention address norm exceeds one")
    _check(contrastive["mention_entity_keys"] == [m["entity"] for m in mentions]
           and contrastive["mention_context_keys"] == [m["context"] for m in mentions]
           and contrastive["unique_context_keys"] == [c for c, _ in keys]
           and contrastive["unique_entity_keys"] == [e for _, e in keys]
           and contrastive["duplicate_counts"] == [len(groups[key]) for key in keys], "full vector/public identity binding changed")
    means = [[sum(vectors[i][axis] for i in groups[key]) / len(groups[key]) for axis in range(32)] for key in keys]
    normalized = [[x / max(math.sqrt(sum(v * v for v in mean)), 1e-8) for x in mean] for mean in means]
    for field, expected in (("context_mean_vectors", means), ("normalized_context_vectors", normalized)):
        _check(len(contrastive[field]) == len(expected) and all(len(row) == 32 for row in contrastive[field]), "full context vector geometry changed")
        for actual, wanted in zip(flatten(contrastive[field]), flatten(expected)):
            same(actual, wanted, "full duplicate mean/normalization mismatch", atol=2e-6, rtol=2e-5)
    scores = [[sum(a * b for a, b in zip(left, right)) / .1 for right in normalized] for left in normalized]
    low, high, ambiguous = 0, 0, 0
    for position, i in enumerate(chosen):
        same(contrastive["numerator_logsumexp"][position], logsumexp([scores[i][j] for j in positive[i]]), "full positive cosine/logsumexp mismatch", atol=1e-5, rtol=2e-5)
        same(contrastive["denominator_logsumexp"][position], logsumexp([scores[i][j] for j in eligible[i]]), "full eligible cosine/logsumexp mismatch", atol=1e-5, rtol=2e-5)
        peak = max(scores[i][j] for j in eligible[i])
        outcomes = {keys[i][1] == keys[j][1] for j in eligible[i] if peak - scores[i][j] <= 2e-5}
        low += int(outcomes == {True})
        high += int(True in outcomes)
        ambiguous += int(len(outcomes) > 1)
    _check(low <= contrastive["retrieval_correct"] <= high, "full nearest-context retrieval outside numerical tie bounds")
    return dict(full_dot_recomputed=True, scope="fixed_full_raw_vectors_attention_masks_targets_dedup_mean_cosine_logsumexp",
        retrieval_correct_recomputed_bounds=[low, high], retrieval_numerically_ambiguous_queries=ambiguous,
        retrieval_tie_score_tolerance=2e-5, independent_neural_execution=False)


def audit_graph_trace(observation, target, indices):
    """Replay graph attention/frontier from saved public metric addresses only."""
    mentions = mention_spec(target, indices)
    vectors = observation["contrastive"]["raw_mention_vectors"]
    addresses = {(m["role"], *m["address"]): vector for m, vector in zip(mentions, vectors)}
    depth, reset = observation["graph_depth"], observation["graph_reset"]
    _check(depth == 2 and type(reset) is bool and len(observation["graph_states"]) == len(observation["graph_fact_attentions"]) == depth,
           "two-hop graph trace policy changed")
    states = [addresses[("question", i)] for i in range(len(indices))]
    for hop in range(depth):
        for row in range(len(indices)):
            valid = [any(mask[0]) for mask in observation["public_token_masks"]["fact"][row]]
            previous = addresses[("question", row)] if reset else states[row]
            keys = [addresses[("fact", row, fact, 0)] for fact in range(len(valid))]
            values = [addresses[("fact", row, fact, 1)] for fact in range(len(valid))]
            scores = [sum(a * b for a, b in zip(key, previous)) * math.sqrt(32) for key in keys]
            peak = max(score for score, active in zip(scores, valid) if active)
            weights = [math.exp(score - peak) if active else 0. for score, active in zip(scores, valid)]
            total = sum(weights)
            weights = [value / total for value in weights]
            value = [sum(weight * payload[axis] for weight, payload in zip(weights, values)) for axis in range(32)]
            norm = max(math.sqrt(sum(v * v for v in value)), 1e-8)
            state = [v / norm for v in value]
            actual_attention, actual_state = observation["graph_fact_attentions"][hop][row], observation["graph_states"][hop][row]
            _check(len(actual_attention) == len(weights) and len(actual_state) == 32, "graph trace attention/frontier geometry changed")
            for actual, expected in zip(actual_attention, weights):
                same(actual, expected, "graph source attention replay mismatch", atol=1e-5, rtol=2e-5)
            for actual, expected in zip(actual_state, state):
                same(actual, expected, "graph normalized frontier replay mismatch", atol=2e-5, rtol=2e-5)
            states[row] = state
    return dict(saved_address_graph_walk_recomputed=True, graph_hops=depth, graph_reset=reset,
                old_reader_and_logit_head_neurally_reexecuted=False)
