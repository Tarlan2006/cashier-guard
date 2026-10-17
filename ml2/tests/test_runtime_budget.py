"""Deadline scheduling and boundary checks without sleeping/model inference."""

import unittest
from unittest.mock import patch

from backend.pipeline.budget import RuntimeBudget, BudgetExpired
from backend.pipeline.perception.config import PerceptionConfig


class BudgetTests(unittest.TestCase):
    def test_interval_only_increases_after_the_adaptive_boundary(self):
        budget = RuntimeBudget(started=0.0)
        with patch("backend.pipeline.budget.time.perf_counter", return_value=149.0):
            self.assertEqual(budget.interval(100.0, 145.0), 0.5)
        with patch("backend.pipeline.budget.time.perf_counter", return_value=151.0):
            self.assertGreaterEqual(budget.interval(100.0, 145.0), 2.0)
        self.assertEqual(len(budget.changes), 1)

    def test_stop_deadline_returns_control_instead_of_starting_more_work(self):
        budget = RuntimeBudget(started=0.0)
        with patch("backend.pipeline.budget.time.perf_counter", return_value=168.0):
            with self.assertRaises(BudgetExpired):
                budget.check()

    def test_invalid_deadline_order_is_rejected(self):
        with self.assertRaises(ValueError):
            PerceptionConfig(adaptive_after_sec=170.0, stop_after_sec=168.0)
