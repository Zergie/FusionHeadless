from __future__ import annotations

from types import SimpleNamespace
import unittest

from context import FusionContext
from mcp.tools.search_components import mcp_search_components


class Collection:
    def __init__(self, *items):
        self.items = items
        self.count = len(items)

    def item(self, index):
        return self.items[index]


def occurrence(name, *, material=None, occurrence_name=None):
    return SimpleNamespace(
        name=occurrence_name or name,
        component=SimpleNamespace(
            name=name,
            material=SimpleNamespace(name=material) if material else None,
        ),
    )


def document(name, identity, *occurrences):
    design = SimpleNamespace(rootComponent=SimpleNamespace(allOccurrences=occurrences))
    return SimpleNamespace(
        name=name, dataFile=SimpleNamespace(id=identity), products=Collection(design),
    )


class SearchComponentsTests(unittest.TestCase):
    def setUp(self):
        self.active = document("Active v2", "active-id", occurrence("Active Bolt"))
        self.other = document("Assembly v127", "assembly-id", occurrence("Other Bolt"))
        self.app = SimpleNamespace(
            activeDocument=self.active, documents=Collection(self.active, self.other),
        )

    def search(self, **query):
        return mcp_search_components(query, FusionContext(self.app, None, None))

    def test_document_selector_resolves_id_and_versionless_name_without_activation(self):
        for selector in ("assembly-id", " assembly ", "ASSEMBLY v3"):
            with self.subTest(selector=selector):
                result = self.search(query="Bolt", document=selector)
                self.assertEqual(result["resolved_document"], "Assembly v127")
                self.assertEqual(result["matches"][0]["name"], "Other Bolt")
                self.assertIs(self.app.activeDocument, self.active)
        self.assertEqual(self.search(query="Bolt")["resolved_document"], "Active v2")

    def test_document_selector_rejects_missing_ambiguous_and_invalid_values(self):
        duplicate = document("Assembly v8", "duplicate-id")
        self.app.documents = Collection(self.active, self.other, duplicate)
        for selector, message in (("missing", "not found"), ("Assembly", "Ambiguous"),
                                  (" ", "non-empty string"), (4, "non-empty string")):
            with self.subTest(selector=selector), self.assertRaisesRegex(ValueError, message):
                self.search(query="Bolt", document=selector)
        self.assertEqual(self.search(query="Bolt", document="assembly-id")["total_component_matches"], 1)

    def test_document_id_takes_priority_over_matching_name(self):
        self.app.documents = Collection(document("assembly-id", "name-id"), self.other)
        self.assertEqual(self.search(query="Bolt", document="assembly-id")["resolved_document"], "Assembly v127")

    def test_material_filter_uses_component_material_and_name_fallback(self):
        self.app.activeDocument = document(
            "Parts", "parts-id",
            occurrence("Bolt(1)", material="Steel"),
            occurrence("Bolt(2)", material="Brass"),
            occurrence("Bolt Stainless Steel A2 v3:1"),
            occurrence("Bolt unknown"),
        )
        result = self.search(query="Bolt", exclude_material=" steel ")
        self.assertEqual(result["total_component_scanned"], 4)
        self.assertEqual(result["total_component_matches"], 2)
        self.assertEqual(result["exclude_material"], "steel")
        self.assertEqual(result["matches"], [
            {"name": "Bolt", "material": "Brass", "count": 1},
            {"name": "Bolt unknown", "material": None, "count": 1},
        ])
        result = self.search(query="Stainless")
        self.assertEqual(result["matches"][0]["material"], "Stainless Steel A2")

    def test_exact_and_regex_search_normalize_both_component_and_occurrence_names(self):
        self.app.activeDocument = document(
            "Parts", "parts-id",
            occurrence("Bolt Steel Grade 8 v3:2"),
            occurrence("Different", occurrence_name="Bolt v12:1"),
        )
        for options in ({"exact": True}, {"use_regex": True}):
            with self.subTest(options=options):
                query = " ^bolt$ " if options.get("use_regex") else " bolt "
                result = self.search(query=query, **options)
                self.assertEqual(result["total_component_matches"], 2)
                self.assertEqual(result["unique_component_matches"], 2)

    def test_invalid_filters_raise_contextual_errors_and_blank_exclusion_is_ignored(self):
        for query, message in (
            ({"query": " "}, "non-empty string"),
            ({"query": "[", "use_regex": True}, "Invalid regex pattern"),
            ({"query": "Bolt", "exclude_material": "["}, "exclude_material"),
            ({"query": "Bolt", "exclude_material": 2}, "exclude_material"),
            ({"query": "Bolt", "exact": "true"}, "boolean"),
            ({"query": "Bolt", "use_regex": 1}, "boolean"),
        ):
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, message):
                self.search(**query)
        result = self.search(query="Bolt", exclude_material=" ")
        self.assertIsNone(result["exclude_material"])
        self.assertEqual(result["total_component_matches"], 1)

    def test_missing_document_or_design_fails_clearly(self):
        self.app.activeDocument = None
        with self.assertRaisesRegex(ValueError, "No document"):
            self.search(query="Bolt")
        self.app.activeDocument = SimpleNamespace(name="Drawing", products=Collection())
        with self.assertRaisesRegex(ValueError, "Fusion design.*Drawing"):
            self.search(query="Bolt")

    def test_canonical_product_is_cast_to_design(self):
        product = object()
        design = self.other.products.item(0)
        self.other.products = SimpleNamespace(itemByProductType=lambda name: product)

        def cast(candidate):
            self.assertIs(candidate, product)
            return design

        adsk = SimpleNamespace(fusion=SimpleNamespace(Design=SimpleNamespace(cast=cast)))
        result = mcp_search_components(
            {"query": "Bolt", "document": "assembly-id"}, FusionContext(self.app, None, adsk),
        )
        self.assertEqual(result["matches"][0]["name"], "Other Bolt")

    def test_group_counts_and_material_survive_normalized_display_names(self):
        self.app.activeDocument = document(
            "Parts", "parts-id", occurrence("Bolt(1)"),
            occurrence("Bolt(2)", material="Brass"), occurrence("Washer", material="Steel"),
        )
        result = self.search(query=".*", use_regex=True)
        self.assertEqual(result["total_component_matches"], 3)
        self.assertEqual(result["unique_component_matches"], 2)
        self.assertEqual(result["matches"], [
            {"name": "Bolt", "material": "Brass", "count": 2},
            {"name": "Washer", "material": "Steel", "count": 1},
        ])


if __name__ == "__main__":
    unittest.main()
