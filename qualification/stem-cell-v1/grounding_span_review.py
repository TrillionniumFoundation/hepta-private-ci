"""Independent stdlib validation of supplied public offsets and V9 span targets.

Reconstructs grammar roles, offset overlap, padding, keys and every target value.
The fast tokenizer itself is not reexecuted; its supplied offsets are validated
against raw public text and token IDs bound to the immutable feature cache.
"""
from hashlib import sha256
import re

from binding_review import _check, _digest, _id

TRAIN = re.compile(r"binding-v4/train/41/(?:[0-9]|[12][0-9]|3[01])/world-[01]|binding-v5/retention-v7-augmentation-[0-7]/1701/(?:[0-9]|[12][0-9]|3[01])/world-[01]")
FRESH = re.compile(r"binding-v5/(?:fresh_combinations|fresh_vocabulary)/2901/(?:[0-9]|[12][0-9]|3[01])/world-[01]")


def grammar_roles(row):
    """Parse all public endpoints without consulting label or support metadata."""
    owners, stores, roles = {}, {}, []
    for text in row["facts"]:
        own = re.fullmatch(r"The ([A-Za-z]+) belongs to ([A-Za-z]+)\.", text)
        store = re.fullmatch(r"([A-Za-z]+) stores all their possessions in the ([A-Za-z]+) box\.", text)
        _check(bool(own or store), "unrecognized controlled public grammar")
        match = own or store
        key, value = match.groups()
        relation = owners if own else stores
        _check(key not in relation, "duplicate public relation")
        relation[key] = value
        kinds = ("object", "person") if own else ("person", "color")
        roles.append(tuple((kind + ":" + match[index], list(match.span(index))) for kind, index in zip(kinds, (1, 2))))
    question = re.fullmatch(r"Where is the ([A-Za-z]+) stored\?", row["question"])
    candidate = re.fullmatch(r"The ([A-Za-z]+) box\.", row["candidate"])
    _check(len(row["facts"]) == 4 and row["sentence_ids"] == [1, 2, 3, 4]
           and row["question_id"] == "0" and row["answer_id"] in ("0", "1")
           and row["source_hash"] == sha256("\n".join(row["facts"]).encode()).hexdigest()
           and len(owners) == len(stores) == 2 and len(set(owners.values())) == 2
           and set(owners.values()) == set(stores) and len(set(stores.values())) == 2
           and question is not None and question[1] in owners and candidate is not None and candidate[1] in stores.values(),
           "complete bijective public roles required")
    return roles, ("object:" + question[1], list(question.span(1))), ("color:" + candidate[1], list(candidate.span(1)))


def span_indices(text, span, alignment, cached_ids):
    _check(alignment["public_text"] == text and alignment["cached_input_ids"] == alignment["tokenizer_input_ids"] == cached_ids
           and alignment["add_special_tokens"] is False and alignment["truncation"] is False,
           "public token alignment differs from immutable cache IDs")
    offsets = alignment["offset_mapping"]
    _check(len(offsets) == len(cached_ids) > 0 and all(isinstance(pair, list) and len(pair) == 2
           and all(type(i) is int for i in pair) and 0 <= pair[0] <= pair[1] <= len(text) for pair in offsets),
           "bounded complete per-token public offsets required")
    start, end = span
    _check(type(start) is type(end) is int and 0 <= start < end <= len(text), "bounded nonempty entity character span required")
    selected = [i for i, (left, right) in enumerate(offsets) if left < end and right > start]
    _check(selected and all(any(offsets[i][0] <= char < offsets[i][1] for i in selected) for char in range(start, end)),
           "entity character coverage incomplete")
    for index in selected:
        left, right = offsets[index]
        _check(not (text[left:min(right, start)] + text[max(left, end):right]).strip(),
               "entity token overlaps other nonwhitespace content")
    return selected


def audit_span_targets(rows, target, cached_tokens, *, role="training"):
    _check(role in ("training", "frozen_diagnostic") and 0 < len(rows) <= 4096,
           "explicit bounded training/frozen-diagnostic target role required")
    shapes, available, parsed = [], [], []
    for row in rows:
        _check(row["source_split"] in (("train",) if role == "training" else ("train", "validation")),
               "target source role not authorized")
        texts = (*row["facts"], row["question"], row["candidate"])
        _check(all(text in cached_tokens for text in texts), "all public target strings must bind to immutable cache")
        lengths = [len(cached_tokens[text]) for text in row["facts"]]
        _check(lengths and min(lengths) > 0 and cached_tokens[row["question"]], "nonempty public evidence/query required")
        chunks = [(min(62, length - start), sentence) for sentence, length in enumerate(lengths) for start in range(0, length, 62)]
        controlled = row["segmentation"] == "synthetic-ownership-storage-v1"
        if controlled:
            pattern = TRAIN if row["source_split"] == "train" else FRESH
            _check(pattern.fullmatch(row["paragraph_id"]) is not None and max(lengths) <= 62,
                   "registered short controlled target source required")
        parsed.append(grammar_roles(row) if controlled else None)
        available.append(controlled)
        shapes.append((chunks, len(cached_tokens[row["question"]]), max(1, len(cached_tokens[row["candidate"]]))))
    facts, width = max(len(s[0]) for s in shapes), max(n for s, _, _ in shapes for n, _ in s)
    questions, candidates, batch = max(s[1] for s in shapes), max(s[2] for s in shapes), len(rows)
    _check(facts <= 256 and max(questions, candidates) <= 1024 and batch * (facts * 2 * width + questions + candidates) <= 16_000_000,
           "bounded target geometry required")
    expected = dict(schema="hepta.grounding.train-spans.v9", role=role, aux_available=available,
        fact_attention_targets=[[[[0.] * width for _ in range(2)] for _ in range(facts)] for _ in rows],
        fact_supervision_mask=[[[False] * 2 for _ in range(facts)] for _ in rows],
        question_attention_targets=[[0.] * questions for _ in rows], question_supervision_mask=list(available),
        candidate_attention_targets=[[0.] * candidates for _ in rows], candidate_supervision_mask=list(available),
        mention_entity_keys=[[[None] * 2 for _ in range(facts)] for _ in rows],
        mention_context_keys=[[[None] * 2 for _ in range(facts)] for _ in rows],
        question_entity_keys=[None] * batch, candidate_entity_keys=[None] * batch,
        question_context_keys=[None] * batch, candidate_context_keys=[None] * batch,
        case_ids=[_id(row) for row in rows], span_records=[], payload_tokens=62,
        target_shapes=dict(fact=[batch, facts, 2, width], question=[batch, questions], candidate=[batch, candidates]),
        natural_auxiliary_targets_invented=False, answer_labels_read=False, support_annotations_read=False,
        trainer_only=role == "training", annotations_authorized_as_model_inputs=False,
        caller_must_enforce_all_models_frozen_and_raw_predictions_first=role == "frozen_diagnostic",
        public_token_alignments={})

    def fill(text, span):
        key = sha256(text.encode()).hexdigest()
        _check(key in target["public_token_alignments"], "public text alignment missing")
        alignment = target["public_token_alignments"][key]
        selected = span_indices(text, span, alignment, cached_tokens[text])
        expected["public_token_alignments"][key] = alignment
        values = [1. / len(selected) if i in selected else 0. for i in range(len(cached_tokens[text]))]
        return key, selected, values

    for index, (row, roles) in enumerate(zip(rows, parsed)):
        if roles is None:
            continue
        fact_roles, question, candidate = roles
        for fact, pair in enumerate(fact_roles):
            for slot, (entity, span) in enumerate(pair):
                text = row["facts"][fact]
                key, selected, values = fill(text, span)
                expected["fact_attention_targets"][index][fact][slot][:len(values)] = values
                expected["fact_supervision_mask"][index][fact][slot] = True
                expected["mention_entity_keys"][index][fact][slot] = entity
                expected["mention_context_keys"][index][fact][slot] = _digest([text, span])
                expected["span_records"].append(dict(row=index, fact=fact, slot=slot, entity_key=entity,
                    character_span=span, token_indices=selected, public_text_sha256=key))
        for name, (entity, span) in (("question", question), ("candidate", candidate)):
            key, selected, values = fill(row[name], span)
            expected[name + "_attention_targets"][index][:len(values)] = values
            expected[name + "_entity_keys"][index] = entity
            expected[name + "_context_keys"][index] = _digest([row[name], span])
            expected["span_records"].append(dict(row=index, role=name, entity_key=entity,
                character_span=span, token_indices=selected, public_text_sha256=key))
    entities = {item["entity_key"] for item in expected["span_records"]}
    expected["canonical_entity_order"] = sorted(entities)
    expected["public_token_alignments_sha256"] = _digest(expected["public_token_alignments"])
    expected["cached_token_bindings_sha256"] = _digest({text: cached_tokens[text] for row in rows for text in (*row["facts"], row["question"], row["candidate"])})
    _check(target == expected, "independently reconstructed complete span targets/roles/keys differ")
    return dict(passed=True, role=role, cases=batch, supervised_cases=sum(available), span_mentions=len(expected["span_records"]),
        public_alignments=len(expected["public_token_alignments"]), target_sha256=_digest(target),
        grammar_char_spans_and_offset_overlap_reconstructed=True, tokenizer_reexecuted=False,
        natural_auxiliary_targets_invented=False)
