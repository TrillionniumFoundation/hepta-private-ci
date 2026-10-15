"""Train-only role spans over public controlled text and exact cached BPE IDs.

The returned auxiliary targets/entity keys belong only to the trainer. No answer
labels, proof-support selections, grammar parser or entity keys enter a model.
Natural examples receive zero targets and unavailable supervision flags.
"""
import hashlib
import json
import re

_OWN = re.compile(r"The ([A-Za-z]+) belongs to ([A-Za-z]+)\.")
_STORE = re.compile(r"([A-Za-z]+) stores all their possessions in the ([A-Za-z]+) box\.")
_QUESTION = re.compile(r"Where is the ([A-Za-z]+) stored\?")
_CANDIDATE = re.compile(r"The ([A-Za-z]+) box\.")
_DIAGNOSTIC_ID = re.compile(r"binding-v5/(?:fresh_combinations|fresh_vocabulary)/2901/(?:[0-9]|[12][0-9]|3[01])/world-[01]")
_TRAIN_ID = re.compile(r"binding-v4/train/41/(?:[0-9]|[12][0-9]|3[01])/world-[01]|binding-v5/retention-v7-augmentation-[0-7]/1701/(?:[0-9]|[12][0-9]|3[01])/world-[01]")


def _get(case, name):
    return case[name] if isinstance(case, dict) else getattr(case, name)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _case_id(case):
    return json.dumps([_get(case, name) for name in ("source_split", "paragraph_id", "question_id", "answer_id")],
                      separators=(",", ":"))


def _controlled(case, role):
    facts = tuple(_get(case, "facts"))
    pattern = _TRAIN_ID if _get(case, "source_split") == "train" else _DIAGNOSTIC_ID
    if (pattern.fullmatch(_get(case, "paragraph_id")) is None or len(facts) != 4
            or tuple(_get(case, "sentence_ids")) != (1, 2, 3, 4)
            or _get(case, "question_id") != "0" or _get(case, "answer_id") not in ("0", "1")
            or hashlib.sha256("\n".join(facts).encode()).hexdigest() != _get(case, "source_hash")):
        raise ValueError("registered complete four-fact controlled training source required")
    roles, ownership, storage = [], {}, {}
    for text in facts:
        own, store = _OWN.fullmatch(text), _STORE.fullmatch(text)
        if own:
            obj, person = own.groups()
            if obj in ownership:
                raise ValueError("ambiguous duplicate ownership relation")
            ownership[obj] = person
            roles.append((("object:" + obj, own.span(1)), ("person:" + person, own.span(2))))
        elif store:
            person, color = store.groups()
            if person in storage:
                raise ValueError("ambiguous duplicate storage relation")
            storage[person] = color
            roles.append((("person:" + person, store.span(1)), ("color:" + color, store.span(2))))
        else:
            raise ValueError("unsupported controlled relation grammar")
    question = _QUESTION.fullmatch(_get(case, "question"))
    candidate = _CANDIDATE.fullmatch(_get(case, "candidate"))
    if (len(ownership) != 2 or len(storage) != 2 or len(set(ownership.values())) != 2
            or set(ownership.values()) != set(storage) or len(set(storage.values())) != 2
            or question is None or question[1] not in ownership
            or candidate is None or candidate[1] not in storage.values()):
        raise ValueError("complete bijective relations and unambiguous public query/candidate required")
    return roles, ("object:" + question[1], question.span(1)), ("color:" + candidate[1], candidate.span(1))


def _token_alignment(text, cached_ids, tokenizer):
    if getattr(tokenizer, "is_fast", False) is not True:
        raise ValueError("fast tokenizer with exact public-text offsets required")
    encoded = tokenizer(text, add_special_tokens=False, truncation=False, return_offsets_mapping=True)
    ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
    if list(ids) != list(cached_ids) or len(offsets) != len(ids) or not ids:
        raise ValueError("fast-tokenizer IDs/offsets differ from the exact cached public text")
    if any(not isinstance(pair, (tuple, list)) or len(pair) != 2
           or any(type(i) is not int for i in pair) or not 0 <= pair[0] <= pair[1] <= len(text) for pair in offsets):
        raise ValueError("bounded per-content-token character offsets required")
    return dict(public_text=text, cached_input_ids=list(cached_ids), tokenizer_input_ids=list(ids),
                offset_mapping=[list(pair) for pair in offsets], add_special_tokens=False, truncation=False)


def _span_target(text, span, alignment):
    if (not isinstance(span, (tuple, list)) or len(span) != 2 or any(type(i) is not int for i in span)
            or not 0 <= span[0] < span[1] <= len(text)):
        raise ValueError("one bounded nonempty character span required")
    offsets = alignment["offset_mapping"]
    start, end = span
    selected = [i for i, (left, right) in enumerate(offsets) if left < end and right > start]
    if not selected or any(not any(offsets[i][0] <= char < offsets[i][1] for i in selected)
                           for char in range(start, end)):
        raise ValueError("entity span is not completely covered by content tokens")
    for index in selected:
        left, right = offsets[index]
        extra = text[left:min(right, start)] + text[max(left, end):right]
        if extra.strip():
            raise ValueError("ambiguous token overlaps non-entity non-whitespace characters")
    target = [0.] * len(offsets)
    for index in selected:
        target[index] = 1. / len(selected)
    return target, selected


def token_span_target(text, span, cached_ids, tokenizer):
    """Uniform attention over all overlapping subtokens, allowing leading spaces."""
    return _span_target(text, span, _token_alignment(text, cached_ids, tokenizer))


def make_grounding_targets(cases, cached_tokens, tokenizer, *, payload_tokens=62, role="training"):
    """Return padded trainer-only attention targets plus canonical entity/context keys.

    Controlled roles require one chunk per short fact. Natural multi-chunk facts
    receive no invented spans. ``frozen_diagnostic`` is scorer-only: the caller
    must finish/freeze all models and execute raw predictions before construction.
    This pure data utility cannot establish that chronology itself.
    """
    cases = tuple(cases)
    if role not in ("training", "frozen_diagnostic"):
        raise ValueError("explicit training or frozen_diagnostic role required")
    if not cases or len(cases) > 4096 or type(payload_tokens) is not int or not 1 <= payload_tokens <= 1024:
        raise ValueError("bounded nonempty training minibatch and token chunks required")
    geometry, available, parsed = [], [], []
    for case in cases:
        allowed_splits = ("train",) if role == "training" else ("train", "validation")
        if _get(case, "source_split") not in allowed_splits:
            raise ValueError("grounding role does not authorize this source split")
        texts = (*_get(case, "facts"), _get(case, "question"), _get(case, "candidate"))
        if any(text not in cached_tokens for text in texts):
            raise ValueError("all public strings must already exist in the frozen token cache")
        lengths = [len(cached_tokens[text]) for text in _get(case, "facts")]
        if not lengths or min(lengths) <= 0 or not cached_tokens[_get(case, "question")]:
            raise ValueError("nonempty evidence/question content tokens required")
        chunks = [(min(payload_tokens, length - start), sentence)
                  for sentence, length in enumerate(lengths) for start in range(0, length, payload_tokens)]
        if len(chunks) > 256:
            raise ValueError("fact chunk count exceeds the public feature bound")
        controlled = _get(case, "segmentation") == "synthetic-ownership-storage-v1"
        if controlled and max(lengths) > payload_tokens:
            raise ValueError("controlled grounding requires both endpoints in one short fact chunk")
        parsed.append(_controlled(case, role) if controlled else None)
        available.append(controlled)
        geometry.append((chunks, len(cached_tokens[_get(case, "question")]), max(1, len(cached_tokens[_get(case, "candidate")]))))
    facts = max(len(shape[0]) for shape in geometry)
    width = max(n for shape, _, _ in geometry for n, _ in shape)
    questions, candidates = max(shape[1] for shape in geometry), max(shape[2] for shape in geometry)
    if max(questions, candidates) > 1024:
        raise ValueError("public question/candidate token bound exceeded")
    if len(cases) * (facts * 2 * width + questions + candidates) > 16_000_000:
        raise ValueError("grounding target tensor bound exceeded; reduce minibatch size")
    result = dict(schema="hepta.grounding.train-spans.v9", role=role, aux_available=available,
        fact_attention_targets=[[[[0.] * width for _ in range(2)] for _ in range(facts)] for _ in cases],
        fact_supervision_mask=[[[False] * 2 for _ in range(facts)] for _ in cases],
        question_attention_targets=[[0.] * questions for _ in cases], question_supervision_mask=list(available),
        candidate_attention_targets=[[0.] * candidates for _ in cases], candidate_supervision_mask=list(available),
        mention_entity_keys=[[[None] * 2 for _ in range(facts)] for _ in cases],
        mention_context_keys=[[[None] * 2 for _ in range(facts)] for _ in cases],
        question_entity_keys=[None] * len(cases), candidate_entity_keys=[None] * len(cases),
        question_context_keys=[None] * len(cases), candidate_context_keys=[None] * len(cases),
        case_ids=[_case_id(case) for case in cases], span_records=[], payload_tokens=payload_tokens,
        target_shapes=dict(fact=[len(cases), facts, 2, width], question=[len(cases), questions],
                           candidate=[len(cases), candidates]),
        natural_auxiliary_targets_invented=False, answer_labels_read=False, support_annotations_read=False,
        trainer_only=role == "training", annotations_authorized_as_model_inputs=False,
        caller_must_enforce_all_models_frozen_and_raw_predictions_first=role == "frozen_diagnostic",
        public_token_alignments={})

    def target_for(text, span):
        key = hashlib.sha256(text.encode()).hexdigest()
        if key not in result["public_token_alignments"]:
            result["public_token_alignments"][key] = _token_alignment(text, cached_tokens[text], tokenizer)
        return _span_target(text, span, result["public_token_alignments"][key])
    for row, (case, roles) in enumerate(zip(cases, parsed)):
        if roles is None:
            continue
        facts_roles, question_role, candidate_role = roles
        for fact, role_pair in enumerate(facts_roles):
            text = _get(case, "facts")[fact]
            for slot, (entity, span) in enumerate(role_pair):
                target, indices = target_for(text, span)
                result["fact_attention_targets"][row][fact][slot][:len(target)] = target
                result["fact_supervision_mask"][row][fact][slot] = True
                result["mention_entity_keys"][row][fact][slot] = entity
                result["mention_context_keys"][row][fact][slot] = _sha([text, span])
                result["span_records"].append(dict(row=row, fact=fact, slot=slot, entity_key=entity,
                    character_span=list(span), token_indices=indices, public_text_sha256=hashlib.sha256(text.encode()).hexdigest()))
        for name, (entity, span) in (("question", question_role), ("candidate", candidate_role)):
            text = _get(case, name)
            target, indices = target_for(text, span)
            result[name + "_attention_targets"][row][:len(target)] = target
            result[name + "_entity_keys"][row] = entity
            result[name + "_context_keys"][row] = _sha([text, span])
            result["span_records"].append(dict(row=row, role=name, entity_key=entity,
                character_span=list(span), token_indices=indices, public_text_sha256=hashlib.sha256(text.encode()).hexdigest()))
    entities = {entity for row in result["mention_entity_keys"] for fact in row for entity in fact if entity is not None}
    entities.update(entity for key in ("question_entity_keys", "candidate_entity_keys") for entity in result[key] if entity is not None)
    result["canonical_entity_order"] = sorted(entities)
    result["public_token_alignments_sha256"] = _sha(result["public_token_alignments"])
    result["cached_token_bindings_sha256"] = _sha({text: list(cached_tokens[text])
        for case in cases for text in (*_get(case, "facts"), _get(case, "question"), _get(case, "candidate"))})
    return result


def grounding_from_bank(cases, bank, *, role="training"):
    return make_grounding_targets(cases, bank.tokens, bank.encoder.tokenizer, payload_tokens=bank.payload_tokens, role=role)
