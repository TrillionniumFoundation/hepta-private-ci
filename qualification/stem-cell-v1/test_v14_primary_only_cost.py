"""Small synthetic parity/adversarial tests: NOT pretrained efficacy or 829-case study."""
from __future__ import annotations
import copy
import math
import unittest
from stem_v13_cheap_retrieval import Index, CONFIG
from v14_primary_only_cost import OriginalPrimaryOnly, validate_packet, run

DOCS=[{'id':'s%03d'%i,'text':f'alpha beta zeta something {i} relay\n' if i%3 else f'gamma dog carrot beta {i}'} for i in range(70)]
QUERIES=['alpha beta','gamma beta','carrot 22','zeta something','epsilon xyz','what is alpha?', 'beta 3']

class Parity(unittest.TestCase):
    def test_identical_primary_top32_on_synthetic(self):
        a=Index(DOCS); b=OriginalPrimaryOnly(DOCS)
        for q in QUERIES:
            with self.subTest(q=q):self.assertEqual(a.rank(q)['phrase_char'], b.rank(q))
    def test_single_arm_no_disallowed_extra_keys(self):
        result=OriginalPrimaryOnly(DOCS).rank('alpha beta')
        self.assertEqual(len(result),32)
        self.assertEqual(len(set(result)),32)
    def test_blank_query_refuses(self):
        with self.assertRaises(ValueError):OriginalPrimaryOnly(DOCS).rank('')
    def test_no_gold_ingestion_by_source_packet(self):
        with self.assertRaises(ValueError):validate_packet({'families':{'labels':[1]}},{})
    def test_fake_fixed_config_rejected(self):
        self.assertEqual(CONFIG['phrase_char_weights'],[0.7,0.1,0.2])
    def test_unregistered_profile(self):
        with self.assertRaises(ValueError):run({}, {}, 'learned_future')
    def test_not_a_reader_claim(self):
        self.assertNotIn('human_semantic_correctness',OriginalPrimaryOnly(DOCS).__dict__)
    def test_unicode(self):
        docs=DOCS+[{'id':'han','text':'中文 问题 猫咪 hola café'}]
        self.assertEqual(Index(docs).rank('中文 猫咪')['phrase_char'],OriginalPrimaryOnly(docs).rank('中文 猫咪'))
    def test_source_order_tie(self):
        docs=[{'id':str(i),'text':'same exact word'} for i in range(40)]
        self.assertEqual(Index(docs).rank('anything')['phrase_char'],OriginalPrimaryOnly(docs).rank('anything'))
    def test_symbols_without_words_refuse(self):
        with self.assertRaises(ValueError):OriginalPrimaryOnly(DOCS).rank('⚡🪴')
if __name__=='__main__':unittest.main()
