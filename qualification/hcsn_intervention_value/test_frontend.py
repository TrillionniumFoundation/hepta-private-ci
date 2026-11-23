import unittest

import numpy as np

from .frontend import build, candidate


def data(prefix):
    rng=np.random.default_rng(1+ord(prefix))
    n=12
    group=np.repeat([prefix+str(i) for i in range(6)],2)
    return dict(audio=rng.normal(size=(n,6,52)),visual=rng.normal(size=(n,6,76)),
                group=group,recording=group,label=np.repeat([0,1,0,1,0,1],2),dt=np.full((n,6),.48),
                query_id=np.array([prefix+str(i) for i in range(n)]),start_seconds=np.zeros(n),
                split=np.repeat(prefix,n))


class Frontend(unittest.TestCase):
    def test_causality_and_paid_isolation(self):
        g,t,d=(data(k) for k in 'gtd')
        base,_=build(g,t,{'dev':d},{})
        d['visual']*=100
        d['audio'][:,3:]+=30.
        alt,_=build(g,t,{'dev':d},{})
        a,b=(candidate(r['dev'],'trained_visual') for r in (base,alt))
        np.testing.assert_allclose(a['x'][:,:3],b['x'][:,:3])
        np.testing.assert_allclose(a['scores'][:,:3],b['scores'][:,:3])
        self.assertFalse(np.allclose(a['read_scores'],b['read_scores']))

    def test_training_creator_does_not_fit_own_classifier(self):
        g,t,d=(data(k) for k in 'gtd')
        before,_=build(g,t,{'dev':d},{})
        row=t['group']==t['group'][0]
        t['label'][row]=1-t['label'][row]
        after,_=build(g,t,{'dev':d},{})
        np.testing.assert_allclose(before['train'][0]['scores'][row],after['train'][0]['scores'][row])
