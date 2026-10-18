import unittest
from evaluate_object_controls import summarize

def result(presence='away_observed',mask='mask_observed'):
 return {'timeline':[{'cashier_presence':presence,'departure_supported':presence=='away_observed','experimental_object':{'state':mask}}],'experimental_signals':[]}

class Tests(unittest.TestCase):
 def test_missing_cashier_is_inconclusive(self):
  self.assertEqual(summarize(result('unknown'))['status'],'inconclusive_no_observed_departure')
 def test_missing_object_is_not_a_successful_control(self):
  self.assertEqual(summarize(result(mask='unknown'))['status'],'inconclusive_object_lost_during_departure')
 def test_observed_coverage_remains_partial(self):
  s=summarize(result());self.assertEqual(s['status'],'no_candidate_with_partial_observed_coverage');self.assertFalse(s['approved_for_rule_engine']);self.assertFalse(s['accuracy_established'])
 def test_signal_always_requires_review(self):
  r=result('unknown','unknown');r['experimental_signals']=[{'start_sec':1,'end_sec':2}]
  self.assertEqual(summarize(r)['status'],'candidate_requires_review')

if __name__=='__main__':unittest.main()
