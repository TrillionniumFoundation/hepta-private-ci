"""Independent stdlib fixtures for V9 spans and compact/full auxiliary evidence."""
import copy
from hashlib import sha256
import math
import struct
import unittest

from binding_review import _digest, _id
from grounding_review import audit_auxiliary, audit_graph_trace
from grounding_span_review import audit_span_targets


def fixture():
    rows = []
    for world in (0, 1):
        facts = [f"The coin belongs to {('Ada', 'Ben')[world]}.", f"The bead belongs to {('Ben', 'Ada')[world]}.",
                 "Ada stores all their possessions in the blue box.", "Ben stores all their possessions in the green box."]
        for answer in (0, 1):
            rows.append(dict(source_split="train", paragraph_id=f"binding-v4/train/41/0/world-{world}",
                question_id="0", answer_id=str(answer), facts=facts, sentence_ids=[1, 2, 3, 4],
                question="Where is the coin stored?", candidate=f"The {('blue', 'green')[answer]} box.",
                source_hash=sha256("\n".join(facts).encode()).hexdigest(), label=int(answer == world),
                evidence_sentence_indices=[1, 3 + world], segmentation="synthetic-ownership-storage-v1"))
    tokens = {text: [ord(c) + 1 for c in text] for row in rows for text in (*row["facts"], row["question"], row["candidate"])}
    b, f, width = 4, 4, max(len(text) for row in rows for text in row["facts"])
    q, c = len(rows[0]["question"]), max(len(row["candidate"]) for row in rows)
    target = dict(schema="hepta.grounding.train-spans.v9", role="training", aux_available=[True]*b,
        fact_attention_targets=[[[[0.]*width for _ in range(2)] for _ in range(f)] for _ in rows],
        fact_supervision_mask=[[[True]*2 for _ in range(f)] for _ in rows],
        question_attention_targets=[[0.]*q for _ in rows], question_supervision_mask=[True]*b,
        candidate_attention_targets=[[0.]*c for _ in rows], candidate_supervision_mask=[True]*b,
        mention_entity_keys=[[[None]*2 for _ in range(f)] for _ in rows], mention_context_keys=[[[None]*2 for _ in range(f)] for _ in rows],
        question_entity_keys=[None]*b, candidate_entity_keys=[None]*b, question_context_keys=[None]*b, candidate_context_keys=[None]*b,
        case_ids=[_id(row) for row in rows], span_records=[], payload_tokens=62,
        target_shapes=dict(fact=[b,f,2,width], question=[b,q], candidate=[b,c]),
        natural_auxiliary_targets_invented=False, answer_labels_read=False, support_annotations_read=False,
        trainer_only=True, annotations_authorized_as_model_inputs=False,
        caller_must_enforce_all_models_frozen_and_raw_predictions_first=False, public_token_alignments={})
    for i, row in enumerate(rows):
        word_pairs = [("object", "coin", "person", ("Ada", "Ben")[i//2]),
                      ("object", "bead", "person", ("Ben", "Ada")[i//2]),
                      ("person", "Ada", "color", "blue"), ("person", "Ben", "color", "green")]
        all_mentions = [("fact", j, slot, kind, word) for j, pair in enumerate(word_pairs)
                        for slot, (kind, word) in enumerate(((pair[0], pair[1]), (pair[2], pair[3])))]
        all_mentions += [("question", None, None, "object", "coin"), ("candidate", None, None, "color", ("blue", "green")[i%2])]
        for role, fact, slot, kind, word in all_mentions:
            text = row["facts"][fact] if role == "fact" else row[role]
            start = text.index(word)
            span, key = [start, start + len(word)], sha256(text.encode()).hexdigest()
            target["public_token_alignments"][key] = dict(public_text=text, cached_input_ids=tokens[text], tokenizer_input_ids=tokens[text],
                offset_mapping=[[j,j+1] for j in range(len(text))], add_special_tokens=False, truncation=False)
            selected = list(range(*span))
            gold = [1./len(word) if j in selected else 0. for j in range(len(text))]
            entity, context = kind + ":" + word, _digest([text, span])
            item = dict(row=i, entity_key=entity, character_span=span, token_indices=selected, public_text_sha256=key)
            if role == "fact":
                target["fact_attention_targets"][i][fact][slot][:len(gold)] = gold
                target["mention_entity_keys"][i][fact][slot], target["mention_context_keys"][i][fact][slot] = entity, context
                item.update(fact=fact, slot=slot)
            else:
                target[role+"_attention_targets"][i][:len(gold)] = gold
                target[role+"_entity_keys"][i], target[role+"_context_keys"][i] = entity, context
                item["role"] = role
            target["span_records"].append(item)
    target["canonical_entity_order"] = sorted({r["entity_key"] for r in target["span_records"]})
    target["public_token_alignments_sha256"] = _digest(target["public_token_alignments"])
    target["cached_token_bindings_sha256"] = _digest(tokens)
    return rows, tokens, target


def full_aux_fixture():
    rows, tokens, target = fixture()
    entities, contexts, addresses, probabilities, terms, counts, raw_vectors = [], [], [], [], [], [], []
    names = target["canonical_entity_order"]
    attention, gold, supervised, valid = {}, {}, {}, {}
    for role in ("fact", "question", "candidate"):
        def rounded(value):
            return [rounded(v) for v in value] if isinstance(value,list) else struct.unpack("<f",struct.pack("<f",value))[0]
        gold[role] = rounded(target[role+"_attention_targets"])
        supervised[role] = copy.deepcopy(target[role+"_supervision_mask"])
        attention[role], valid[role] = [], []
        for i, row in enumerate(rows):
            if role == "fact":
                width = len(gold[role][i][0][0])
                lengths = [len(tokens[t]) for t in row["facts"]]
                distributions = [[[1./n]*n + [0.]*(width-n) for _ in range(2)] for n in lengths]
                attention[role].append(distributions)
                valid[role].append([[[True]*n+[False]*(width-n)] for n in lengths])
                locations = [(j,k) for j in range(4) for k in range(2)]
            else:
                width, n = len(gold[role][i]), len(tokens[row[role]])
                attention[role].append([1./n]*n + [0.]*(width-n))
                valid[role].append([True]*n+[False]*(width-n))
                locations = [()]
            for location in locations:
                address = [i,*location]
                if role == "fact":
                    j,k = location
                    entity, context = target["mention_entity_keys"][i][j][k], target["mention_context_keys"][i][j][k]
                    a,t = attention[role][i][j][k], gold[role][i][j][k]
                else:
                    entity, context = target[role+"_entity_keys"][i], target[role+"_context_keys"][i]
                    a,t = attention[role][i], gold[role][i]
                selected = [p for p,g in zip(a,t) if g > 0]
                probabilities.append(selected)
                counts.append(len(selected))
                terms.append(-sum(g*math.log(max(p,1e-9)) for p,g in zip(a,t)))
                entities.append(entity); contexts.append(context); addresses.append([role,*address])
                raw_vectors.append([float(axis == names.index(entity)) for axis in range(32)])
    groups = {}
    for index,pair in enumerate(zip(contexts,entities)):
        groups.setdefault(pair,[]).append(index)
    keys = sorted(groups)
    positive = [[j for j,k in enumerate(keys) if j != i and k[1] == key[1]] for i,key in enumerate(keys)]
    negatives = [len(keys)-1-len(p) for p in positive]
    chosen = [i for i in range(len(keys)) if positive[i] and negatives[i]]
    numerators = [10. + math.log(len(positive[i])) for i in chosen]
    denominators = [math.log(len(positive[i])*math.exp(10.)+negatives[i]) for i in chosen]
    means = [raw_vectors[groups[key][0]] for key in keys]
    contrastive = dict(temperature=.1, normalization_epsilon=1e-8,
        reduction="mean_logsumexp_eligible_minus_logsumexp_positive_mass",
        negative_types="all_other_canonical_entities_including_other_types", duplicate_reduction="mean_then_L2_normalize",
        queries_require_positive_and_negative=True,raw_mentions=len(entities),unique_contexts=len(keys),duplicate_mentions=len(entities)-len(keys),
        context_identity_sha256=_digest([[c,e,len(groups[(c,e)])] for c,e in keys]), query_indices=chosen,
        positive_counts=[len(positive[i]) for i in chosen], negative_counts=[negatives[i] for i in chosen],
        numerator_logsumexp=numerators,denominator_logsumexp=denominators,retrieval_correct=len(chosen),retrieval_queries=len(chosen),
        loss=sum(d-n for n,d in zip(numerators,denominators))/len(chosen),raw_mention_vectors=raw_vectors,
        mention_entity_keys=entities,mention_context_keys=contexts,unique_context_keys=[c for c,e in keys],unique_entity_keys=[e for c,e in keys],
        duplicate_counts=[len(groups[k]) for k in keys],context_mean_vectors=means,normalized_context_vectors=means)
    aux = dict(auxiliary_available=True,source_targets_sha256=_digest(target),span_loss=sum(terms)/len(terms),span_count=len(terms),
        span_mention_ce=terms,span_selected_probabilities=probabilities,span_token_counts=counts,contrastive=contrastive,
        span_probability_floor=1e-9,span_reduction="mean_all_supervised_mentions_including_context_duplicates",
        slot_addresses=addresses,attention_distributions=attention,attention_targets=gold,supervision_masks=supervised,public_token_masks=valid)
    return rows,tokens,target,aux


class GroundingReviewTests(unittest.TestCase):
    def test_grammar_offsets_reconstruct_all_targets_without_labels_or_proofs(self):
        rows,tokens,target = fixture()
        report = audit_span_targets(rows,target,tokens)
        self.assertEqual(report["span_mentions"],40)
        self.assertFalse(report["tokenizer_reexecuted"])
        for row in rows:
            row["label"] = 99
            row["evidence_sentence_indices"] = [999]
        self.assertTrue(audit_span_targets(rows,target,tokens)["passed"])

    def test_target_values_contexts_offsets_cache_and_role_mutations_rejected(self):
        rows,tokens,target = fixture()
        key = next(iter(target["public_token_alignments"]))
        mutations = [lambda t:t["fact_attention_targets"][0][0][0].__setitem__(0,1.),
            lambda t:t["mention_context_keys"][0][0].__setitem__(0,"f"*64),
            lambda t:t["public_token_alignments"][key]["cached_input_ids"].__setitem__(0,-1),
            lambda t:t["public_token_alignments"][key]["offset_mapping"].__setitem__(4,[0,9]),
            lambda t:t.update(trainer_only=False),lambda t:t["span_records"][0]["token_indices"].pop()]
        for mutation in mutations:
            wrong = copy.deepcopy(target); mutation(wrong)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                audit_span_targets(rows,wrong,tokens)

    def test_fresh_target_role_is_explicit_and_never_authorizes_training(self):
        rows,tokens,target = fixture()
        for row in rows:
            row["source_split"]="validation"
            row["paragraph_id"]=row["paragraph_id"].replace("binding-v4/train/41","binding-v5/fresh_combinations/2901")
        target.update(role="frozen_diagnostic",trainer_only=False,caller_must_enforce_all_models_frozen_and_raw_predictions_first=True,
                      case_ids=[_id(row) for row in rows])
        self.assertTrue(audit_span_targets(rows,target,tokens,role="frozen_diagnostic")["passed"])
        with self.assertRaises(ValueError):
            audit_span_targets(rows,target,tokens)

    def test_compact_and_full_auxiliary_match_independent_reference(self):
        _,_,target,aux = full_aux_fixture()
        compact = audit_auxiliary(aux,target,list(range(4)))
        full = audit_auxiliary(aux,target,list(range(4)),full=True)
        self.assertFalse(compact["full_dot_recomputed"])
        self.assertTrue(full["full_dot_recomputed"])
        self.assertEqual(full["span_mentions"],40)
        self.assertEqual(full["retrieval_numerically_ambiguous_queries"],0)

    def test_full_targets_use_actual_fp32_uniform_rounding(self):
        _,_,target,aux = full_aux_fixture()
        full_values = [v for row in aux["attention_targets"]["fact"] for fact in row for slot in fact for v in slot]
        self.assertIn(struct.unpack("<f",struct.pack("<f",1/3))[0],full_values)
        self.assertTrue(audit_auxiliary(aux,target,list(range(4)),full=True)["passed"])

    def test_compact_selected_probabilities_counts_masks_and_reductions_rejected(self):
        _,_,target,aux = full_aux_fixture()
        mutations=[lambda a:a["span_selected_probabilities"][0].__setitem__(0,.9),lambda a:a["span_token_counts"].__setitem__(0,99),
            lambda a:a["contrastive"]["positive_counts"].__setitem__(0,999),lambda a:a["contrastive"].update(context_identity_sha256="0"*64),
            lambda a:a["contrastive"].update(loss=.9),lambda a:a.update(span_weight=0,span_loss=.1)]
        for mutation in mutations:
            wrong=copy.deepcopy(aux);mutation(wrong)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                audit_auxiliary(wrong,target,list(range(4)))

    def test_full_vector_attention_and_immutable_public_mask_mutations_rejected(self):
        _,_,target,aux=full_aux_fixture()
        mutations=[lambda a:a["contrastive"]["raw_mention_vectors"][0].__setitem__(0,.4),
            lambda a:a["attention_distributions"]["fact"][0][0][0].__setitem__(0,.2),
            lambda a:a["public_token_masks"]["candidate"][0].__setitem__(-1,True),
            lambda a:a["contrastive"]["duplicate_counts"].__setitem__(0,999)]
        for mutation in mutations:
            wrong=copy.deepcopy(aux);mutation(wrong)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                audit_auxiliary(wrong,target,list(range(4)),full=True)

    def test_compact_scope_does_not_pretend_to_recompute_each_dot_product(self):
        _,_,target,aux=full_aux_fixture()
        wrong=copy.deepcopy(aux)
        for key in ("numerator_logsumexp","denominator_logsumexp"):
            wrong["contrastive"][key]=[v-.1 for v in wrong["contrastive"][key]]
        self.assertFalse(audit_auxiliary(wrong,target,list(range(4)))["full_dot_recomputed"])
        with self.assertRaisesRegex(ValueError,"cosine/logsumexp"):
            audit_auxiliary(wrong,target,list(range(4)),full=True)

    def test_natural_auxiliary_is_empty_and_cannot_invent_supervision(self):
        aux=dict(auxiliary_available=False,span_count=0,span_loss=0.,span_mention_ce=[],span_selected_probabilities=[],span_token_counts=[],
                 contrastive=dict(loss=0.,retrieval_correct=0,retrieval_queries=0))
        self.assertTrue(audit_auxiliary(aux)["passed"])
        aux["span_count"]=1
        with self.assertRaises(ValueError):audit_auxiliary(aux)


if __name__=="__main__":
    unittest.main()
