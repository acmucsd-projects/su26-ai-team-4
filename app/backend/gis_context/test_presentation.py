"""Small synthetic contract suite for normalization and evidence consolidation."""

from copy import deepcopy
import json
import unittest

from app.backend.building_context import valid_context
from app.backend.gis_context.export_dashboard import present_claim
from app.backend.gis_context.presentation import normalize_classification, normalize_context
from app.backend.test_building_context import claim


def normalized(*raw, conflicts=()):
    return normalize_context([present_claim(c, f"claim-{i}") for i, c in enumerate(raw)], conflicts)


def school_site(name="Example School", temporal="pre_event_reference_vintage_unverified", provider="sonoma_schools"):
    return claim("school_site" if provider == "sonoma_schools" else "site_use", "site", provider, temporal,
                 "Within mapped site: " + name, mapped_name=name, category="education", raw_value={"amenity": "school"})


def property_use(value, provider="bay_2017", temporal="pre_event_historical", multi=True):
    return claim("property_use", "parcel", provider, temporal, "Property: " + value,
                 raw_value={"DORAPPDESC": value}, spatial_evidence={"structure_association": "multi_structure" if multi else "single_structure_supported"})


class PresentationTests(unittest.TestCase):
    def test_taxonomy_subtypes_and_capitalization(self):
        cases = [("parochial school", "education", "school", "School"),
                 ("Multi-family 10 less", "residential", "multifamily_up_to_10", "Multifamily · Up to 10 units"),
                 ("STORES, 1 STORY", "commercial", "retail", "Retail"),
                 ("Office Bldgs, Low-Rise (1 to 4 Stories)", "professional_services", "low_rise_office", "Low-rise office"),
                 ("medical office", "medical", "medical_office", "Medical office"),
                 ("residential area", "residential", "residential", "Residential")]
        for value, category, subtype, label in cases:
            with self.subTest(value=value):
                self.assertEqual(normalize_classification(value), [{"category": category, "subtype": subtype, "label": label}])
        self.assertEqual(normalize_classification("Unexpected provider code")[0]["category"], "unknown")

    def test_low_rise_office_aliases_consolidate_without_losing_originals(self):
        result = normalized(property_use("Office Bldgs. Low-Rise (1 to 4 Stories)", "hcad", "event_year"),
                            property_use("Office Building", "hcad", "event_year"))
        self.assertEqual(result["statements"][0]["text"], "Low-rise office")
        self.assertEqual(len(result["contexts"]), 1)
        self.assertEqual(result["contexts"][0]["concepts"][0]["supporting_claims"], ["claim-0", "claim-1"])
        self.assertEqual([c["original_values"]["DORAPPDESC"] for c in result["claims"]],
                         ["Office Bldgs. Low-Rise (1 to 4 Stories)", "Office Building"])

    def test_mixed_uses_remain_structured_and_do_not_choose_a_winner(self):
        result = normalized(*(claim(label="Modeled use: " + value) for value in
                              ["Professional services", "Medical office", "Wholesale", "Retail"]))
        context = result["contexts"][0]
        self.assertEqual(context["category"], "mixed_use")
        self.assertEqual(len(context["concepts"]), 4)
        self.assertTrue(context["modeled"])
        self.assertEqual(context["scope"], "modeled_building")
        self.assertIn("not_event_aligned", context["qualifications"])
        self.assertIn("Mixed", result["statements"][0]["text"])
        self.assertNotIn("Wholesale; Retail", result["statements"][0]["text"])

    def test_school_corroboration_preserves_scopes_dates_and_source_independence(self):
        result = normalized(claim(label="Modeled use: School"), school_site(),
                            school_site(temporal="event_snapshot", provider="osm"),
                            school_site(temporal="current_only", provider="osm"),
                            property_use("PAROCHIAL SCHOOL", "sonoma_parcels", "current_only"))
        self.assertEqual(len(result["statements"]), 1)
        summary = result["statements"][0]
        self.assertEqual(summary["text"], "Within Example School campus")
        self.assertEqual(summary["scope"], "site")
        self.assertFalse(summary["modeled"])
        self.assertEqual(summary["corroboration_basis"], "education_category_only")
        self.assertEqual(summary["supporting_sources"], ["nsi", "osm", "sonoma"])
        self.assertEqual(set(summary["supporting_claims"] + summary["corroborating_claims"]), {f"claim-{i}" for i in range(5)})
        self.assertEqual({c["scope"] for c in result["contexts"]}, {"site", "property", "modeled_building"})
        self.assertEqual(len({c["temporal_relation"] for c in result["contexts"]}), 4)
        self.assertIn("vintage unverified", summary["temporal_label"])
        self.assertTrue(valid_context(result))

    def test_mixed_school_and_commercial_evidence_is_not_false_agreement(self):
        conflicts = [{"reason": "modeled_vs_mapped_difference", "supporting_claims": ["claim-0", "claim-2"], "resolution": "preserved_separately"}]
        result = normalized(claim(label="Modeled use: Personal/repair services"),
                            claim(label="Modeled use: School"), school_site(), conflicts=conflicts)
        self.assertEqual(len(result["statements"]), 2)
        site = next(s for s in result["statements"] if s["scope"] == "site")
        mixed = next(s for s in result["statements"] if s["scope"] == "modeled_building")
        self.assertEqual(site["corroborating_claims"], ["claim-1"])
        self.assertEqual(mixed["category"], "mixed_use")
        self.assertEqual(result["conflicts"], conflicts)
        self.assertTrue(result["notes"])

    def test_different_names_and_current_vs_historical_identities_remain_separate(self):
        result = normalized(school_site("First School"), school_site("Second School", "current_only", "osm"))
        self.assertEqual(len(result["statements"]), 2)
        self.assertIn("School-site names differ by source.", result["notes"])
        names = normalized(claim("mapped_name", "building", "osm", "event_snapshot", "Name: OLD NAME", mapped_name="OLD NAME"),
                           claim("mapped_name", "building", "osm", "current_only", "Name: ACC", mapped_name="ACC"))
        self.assertEqual([s["text"] for s in names["statements"]], ["OLD NAME", "ACC"])
        self.assertEqual(names["primary_category"], "unknown")  # Never infer use from names.
        self.assertNotEqual(names["contexts"][0]["temporal_relation"], names["contexts"][1]["temporal_relation"])

    def test_parcel_scope_timing_and_multi_structure_are_retained(self):
        result = normalized(property_use("MULTI-FAMILY 10 LESS"))
        context = result["contexts"][0]
        self.assertEqual(context["scope"], "property")
        self.assertTrue(context["multi_structure"])
        self.assertIn("multi_structure_parcel", context["qualifications"])
        self.assertEqual(context["temporal_relation"], "pre_event_historical")
        self.assertFalse(context["modeled"])
        self.assertEqual(result["statements"][0]["label"], "Property use")
        self.assertEqual(result["statements"][0]["temporal_label"], "2017 pre-event")

    def test_same_single_structure_parcel_is_not_repeated_or_counted_as_two_sources(self):
        structure = claim("structure_use", "building", "bay_2017", "pre_event_historical", "Structure: SINGLE FAMILY")
        single = normalized(structure, property_use("SINGLE FAMILY", multi=False))
        self.assertEqual(len(single["statements"]), 1)
        self.assertFalse(single["has_multiple_supporting_sources"])
        self.assertEqual(single["statements"][0]["corroboration_basis"], "single_structure_parcel_support")
        multi = normalized(structure, property_use("SINGLE FAMILY", multi=True))
        self.assertEqual(len(multi["statements"]), 2)

    def test_area_is_secondary_and_never_promoted_to_building_use(self):
        area = claim("area_use", "site", "osm", "current_only", "Within current mapped residential area: Example Neighborhood",
                     mapped_name="Example Neighborhood", raw_value={"landuse": "residential"})
        only = normalized(area)
        self.assertTrue(only["area_only"])
        self.assertEqual(only["primary_label"], "Area context")
        self.assertEqual(only["contexts"][0]["scope"], "area")
        stronger = normalized(area, property_use("SINGLE FAMILY"))
        self.assertFalse(stronger["area_only"])
        self.assertNotIn(next(s["id"] for s in stronger["statements"] if s["scope"] == "area"), stronger["primary_statement_ids"])

    def test_schema_references_determinism_and_input_preservation(self):
        raw = claim()
        original = deepcopy(raw)
        result = normalized(raw)
        self.assertEqual(raw, original)
        self.assertEqual(normalized(raw), json.loads(json.dumps(result)))
        self.assertTrue(valid_context(result))
        self.assertTrue(valid_context(normalized()))
        result["statements"][0]["supporting_claims"] = ["missing-claim"]
        self.assertFalse(valid_context(result))


if __name__ == "__main__":
    unittest.main()
