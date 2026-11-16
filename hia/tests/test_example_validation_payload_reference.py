"""Source-only effect-order cases; no HIA/native/Rust product is executed."""
import random
import unittest

from example_validation_reference import ErrorKind, PendingValidation, validate_pending
from example_validation_payload_reference import (
    FALLBACK_EXAMPLE, ValidationWithRules, validate_pending_payload,
)


class PayloadReferenceTest(unittest.TestCase):
    def run_model(self, groups, match, debug=None, join=None):
        return validate_pending_payload(
            groups, 0, match, debug or (lambda value: f"<{value}>"),
            join or (lambda tokens: "|".join(tokens)),
        )

    def test_negative_first_match_debug_before_join_and_only_first_rule(self):
        calls = []
        group = ValidationWithRules(['owned', 'unused'], [['a'], ['hit'], ['late']], [['positive']], 'loc')
        def match(g, cmd):
            calls.append(('match', cmd[0]))
            return ['first', 'second'] if cmd[0] == 'hit' else []
        def debug(rule):
            calls.append(('debug', rule))
            return rule.upper()
        def join(cmd):
            calls.append(('join', cmd[0]))
            return cmd[0]
        out = self.run_model([group], match, debug, join)
        self.assertEqual(calls, [('match','a'), ('match','hit'), ('debug','first'), ('join','hit')])
        self.assertEqual((out.kind,out.first_rule_debug,out.matched_negative_example,out.location),
                         (ErrorKind.EXAMPLE_DID_MATCH,'FIRST','hit','loc'))
        self.assertEqual(out.all_rule_debug, ())
        self.assertEqual(out.event_trace, (('not_match',0,0),('not_match',0,1),('debug_match',0,0),('join_negative',0,1)))

    def test_negative_try_join_error_uses_exact_fallback(self):
        g=ValidationWithRules([], [['\x00']], [], None)
        out=self.run_model([g], lambda *_:['match'], join=lambda _:None)
        self.assertEqual(out.matched_negative_example, FALLBACK_EXAMPLE)
        self.assertEqual(out.kind, ErrorKind.EXAMPLE_DID_MATCH)

    def test_positive_renders_each_unmatched_then_debugs_all_rules(self):
        calls=[]
        g=ValidationWithRules(['r1','r2'], [], [['yes'],['bad'],['also-bad']], 'here')
        def match(_, cmd):
            calls.append(('match',cmd[0]))
            return ['ok'] if cmd[0]=='yes' else []
        def join(cmd):
            calls.append(('join',cmd[0]))
            return None if cmd[0]=='also-bad' else cmd[0]
        def debug(rule):
            calls.append(('debug',rule))
            return rule.upper()
        out=self.run_model([g],match,debug,join)
        self.assertEqual(calls,[('match','yes'),('match','bad'),('join','bad'),
                                ('match','also-bad'),('join','also-bad'),('debug','r1'),('debug','r2')])
        self.assertEqual(out.unmatched_positive_examples, ('bad',FALLBACK_EXAMPLE))
        self.assertEqual(out.all_rule_debug, ('R1','R2'))
        self.assertEqual((out.kind,out.location),(ErrorKind.EXAMPLE_DID_NOT_MATCH,'here'))

    def test_matched_positive_never_formats_examples_or_rules(self):
        g=ValidationWithRules(['sensitive'], [['negative']], [['positive']],'ignored')
        out=self.run_model([g], lambda _,c:['match'] if c[0]=='positive' else [],
                           lambda _:self.fail('unexpected Debug'),
                           lambda _:self.fail('unexpected join'))
        self.assertEqual(out.kind, ErrorKind.NONE)
        self.assertIsNone(out.location)

    def test_negative_debug_exception_blocks_join_and_later_groups(self):
        g=ValidationWithRules(['r'], [['hit']], [['late']],'not-attached')
        g2=ValidationWithRules([], [['later']], [],'later')
        seen=[]
        def debug(_):
            seen.append('debug'); raise ValueError('panic before try_join')
        with self.assertRaisesRegex(ValueError,'panic before try_join'):
            self.run_model([g,g2],lambda _,cmd:seen.append(cmd[0]) or ['match'], debug,
                           lambda _:self.fail('should not join'))
        self.assertEqual(seen,['hit','debug'])

    def test_positive_debug_exception_after_all_unmatched_join(self):
        g=ValidationWithRules(['ok','boom','late'],[],[['miss1'],['miss2']],'unused')
        seen=[]
        def debug(rule):
            seen.append(('debug',rule))
            if rule=='boom': raise ValueError('debug panic')
            return rule
        def join(tokens):
            seen.append(('join',tokens[0]));return tokens[0]
        with self.assertRaisesRegex(ValueError,'debug panic'):
            self.run_model([g],lambda _,cmd:seen.append(('match',cmd[0])) or [],debug,join)
        self.assertEqual(seen,[('match','miss1'),('join','miss1'),('match','miss2'),('join','miss2'),
                               ('debug','ok'),('debug','boom')])

    def test_render_exception_blocks_later_rules_and_groups(self):
        groups=[ValidationWithRules([],[],[['missing'],['never']],None),
                ValidationWithRules([], [['future']], [],None)]
        seen=[]
        def join(tokens):
            seen.append(('join',tokens[0]));raise RuntimeError('join double failure')
        with self.assertRaisesRegex(RuntimeError,'join double failure'):
            self.run_model(groups,lambda _,c:seen.append(('match',c[0])) or [],join=join)
        self.assertEqual(seen,[('match','missing'),('join','missing')])

    def test_none_and_empty_result_even_with_location(self):
        groups=[ValidationWithRules(['unused'],[],[],'a'), ValidationWithRules(['unused'],[],[],'b')]
        out=self.run_model(groups,lambda *_:self.fail('must be empty'))
        self.assertEqual((out.kind,out.group_index,out.location,out.event_trace),
                         (ErrorKind.NONE,None,None,()))

    def test_start_excludes_prior_groups_and_end_is_noop(self):
        groups=[ValidationWithRules([], [['hit']], [],'skipped'),ValidationWithRules([],[],[['miss']],'picked')]
        args=(lambda _,cmd: [],lambda v:f'{v}',lambda c:c[0])
        out=validate_pending_payload(groups,1,*args)
        self.assertEqual((out.kind,out.group_index,out.location),(ErrorKind.EXAMPLE_DID_NOT_MATCH,1,'picked'))
        end=validate_pending_payload(groups,2,*args)
        self.assertEqual((end.kind,end.event_trace),(ErrorKind.NONE,()))

    def test_invalid_start_rejected_before_callbacks(self):
        groups=[ValidationWithRules([],[],[])]
        for x in [-1,2,True,0.5,'0']:
            with self.subTest(x=x),self.assertRaises(IndexError):
                validate_pending_payload(groups,x,lambda *_:self.fail('match'),
                                         lambda _:self.fail('debug'),lambda _:self.fail('join'))

    def test_stateful_repeat_without_memoization(self):
        g=ValidationWithRules(['r'],[['same'],['same']],[['same']],None)
        seen=[]
        def match(_,cmd):
            seen.append(tuple(cmd))
            return ['matched'] if len(seen)==3 else []
        out=self.run_model([g],match)
        self.assertEqual(seen,[('same',)]*3)
        self.assertEqual(out.kind,ErrorKind.NONE)

    def test_none_location_is_not_invented_on_errors(self):
        g=ValidationWithRules(['r'],[['hit']],[],None)
        out=self.run_model([g],lambda *_:['m'])
        self.assertEqual(out.kind,ErrorKind.EXAMPLE_DID_MATCH)
        self.assertIsNone(out.location)

    def test_8000_deterministic_structural_equivalence_to_selection_reference(self):
        rng=random.Random(0x18E770)
        for case in range(8000):
            groups=[]; old=[]; answers={}
            for idx in range(rng.randrange(0,5)):
                negatives=[(str(case),str(idx),'n',str(j)) for j in range(rng.randrange(0,4))]
                positives=[(str(case),str(idx),'p',str(j)) for j in range(rng.randrange(0,4))]
                rules=[f'rule-{idx}-{j}' for j in range(rng.randrange(0,4))]
                loc=f'loc-{idx}'
                groups.append(ValidationWithRules(rules,negatives,positives,loc))
                old.append(PendingValidation(negatives,positives,loc))
                for cmd in negatives+positives: answers[cmd]=bool(rng.getrandbits(1))
            start=rng.randrange(len(groups)+1)
            seen1=[];seen2=[]
            def callback(group,cmd):
                seen1.append((group,tuple(cmd)));return answers[tuple(cmd)]
            def matcher(group,cmd):
                seen2.append((group,tuple(cmd)))
                return [f'matched-{group}'] if answers[tuple(cmd)] else []
            selection=validate_pending(old,start,callback)
            payload=validate_pending_payload(groups,start,matcher,lambda rule:str(rule),
                                            lambda parts:'|'.join(parts))
            self.assertEqual(payload.kind,selection.error)
            self.assertEqual(payload.group_index,selection.failing_validation_index)
            self.assertEqual(payload.location,selection.attached_location)
            self.assertEqual(seen2,seen1)
            if payload.kind==ErrorKind.EXAMPLE_DID_NOT_MATCH:
                self.assertEqual(len(payload.unmatched_positive_examples),
                                 len(selection.local_result.unmatched_positive_indices))
                self.assertEqual(len(payload.all_rule_debug),len(groups[payload.group_index].rules))
            if payload.kind==ErrorKind.EXAMPLE_DID_MATCH:
                self.assertEqual(len(payload.all_rule_debug),0)


if __name__=='__main__':
    unittest.main()
