from copy import deepcopy
import json
import unittest

from scripts.build_rules_catalog import DOCUMENT, REPO, build_catalog, verify_paragraphs


def source_fixture():
    return dict(sources=[dict(id="source", official_url="https://example.org/act.pdf")],
        rules=[dict(id=f"KZ-CASH-{i:03d}", type=f"Synthetic type {i}", source_id="source",
                    paragraph="п. 22", legal_requirement="Shared legal phrase for a synthetic test",
                    visual_candidate="Synthetic visible sign", do_not_flag_if=["Synthetic exception"])
               for i in range(1, 9)])


class CatalogBuilderTests(unittest.TestCase):
    def test_mapping_preserves_visual_conditions_and_document(self):
        source = source_fixture()
        result = build_catalog(source)
        self.assertEqual(len(result["rules"]), 8)
        self.assertEqual(result["rules"][0], dict(id="KZ-CASH-001", title="Synthetic type 1",
            visual_signs=["Synthetic visible sign", "Не отмечать, если: Synthetic exception"],
            document=DOCUMENT, section="п. 22", url="https://example.org/act.pdf", is_demo=False))

    def test_bad_source_is_rejected_instead_of_inventing_replacements(self):
        mutations = [lambda s: s["rules"].pop(),
                     lambda s: s["rules"][0].update(id="KZ-CASH-002"),
                     lambda s: s["rules"][0].update(visual_candidate=" "),
                     lambda s: s["rules"][0].update(do_not_flag_if=[""]),
                     lambda s: s["sources"][0].update(official_url="http://example.org/act"),
                     lambda s: s["sources"][0].update(official_url="https://user:pass@example.org/act")]
        for mutate in mutations:
            source = deepcopy(source_fixture())
            mutate(source)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                build_catalog(source)

    def test_number_alone_does_not_confirm_phrase_or_remove_rules(self):
        source = source_fixture()
        report = verify_paragraphs(source, "22. Unrelated paragraph content.\n23. Shared legal phrase.")
        self.assertEqual(len(report), 8)
        self.assertTrue(report[0]["checks"][0]["number_found"])
        self.assertFalse(report[0]["found"])
        self.assertEqual(len(build_catalog(source)["rules"]), 8)

    def test_repeated_numbers_and_multiclause_sections_use_local_blocks(self):
        source = source_fixture()
        source["rules"][0]["paragraph"] = "п. 22; п. 24"
        report = verify_paragraphs(source, "22. unrelated annex.\n23. stop.\n"
            "22. Shared legal phrase.\n24. Shared legal phrase.\n25. stop.")
        self.assertTrue(report[0]["found"])
        self.assertEqual(report[0]["checks"][0]["number_occurrences"], 2)
        self.assertEqual([c["paragraph"] for c in report[0]["checks"]], [22, 24])

    def test_shipped_catalog_contains_only_eight_non_demo_rules(self):
        catalog = json.loads((REPO / "data/rules.json").read_text(encoding="utf-8"))
        self.assertEqual({r["id"] for r in catalog["rules"]}, {f"KZ-CASH-{i:03d}" for i in range(1, 9)})
        self.assertTrue(all(r["is_demo"] is False for r in catalog["rules"]))
        gate = json.loads((REPO / "ml2/configs/rule_validation.json").read_text(encoding="utf-8"))
        self.assertEqual(gate["enabled_rule_ids"], [])
