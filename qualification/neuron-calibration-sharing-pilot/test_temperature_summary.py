import copy
import unittest
from temperature_summary import temperature_summary

class TemperatureSummaryTests(unittest.TestCase):
    def test_all_uniform(self):
        self.assertEqual(temperature_summary([{'T':None,'uniform':True}]*20),{'finite_T_range':None,'finite_count':0,'uniform_count':20,'choice_count':20})
    def test_mixed(self):
        self.assertEqual(temperature_summary([{'T':None,'uniform':True},{'T':.5,'uniform':False},{'T':2.,'uniform':False}]),{'finite_T_range':[.5,2.],'finite_count':2,'uniform_count':1,'choice_count':3})
    def test_finite(self):
        self.assertEqual(temperature_summary([{'T':.6,'uniform':False},{'T':.5,'uniform':False}])['finite_T_range'],[.5,.6])
    def test_empty(self):
        self.assertEqual(temperature_summary([])['finite_T_range'],None)
    def test_preserves_choices(self):
        a=[{'T':None,'uniform':True},{'T':.5,'uniform':False}];b=copy.deepcopy(a);temperature_summary(a);self.assertEqual(a,b)
    def test_invalid(self):
        for a in [[{'T':1,'uniform':True}],[{'T':None,'uniform':False}],[{'T':float('nan'),'uniform':False}],[{'T':-1,'uniform':False}]]:
            with self.assertRaises(ValueError):temperature_summary(a)

if __name__=='__main__':unittest.main()
