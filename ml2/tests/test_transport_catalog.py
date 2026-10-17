import unittest
from scripts.prepare_transport_catalog import convert


def catalog():
    return dict(
        sources=[
            dict(
                id="source",
                title="Supplied source title",
                official_url="https://example.org/supplied",
            )
        ],
        rules=[
            dict(
                id="rule",
                type="Supplied rule",
                source_id="source",
                paragraph="Supplied clause",
                visual_candidate="Visible action",
                required_context=["Context must be seen"],
                do_not_flag_if=["Action is occluded"],
            )
        ],
    )


class CatalogConversionTests(unittest.TestCase):
    def test_conversion_keeps_source_clause_context_and_exclusions(self):
        converted = convert(catalog())
        rule = converted["rules"][0]
        self.assertEqual(rule["section"], "Supplied clause")
        self.assertEqual(rule["url"], "https://example.org/supplied")
        self.assertIn("Required context: Context must be seen", rule["visual_signs"])
        self.assertIn("Do not flag if: Action is occluded", rule["visual_signs"])
        self.assertTrue(converted["integration_test_only"])

    def test_unknown_clause_is_not_filled_in(self):
        source = catalog()
        source["rules"][0]["paragraph"] = None
        with self.assertRaisesRegex(ValueError, "missing"):
            convert(source)
