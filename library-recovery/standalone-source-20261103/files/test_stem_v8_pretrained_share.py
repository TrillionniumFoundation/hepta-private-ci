"""V8 source-only safety and optional original archived-weight execution tests.

Static fixtures are NOT actual inference. Set HEPTA_V8_REAL_ROOT to run genuine
original MiniLM numeric/input tests; no synthetic test grants model authority.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from stem_v8_pretrained_share import (
    ACTIVE, SCENARIOS, SIZES, SHA, OriginalMiniLM, bare_wordpiece,
    scenario_rows, source_only_records, validate_receipt, verify_material,
)
from stem_selection_v7 import cache_identity


def valid_shape_fixture():
    """Deliberately fabricated contract fixture, never original pretrained proof."""
    n, m = 64, 2
    rows = []
    for key, unique in zip(SCENARIOS, (1, 4, 32, 32, 32), strict=True):
        rows.append(dict(scenario=key, active_cell_heads=ACTIVE,
                         unique_source_authority_keys=unique,
                         baseline_encoder_forwards=ACTIVE * m,
                         shared_encoder_forwards=unique * m,
                         baseline_measured_ms=[100., 102.], shared_measured_ms=[10., 12.],
                         baseline_p50_ms=101., shared_p50_ms=11.,
                         baseline_p95_ms=102., shared_p95_ms=12.,
                         readout_sha256="1" * 64, bitwise_equal=True, source_text_logged=False))
    return dict(schema="hepta.stem.v8.archived-minilm-physical-share.shadow.v1",
                size=n, iterations_per_scenario=m, active_per_dispatch=32,
                source_script_sha256="a"*64,
                material_sha256={k: SHA[k] for k in ("model", "tokenizer", "vocab", "config", "locomo")},
                numeric_probe=dict(cls="b"*64, pooler="c"*64,
                                   same_host_reference_exact=True,
                                   archived_cross_host_reference_exact=False),
                archived_numeric_sha256=dict(cls=SHA["numeric_cls"], pooler=SHA["numeric_pooler"]),
                real_pretrained_encoder_model_weights=True, original_source_turns_model_input=True,
                hf_tokenizer_operator_parity_verified=False, multimodal_tested=False,
                retention_gain_verified=False, new_model_winner_verified=False,
                real_target_host=False, production_authorized=False,
                human_task_accuracy=None, source_owner_signature=None,
                reader_natural_answer_calls=0, independent_calendar_windows=0,
                resident_private_heads=n, resident_encoder_copies=1,
                per_head_params=6914, actual_head_parameters=n*6914,
                encoder_forwards_including_numeric_anchor=1+sum((32+x)*m for x in (1,4,32,32,32)),
                encoder_token_positions_including_anchor=20000,
                rss_before_model_kib=12000, rss_with_model_and_heads_kib=320000,
                rss_after_trials_kib=321000, model_load_wall_seconds=1.2,
                total_cpu_seconds=15.,total_wall_seconds=16., rows=rows)


class NoOriginalModelNeeded(unittest.TestCase):
    def test_supported_size_and_scenario_universe(self):
        self.assertEqual(SIZES, (64, 256, 1024, 4096))
        self.assertEqual(len(SCENARIOS), 5)

    def test_wordpiece_bounds_no_silent_truncation(self):
        vocab={"a":1}
        self.assertEqual(bare_wordpiece("a",vocab),[101,1,102])
        with self.assertRaises(ValueError):bare_wordpiece("a "*127,vocab)
        for value in ("", "  ", "a"*5000):
            with self.assertRaises(ValueError):bare_wordpiece(value,vocab)

    def test_wordpiece_candidate_unknown(self):
        self.assertEqual(bare_wordpiece("notinvocab",{}),[101,100,102])

    def test_material_missing_fails(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):verify_material(Path(td))

    def test_complete_cache_key_reuses_only_when_identity_matches(self):
        base=dict(principal="a", purpose="test", generation=0, authority_epoch=1,
                  model_revision=SHA["model_revision"], weights_sha256=SHA["model"],
                  tokenizer_sha256=SHA["tokenizer"], preprocess_sha256="a"*64,
                  input_sha256="b"*64,modality="text")
        self.assertEqual(cache_identity(base),cache_identity(dict(base)))
        for name,value in (("principal","b"),("purpose","other"),("generation",1),
                           ("authority_epoch",2),("model_revision","b"*40),
                           ("weights_sha256","c"*64),("tokenizer_sha256","d"*64),
                           ("preprocess_sha256","e"*64),("input_sha256","f"*64),
                           ("modality","image")):
            copyrow=dict(base);copyrow[name]=value
            self.assertNotEqual(cache_identity(base),cache_identity(copyrow),name)

    def test_registered_scenarios_do_not_secretly_reuse(self):
        source=[dict(text=f"source reference {i} with content", family_id=f"root{i%10}",
                     source_sha256=hashlib.sha256(str(i).encode()).hexdigest()) for i in range(32)]
        for mode,want in zip(SCENARIOS,(1,4,32,32,32),strict=True):
            rows=scenario_rows(source,mode,64)
            self.assertEqual(len(rows),32)
            self.assertEqual(len({r['key'] for r in rows}),want)
            self.assertEqual([x['cell_id'] for x in rows],list(range(32)))
            self.assertTrue(all('label' not in row and 'answer' not in row for row in rows))

    def test_tamper_source_hash_and_duplicate_material_forbid(self):
        rows=[dict(text="some original public text", family_id="f0",source_sha256="a"*64)]*32
        with self.assertRaises(ValueError):scenario_rows(rows,'unknown',64)
        with self.assertRaises(ValueError):scenario_rows(rows,'identical',42)

    def test_receipt_fixture_contract_not_pretrained_proof(self):
        self.assertTrue(validate_receipt(valid_shape_fixture()))

    def test_reject_fake_model_winner_and_authority(self):
        for field in ("hf_tokenizer_operator_parity_verified", "multimodal_tested",
                      "retention_gain_verified", "new_model_winner_verified",
                      "real_target_host", "production_authorized"):
            a=valid_shape_fixture();a[field]=True
            with self.assertRaises(ValueError, msg=field):validate_receipt(a)

    def test_reject_wrong_model_digests_and_numeric(self):
        x=valid_shape_fixture();x['material_sha256']['model']='0'*64
        with self.assertRaises(ValueError):validate_receipt(x)
        for field,value in (("same_host_reference_exact",False),
                            ("archived_cross_host_reference_exact",True),
                            ("cls","not-a-digest")):
            x=valid_shape_fixture();x['numeric_probe'][field]=value
            with self.assertRaises(ValueError, msg=field):validate_receipt(x)

    def test_reject_missing_cases_and_false_forward_conservation(self):
        x=valid_shape_fixture();x['rows'].pop()
        with self.assertRaises(ValueError):validate_receipt(x)
        for field,value in (("encoder_forwards_including_numeric_anchor",123),
                            ("actual_head_parameters",3),
                            ("resident_encoder_copies",4),
                            ("active_per_dispatch",33)):
            x=valid_shape_fixture();x[field]=value
            with self.assertRaises(ValueError, msg=field):validate_receipt(x)

    def test_reject_fake_cross_domain_sharing(self):
        x=valid_shape_fixture();x['rows'][3]['shared_encoder_forwards']=2
        with self.assertRaises(ValueError):validate_receipt(x)
        x=valid_shape_fixture();x['rows'][4]['unique_source_authority_keys']=1
        with self.assertRaises(ValueError):validate_receipt(x)

    def test_reject_fake_timings_or_output_hash(self):
        for field,value in (("shared_p50_ms",1.),("shared_p95_ms",-1.),
                            ("readout_sha256","not-a-real-hash"),
                            ("bitwise_equal",False),
                            ("source_text_logged",True),
                            ("shared_measured_ms",[1.,float('nan')])):
            x=valid_shape_fixture();x['rows'][0][field]=value
            with self.assertRaises(ValueError, msg=field):validate_receipt(x)

    def test_reject_false_human_accuracy_and_future(self):
        for field,value in (("human_task_accuracy",0.9),
                            ("source_owner_signature","fake"),
                            ("reader_natural_answer_calls",1),
                            ("independent_calendar_windows",2)):
            x=valid_shape_fixture();x[field]=value
            with self.assertRaises(ValueError, msg=field):validate_receipt(x)

    def test_reject_changed_source_file_sha(self):
        with self.assertRaises(ValueError):validate_receipt(valid_shape_fixture(),source_sha="1"*64)


class PhysicallyLoadedOriginalIfMounted(unittest.TestCase):
    @unittest.skipUnless(os.getenv("HEPTA_V8_REAL_ROOT"),"original original pretrained archive not mounted")
    def test_original_pretrained_tensor_numeric_and_source_only_roster(self):
        import torch
        torch.set_num_threads(1)
        root=Path(os.environ["HEPTA_V8_REAL_ROOT"])
        original=OriginalMiniLM(root)
        observed=original.numeric_probe()
        self.assertTrue(observed['same_host_reference_exact'])
        self.assertGreater(original.calls,0)
        records=source_only_records(root/'locomo.json')
        self.assertGreaterEqual(len(records),32)
        self.assertEqual(len({r['family_id'] for r in records}),10)
        self.assertTrue(all(set(r)=={'family_id','source_id','source_sha256','text'} for r in records))


if __name__=='__main__':unittest.main()
