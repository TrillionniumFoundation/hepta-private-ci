"""CPU-torch real Head optimizer on synthetic features, never real pretrained score."""
import copy
import unittest
import torch
import e3_native_capacity_match as m

class Controls(unittest.TestCase):
 def source(self,coincident=False):
  torch.manual_seed(47)
  t=torch.randn(32,256,requires_grad=True)
  j=t.clone().detach() if coincident else torch.randn(32,256,requires_grad=True)
  choices=torch.randn(32,4,256,requires_grad=True)
  labels=[x%4 for x in range(16)]
  return t,j,choices,list(range(16)),labels,list(range(16,32))
 def test_genuine_torch_sgd_both_controls(self):
  q=m.train_pair(*self.source(),steps=2)
  self.assertEqual(len(q['text_only_probabilities']),16)
  self.assertEqual(len(q['joint_text_image_probabilities']),16)
  self.assertEqual(q['heads_complete_trainable_params_each'],769)
  self.assertEqual(q['authority'],'DENY_ALL')
  self.assertTrue(q['same_initialization'])
 def test_identical_features_equal_outputs(self):
  q=m.train_pair(*self.source(coincident=True),steps=2)
  self.assertEqual(q['text_only_probabilities'],q['joint_text_image_probabilities'])
  self.assertEqual(q['text_trained_head_digest'],q['joint_trained_head_digest'])
 def test_no_encoder_grad(self):
  args=self.source()
  m.train_pair(*args,steps=2)
  self.assertIsNone(args[0].grad)
  self.assertIsNone(args[1].grad)
  self.assertIsNone(args[2].grad)
 def test_cal_labels_unavailable_to_function(self):
  self.assertNotIn('cal_labels',m.train_pair.__code__.co_varnames)
  self.assertNotIn('test_labels',m.train_pair.__code__.co_varnames)
 def test_train_labels_change_head(self):
  args=self.source()
  a=m.train_pair(*args,steps=2)
  args=list(args);args[4]=[(x+1)%4 for x in args[4]]
  b=m.train_pair(*args,steps=2)
  self.assertNotEqual(a['text_trained_head_digest'],b['text_trained_head_digest'])
 def test_overlap_is_rejected(self):
  args=list(self.source());args[5]=[15]+list(range(17,32))
  with self.assertRaises(m.MatchedHeadError):m.train_pair(*args,steps=2)
 def test_bad_count_labels_is_rejected(self):
  args=list(self.source());args[4]=[0,1]
  with self.assertRaises(m.MatchedHeadError):m.train_pair(*args,steps=2)
 def test_illegal_class_is_rejected(self):
  args=list(self.source());args[4][0]=4
  with self.assertRaises(m.MatchedHeadError):m.train_pair(*args,steps=2)
 def test_nonfinite_is_rejected(self):
  args=list(self.source());args[0]=args[0].detach().clone();args[0][1,1]=float('nan')
  with self.assertRaises(m.MatchedHeadError):m.train_pair(*args,steps=2)
 def test_no_overwide_hidden_params(self):
  args=self.source();q=m.train_pair(*args,steps=2)
  self.assertEqual(q['heads_complete_trainable_params_each'],769)
 def test_input_incomplete(self):
  args=list(self.source());args[2]=args[2][:20]
  with self.assertRaises(m.MatchedHeadError):m.train_pair(*args,steps=2)
 def test_no_duplicate_train_indices(self):
  args=list(self.source());args[3][0]=args[3][1]
  with self.assertRaises(m.MatchedHeadError):m.train_pair(*args,steps=2)

if __name__=='__main__':unittest.main()
