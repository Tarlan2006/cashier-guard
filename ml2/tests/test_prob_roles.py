"""Probabilistic roles: null option, invariance and concurrent clients."""

import copy
import unittest

from backend.pipeline.perception.prob_roles import assign_probabilistic_roles


def person(identifier, x, y):
    return dict(
        id=identifier,
        bbox=[x - 0.04, y - 0.04, x + 0.04, y + 0.04],
        counted=True,
        confidence=0.9,
    )


def scene():
    return dict(
        video=dict(width=400, height=600),
        fixtures=[
            dict(
                class_="unused",
                **{"class": "counter_machine", "bbox": [0.46, 0.46, 0.54, 0.54]}
            ),
            {"class": "safe", "bbox": [0.66, 0.46, 0.74, 0.54]},
            {"class": "laptop", "bbox": [0.66, 0.46, 0.74, 0.54]},
        ],
        frames=[
            dict(
                timestamp_sec=i * 0.5,
                persons=[person(1, 0.5, 0.6)]
                + ([person(2, 0.5, 0.3)] if i >= 8 else []),
            )
            for i in range(20)
        ],
    )


class ProbabilityRoleTests(unittest.TestCase):
    def test_resident_and_later_opposite_client_have_probabilities(self):
        facts = assign_probabilistic_roles(scene())
        people = facts["frames"][-1]["persons"]
        self.assertEqual(
            [p["role"] for p in people], ["cashier_candidate", "client_candidate"]
        )
        for person in people:
            self.assertTrue(0 <= person["cashier_prob"] <= 1)
            self.assertTrue(0 <= person["client_prob"] <= 1)
            self.assertLessEqual(
                person["cashier_prob"] + person["client_prob"], 1 + 1e-8
            )

    def test_single_far_person_is_not_certain_just_because_there_is_no_rival(self):
        facts = scene()
        for row in facts["frames"]:
            row["persons"] = [person(1, 0.05, 0.95)]
        assign_probabilistic_roles(facts)
        self.assertEqual(facts["frames"][-1]["persons"][0]["role"], "unknown")
        self.assertLess(facts["frames"][-1]["persons"][0]["cashier_prob"], 0.6)

    def test_equal_evidence_leaves_unknown(self):
        facts = scene()
        for row in facts["frames"]:
            row["persons"] = [person(1, 0.5, 0.6), person(2, 0.5, 0.4)]
        assign_probabilistic_roles(facts)
        self.assertTrue(
            all(p["role"] == "unknown" for p in facts["frames"][-1]["persons"])
        )

    def test_two_clients_are_not_forced_into_one_global_client_softmax(self):
        facts = scene()
        for index, row in enumerate(facts["frames"]):
            if index >= 8:
                row["persons"].append(person(3, 0.6, 0.3))
        assign_probabilistic_roles(facts)
        self.assertEqual(
            sum(
                p["role"] == "client_candidate" for p in facts["frames"][-1]["persons"]
            ),
            2,
        )

    def test_uncertain_person_gets_scores_but_keeps_unknown(self):
        facts = scene()
        for row in facts["frames"]:
            for p in row["persons"]:
                p["uncertain"] = True
        assign_probabilistic_roles(facts)
        self.assertTrue(
            all(p["role"] == "unknown" for p in facts["frames"][-1]["persons"])
        )
        self.assertTrue(
            all("cashier_prob" in p for p in facts["frames"][-1]["persons"])
        )

    def test_resolution_change_does_not_change_probabilities(self):
        first, second = scene(), scene()
        second["video"] = {"width": 800, "height": 1200}
        assign_probabilistic_roles(first)
        assign_probabilistic_roles(second)
        self.assertAlmostEqual(
            first["frames"][-1]["persons"][0]["cashier_prob"],
            second["frames"][-1]["persons"][0]["cashier_prob"],
        )


if __name__ == "__main__":
    unittest.main()
