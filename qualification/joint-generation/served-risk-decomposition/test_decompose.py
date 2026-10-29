import copy
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import decompose as d

class MetricTests(unittest.TestCase):
    def test_endpoints(self):
        self.assertEqual(d.rho(0,.2),0);self.assertAlmostEqual(d.rho(1,0),1)
        self.assertAlmostEqual(d.rho(1,.04),math.exp(-1))
    def test_swap_and_conservation(self):
        for a,b,c,e in [(0,0,1,1),(.25,.01,.75,.03),(1,0,1,.02),(.99,.1,.2,0)]:
            x=d.channels(a,b,c,e);y=d.channels(c,e,a,b)
            for k in x:self.assertAlmostEqual(x[k],-y[k],places=14)
            self.assertAlmostEqual(x['rho_delta'],x['class_mass_component']+x['image_mse_component'],places=14)
    def test_one_channel_only(self):
        self.assertEqual(d.channels(.5,.01,.5,.03)['class_mass_component'],0)
        self.assertEqual(d.channels(.5,.01,.8,.01)['image_mse_component'],0)
    def test_invalid_scalars(self):
        for x in [True,None,float('nan'),float('inf'),-.01,1.01]:
            with self.assertRaises(ValueError):d.rho(x,.02)
            with self.assertRaises(ValueError):d.rho(.5,x)
    def test_fixed_exhaustive_bins(self):
        self.assertEqual([d.bin_index(x) for x in [0,.49,.5,.89,.9,.989,.99,1]],[0,0,1,1,2,2,3,3])
    def test_empty_and_weighted_summary(self):
        self.assertIsNone(d.summarize([])['mean'])
        x=d.channels(.75,.01,.5,.02);r=d.summarize([x],2)
        self.assertEqual(r['contribution_to_stratum_mean']['rho_delta'],x['rho_delta']/2)
    def test_missing_inventory(self):
        with self.assertRaises(ValueError):d.analyze([])
    def test_literal_full_report(self):
        p=.5;m=.02;rows=[]
        for i in range(765):
            for v in d.NOISE:rows.append({'source_id':str(i),'variant':v,'label':i%10,'law':'finite-u53-fixed-10','request_sha256':'0'*64,'target_sha256':'1'*64,'expected_accuracy':p,'expected_mse':m,'expected_utility':p*math.exp(-m/.04),'conditional_entropic_rho2':d.rho(p,m),'actual_class_nll':{'tag':'finite','value':-math.log(p)}})
        base={'schema':'endpoint-anchor-comparison-fresh-AA-v1/served-report','origin':'DEV-developmental','checkpoint':'final','panel':'corrupted','official_TEST_read':False,'cohort_sha256':'2'*64,'source_sha256':'3'*64,'cell':list(d.CELLS[0]),'request_rows':rows,'overall':{'metrics':{k:rows[0][k] for k in d.METRICS}}}
        self.assertEqual(len(d.report_rows(base)),1530)
        reports=[{**base,'cell':list(c)} for c in d.CELLS];result=d.analyze(reports)
        self.assertEqual(len(result['contrasts']),14)
        self.assertTrue(all(r['strata']['all']['overall']['mean']['rho_delta']==0 for r in result['contrasts']))
        for change in ('duplicate','metric','test'):
            bad=copy.deepcopy(base)
            if change=='duplicate':bad['request_rows'][-1]=bad['request_rows'][0]
            elif change=='metric':bad['request_rows'][0]['expected_utility']+=.1
            else:bad['official_TEST_read']=True
            with self.assertRaises(ValueError):d.report_rows(bad)

if __name__=='__main__':unittest.main(verbosity=2)
