import unittest
import numpy as np
from test_matched_haar import source,inputs,terms
from matched_haar import MatchedHaarModel,MODE
from grouped_training import select_group_gradients
MEASUREMENTS={}
class InteractionTests(unittest.TestCase):
    def test_four_arm_routes_and_Haar_rowN_anchor_parameter_FD(self):
        base=source()
        for rep in ('raw','haar'):
            for objective,key in (('additive','aligned_additive'),('row_ndu','aligned_ndu')):
                model=MatchedHaarModel.from_source(base,representation=rep,mode=MODE);t=terms(model);dp,dq=select_group_gradients(t,{},objective)
                for got,g,a in zip((dp,dq),t[key][1:3],t['aligned_anchor']):np.testing.assert_array_equal(got,g+.2*a)
                model.gradients(inputs(),dp,dq)
        model=MatchedHaarModel.from_source(base,representation='haar',mode=MODE);t=terms(model);dp,dq=select_group_gradients(t,{},'row_ndu');grads=model.gradients(inputs(),dp,dq)
        def loss():
            t=terms(model);return -t['aligned_ndu'][0].mean()+.2*t['aligned_anchor_value']
        errors=[]
        for key,index in (('encoder',(0,0)),('encoder',(195,0)),('bias',(0,)),('text',(0,1)),('text_bias',(1,)),('image',(0,5)),('image_bias',(5,))):
            old=model.params[key][index];eps=1e-6;model.params[key][index]=old+eps;plus=loss();model.params[key][index]=old-eps;minus=loss();model.params[key][index]=old;errors.append(float(abs((plus-minus)/(2*eps)-grads[key][index])))
        self.assertLess(max(errors),2e-7);MEASUREMENTS['Haar_rowN_anchor_FD_coordinates']=7;MEASUREMENTS['Haar_rowN_anchor_max_FD']=max(errors)
