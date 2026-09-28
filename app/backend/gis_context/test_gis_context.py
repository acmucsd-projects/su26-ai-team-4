"""Synthetic geometry tests; none of these fixtures are Harvey audit evidence."""

from dataclasses import replace
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from shapely.geometry import Point, Polygon, box, mapping

from .audit import FLAGS, PROVIDERS, aggregate, build_row, empty_report, run_audit, select_qa
from .cache import CachedClient, canonical
from .geometry import Projection, SCENE_ID, load_scene, overlap, utc_timestamp
from .matching import footprint_matches, nsi_matches, parcel_matches, poi_matches, site_matches
from .models import Feature, Match, Source
from .local_providers import LOCAL, fetch_local, local_features, local_claims
from .scenes import SCENE_COUNTS, SCENE_PROVIDERS
from .normalize import compare_claims, hcad_claims, nsi_claims, nsi_occupancy, osm_claims, property_category
from .providers import fetch_hcad, fetch_nsi, geojson_features, osm_features, overpass_query, source_info, HCAD_FIELDS
from .report import write_reports
from .review import apply_review, evidence_sha256


def feature(record_id="1", geometry=None, properties=None, provider="osm_current"):
    return Feature(record_id, geometry if geometry is not None else box(0, 0, 10, 10),
                   properties or {}, source_info(provider, "2026-09-28"))


def accepted(relationship="footprint", confidence="strong", **evidence):
    return Match("1", relationship, True, confidence, "test", evidence)


class GeometryTests(unittest.TestCase):
    def test_metric_projection_and_roundtrip(self):
        # Synthetic Houston location, not the unknown Harvey scene location.
        geo = box(-95.4000, 29.7500, -95.3999, 29.7501)
        projection = Projection.for_geometry(geo)
        self.assertEqual(projection.epsg, 32615)
        metric = projection.project(geo)
        self.assertGreater(metric.area, 90)
        self.assertLess(metric.area, 120)
        self.assertLess(projection.unproject(metric).hausdorff_distance(geo), 1e-9)

    def test_overlap_metrics(self):
        result = overlap(box(0, 0, 10, 10), box(5, 0, 15, 10))
        self.assertEqual(result["intersection_m2"], 50)
        self.assertEqual(result["xbd_coverage"], .5)
        self.assertAlmostEqual(result["iou"], 1 / 3)
        self.assertEqual(result["centroid_distance_m"], 5)

    def test_timestamp_requires_timezone(self):
        self.assertEqual(utc_timestamp("2017-09-01T12:00:00-05:00"), "2017-09-01T17:00:00Z")
        for value in (None, "2017-08-25", "2017-08-25T12:00:00"):
            with self.assertRaises(ValueError):
                utc_timestamp(value)

    def test_raw_uid_join_and_missing_geometry(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {"scene_id": SCENE_ID, "buildings": [{"id": str(i), "uid": str(i)} for i in range(76)]}
            raw = {"metadata": {"capture_date": "2017-09-01T12:00:00Z"}, "features": {"lng_lat": [
                {"properties": {"uid": str(i)}, "wkt": box(-95.4 + i * .0001, 29.75, -95.39995 + i * .0001, 29.75005).wkt}
                for i in reversed(range(76))]}}
            manifest_path, label_path = root / "scene.json", root / (SCENE_ID + "_post_disaster.json")
            manifest_path.write_text(json.dumps(manifest))
            label_path.write_text(json.dumps(raw))
            scene = load_scene(manifest_path, label_path)
            self.assertEqual(len(scene.metric), 76)
            self.assertAlmostEqual(scene.geographic["0"].bounds[0], -95.4)
            raw["features"]["lng_lat"].pop()
            label_path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "UIDs"):
                load_scene(manifest_path, label_path)


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.buildings = {"a": box(0, 0, 10, 10), "b": box(20, 0, 30, 10)}

    def test_strong_and_moderate_footprints(self):
        strong = footprint_matches(self.buildings, [feature()])["a"][0]
        self.assertTrue(strong.accepted)
        self.assertEqual(strong.spatial_confidence, "strong")
        moderate = footprint_matches(self.buildings, [feature(geometry=box(5, 0, 15, 10))])["a"][0]
        self.assertTrue(moderate.accepted)
        self.assertEqual(moderate.spatial_confidence, "moderate")

    def test_close_footprint_competitors_rejected(self):
        matches = footprint_matches(self.buildings, [feature("1"), feature("2", box(.1, 0, 10.1, 10))])["a"]
        self.assertFalse(any(m.accepted for m in matches))
        self.assertTrue(matches[0].ambiguous)

    def test_one_external_footprint_cannot_identify_two_roofs(self):
        buildings = {"a": box(0, 0, 10, 10), "b": box(10, 0, 20, 10)}
        result = footprint_matches(buildings, [feature(geometry=box(0, 0, 20, 10))])
        self.assertFalse(any(m.accepted for ms in result.values() for m in ms))

    def test_poi_containment_and_boundary(self):
        inside = poi_matches(self.buildings, [feature(geometry=Point(5, 5))])["a"][0]
        self.assertTrue(inside.accepted)
        self.assertEqual(inside.spatial_confidence, "strong")
        boundary = poi_matches(self.buildings, [feature(geometry=Point(0, 5))])["a"][0]
        self.assertTrue(boundary.accepted)
        self.assertEqual(boundary.spatial_confidence, "moderate")

    def test_near_poi_uniqueness_and_distance(self):
        near = poi_matches(self.buildings, [feature(geometry=Point(-4, 5))])["a"][0]
        self.assertTrue(near.accepted)
        between = poi_matches(self.buildings, [feature(geometry=Point(15, 5))])
        self.assertFalse(any(m.accepted for ms in between.values() for m in ms))
        self.assertTrue(between["a"][0].ambiguous)
        far = poi_matches(self.buildings, [feature(geometry=Point(-8, 5))])["a"][0]
        self.assertFalse(far.accepted)
        self.assertEqual(poi_matches(self.buildings, [feature(geometry=Point(-16, 5))])["a"], [])

    def test_poi_inside_overlapping_buildings_rejected(self):
        buildings = {"a": box(0, 0, 10, 10), "b": box(4, 4, 14, 14)}
        matches = poi_matches(buildings, [feature(geometry=Point(5, 5))])
        self.assertTrue(all(m.ambiguous and not m.accepted for ms in matches.values() for m in ms))

    def test_parcel_single_and_multi_structure(self):
        parcel = feature(geometry=box(-1, -1, 11, 11), properties={"BUILDCOUNT": 1}, provider="hcad")
        result = parcel_matches(self.buildings, [parcel])["a"][0]
        self.assertTrue(result.evidence["building_promotion_allowed"])
        parcel.geometry = box(-1, -1, 31, 11)
        result = parcel_matches(self.buildings, [parcel])["a"][0]
        self.assertEqual(result.evidence["structure_association"], "multi_structure")
        self.assertFalse(result.evidence["building_promotion_allowed"])

    def test_parcel_unknown_count_and_competing_parcels(self):
        parcel = feature(geometry=box(-1, -1, 11, 11), provider="hcad")
        match = parcel_matches(self.buildings, [parcel])["a"][0]
        self.assertEqual(match.evidence["structure_association"], "structure_count_unknown")
        other = feature("2", parcel.geometry, provider="hcad")
        matches = parcel_matches(self.buildings, [parcel, other])["a"]
        self.assertTrue(all(m.ambiguous and not m.accepted for m in matches))

    def test_site_membership_preserves_scope(self):
        site = feature(geometry=box(-1, -1, 31, 11), properties={"amenity": "school", "name": "Synthetic School"})
        match = site_matches(self.buildings, [site])["a"][0]
        claims = osm_claims(site, match)
        self.assertTrue(all(c.scope == "site" and not c.critical_facility for c in claims))
        self.assertIn("Within", claims[0].label)

    def test_nsi_inside_and_near(self):
        rows = [feature("inside", Point(5, 5), {"occtype": "RES1-1SNB"}, "nsi"),
                feature("near", Point(-1, 5), {"occtype": "COM6"}, "nsi")]
        matches = nsi_matches(self.buildings, rows)["a"]
        self.assertEqual([m.record_id for m in matches if m.accepted], ["inside"])

    def test_stacked_nsi_preserves_mixed_occupancy(self):
        features = [feature("1", Point(5, 5), {"occtype": "RES3A", "ftprntid": "xyz", "ftprntsrc": "NGA"}, "nsi"),
                    feature("2", Point(6, 5), {"occtype": "COM1", "ftprntid": "xyz", "ftprntsrc": "NGA"}, "nsi")]
        matches = nsi_matches(self.buildings, features)["a"]
        self.assertTrue(all(m.accepted for m in matches))
        claims = [nsi_claims(f, m)[0] for f, m in zip(features, matches)]
        self.assertEqual({c.category for c in claims}, {"multifamily", "commercial_retail"})
        self.assertEqual(compare_claims(claims), [])

    def test_unlinked_nsi_records_are_ambiguous(self):
        records = [feature("1", Point(2, 2), provider="nsi"), feature("2", Point(8, 8), provider="nsi")]
        self.assertTrue(all(m.ambiguous and not m.accepted for m in nsi_matches(self.buildings, records)["a"]))

    def test_shared_nsi_footprint_across_roofs_rejected(self):
        records = [feature("1", Point(5, 5), {"ftprntid": "f", "ftprntsrc": "NGA"}, "nsi"),
                   feature("2", Point(25, 5), {"ftprntid": "f", "ftprntsrc": "NGA"}, "nsi")]
        results = nsi_matches(self.buildings, records)
        self.assertFalse(any(m.accepted for matches in results.values() for m in matches))


class SemanticTests(unittest.TestCase):
    def test_real_hcad_bank_and_compound_garage_description(self):
        self.assertEqual(property_category("Bank"), "office_professional")
        self.assertEqual(property_category("Auto Service Garage,Warehouse - Metallic"), "mixed")

    def test_real_osm_duplicate_dentist_tags_preserve_one_claim(self):
        claims = osm_claims(feature(properties={"amenity": "dentist", "healthcare": "dentist", "name": "Fixture"}), accepted("place"))
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].raw_value, {"amenity": "dentist", "healthcare": "dentist", "name": "Fixture"})

    def test_residential_landuse_is_area_context_not_building_use(self):
        claims = osm_claims(feature(properties={"landuse": "residential", "name": "Fixture Neighbourhood"}), accepted("site"))
        self.assertEqual(claims[0].kind, "area_use")
        self.assertEqual(claims[0].scope, "site")
        self.assertIn("residential area", claims[0].label)

    def test_nsi_taxonomy_and_unknown(self):
        for code, expected in {"RES1-2SWB": "residential", "RES3F": "multifamily", "RES4": "lodging", "RES6": "medical",
                               "COM1": "commercial_retail", "COM6": "medical", "COM7": "medical", "GOV2": "emergency_services",
                               "EDU1": "education", "EDU2": "education", "RES10": "unknown", "nonsense": "unknown"}.items():
            self.assertEqual(nsi_occupancy(code)[0], expected)

    def test_nsi_is_modeled_not_critical_or_exact_year(self):
        record = feature(properties={"occtype": "COM6", "med_yr_blt": 1970}, provider="nsi")
        claim = nsi_claims(record, accepted("nsi_structure"))[0]
        self.assertTrue(claim.source.modeled)
        self.assertFalse(claim.critical_facility)
        self.assertNotIn("1970", json.dumps(claim.to_dict()))
        self.assertIn("Modeled use", claim.label)

    def test_parcel_property_not_outbuilding_use(self):
        record = feature(properties={"LANDUSE_DS": "Residential", "BLDTYPE_DS": "Single family residential", "Tax_Year": "2017"}, provider="hcad")
        match = accepted("parcel", structure_association="multi_structure", building_promotion_allowed=False)
        claims = hcad_claims(record, match)
        self.assertTrue(all(c.scope == "parcel" for c in claims))
        self.assertTrue(all(c.ambiguity for c in claims))

    def test_unknown_property_codes_not_guessed(self):
        self.assertEqual(property_category("A1"), "unknown")
        self.assertEqual(property_category("NONRESIDENTIAL"), "unknown")
        self.assertEqual(property_category("Single Family Residential"), "residential")

    def test_critical_requires_explicit_strong_mapped_evidence(self):
        record = feature(properties={"amenity": "hospital"})
        self.assertTrue(osm_claims(record, accepted("place"))[0].critical_facility)
        self.assertFalse(osm_claims(record, accepted("place", "moderate"))[0].critical_facility)
        self.assertFalse(osm_claims(feature(properties={"building": "hospital"}), accepted())[0].critical_facility)
        self.assertFalse(osm_claims(feature(properties={"amenity": "school"}), accepted())[0].critical_facility)

    def test_inactive_and_vacant_places_not_active_uses(self):
        self.assertEqual(osm_claims(feature(properties={"shop": "vacant"}), accepted("place")), [])
        claims = osm_claims(feature(properties={"amenity": "hospital", "disused": "yes"}), accepted("place"))
        self.assertEqual(claims, [])

    def test_temporal_and_name_changes_preserved(self):
        old = feature(properties={"amenity": "school", "name": "Old School"}, provider="osm_historical")
        old.source = replace(old.source, snapshot="2017-09-01T00:00:00Z")
        new = feature(properties={"amenity": "school", "name": "New School"})
        claims = osm_claims(old, accepted("place")) + osm_claims(new, accepted("place"))
        self.assertEqual(claims[0].source.temporal_status, "event_snapshot")
        self.assertEqual(claims[1].source.temporal_status, "current_only")
        self.assertEqual(compare_claims(claims)[0]["reason"], "historical_current_difference")

    def test_modeled_conflict_but_no_cross_scope_false_conflict(self):
        modeled = nsi_claims(feature(properties={"occtype": "RES1"}, provider="nsi"), accepted("nsi_structure"))[0]
        mapped = osm_claims(feature(properties={"building:use": "hospital"}), accepted())[0]
        self.assertEqual(compare_claims([modeled, mapped])[0]["reason"], "modeled_vs_mapped_difference")
        mapped.scope = "parcel"
        self.assertEqual(compare_claims([modeled, mapped]), [])


class ProviderTests(unittest.TestCase):
    def test_queries_are_bulk_all_tags_and_historical(self):
        query = overpass_query((-95.4, 29.7, -95.3, 29.8), "2017-09-01T12:00:00Z")
        self.assertIn('[date:"2017-09-01T12:00:00Z"]', query)
        self.assertIn("nwr", query)
        self.assertIn("nwr(29.7,-95.4,29.8,-95.3);out meta geom;", query)
        self.assertNotIn("[date:", overpass_query((-95.4, 29.7, -95.3, 29.8), None))

    def test_real_scene_query_does_not_expand_entire_highway_routes(self):
        query = overpass_query((-95.4, 29.7, -95.3, 29.8), None)
        self.assertNotIn(">>", query)
        self.assertNotIn("rel(b", query)
        self.assertIn("out meta geom", query)

    def test_real_capture_precision_is_adapted_to_overpass_seconds(self):
        capture = "2017-08-31T17:38:50.685Z"
        query = overpass_query((-95.4, 29.7, -95.3, 29.8), capture)
        self.assertIn('[date:"2017-08-31T17:38:50Z"]', query)
        self.assertEqual(utc_timestamp(capture), "2017-08-31T17:38:50.685000Z")

    def test_nsi_ring_not_four_number_bbox(self):
        class Client:
            def get_json(self, url, **kwargs):
                self.params = kwargs["params"]
                return {"type": "FeatureCollection", "features": []}
        client = Client()
        fetch_nsi(client, (-95.4, 29.7, -95.3, 29.8), "test")
        self.assertEqual(len(client.params["bbox"].split(",")), 10)

    def test_hcad_schema_validation_and_truncation(self):
        class Client:
            def get_json(self, url, **kwargs):
                if url.endswith("/query"):
                    return {"type": "FeatureCollection", "features": [], "exceededTransferLimit": True}
                return {"name": "HCAD Parcels 2017", "fields": [{"name": k} for k in HCAD_FIELDS]}
        with self.assertRaisesRegex(ValueError, "truncated"):
            fetch_hcad(Client(), (-95.4, 29.7, -95.3, 29.8), "test")

    def test_hcad_record_year_not_blindly_event_aligned(self):
        payload = {"type": "FeatureCollection", "features": [{"geometry": mapping(box(-95.4, 29.7, -95.399, 29.701)),
                   "properties": {"OBJECTID": 1, "Tax_Year": "2020"}}]}
        records, issues = geojson_features(payload, source_info("hcad", "test"), Projection(32615))
        self.assertFalse(issues)
        self.assertEqual(records[0].source.temporal_status, "tax_year_unverified")

    def test_osm_multipolygon_hole_and_named_node(self):
        def geom(coords):
            return [{"lon": x, "lat": y} for x, y in coords]
        outer = [(-95.4, 29.7), (-95.399, 29.7), (-95.399, 29.701), (-95.4, 29.701), (-95.4, 29.7)]
        inner = [(-95.3998, 29.7002), (-95.3992, 29.7002), (-95.3992, 29.7008), (-95.3998, 29.7008), (-95.3998, 29.7002)]
        payload = {"elements": [{"type": "relation", "id": 1, "version": 2, "timestamp": "2017-01-01T00:00:00Z",
                    "tags": {"type": "multipolygon", "amenity": "school"}, "members": [
                        {"type": "way", "role": "outer", "geometry": geom(outer)},
                        {"type": "way", "role": "inner", "geometry": geom(inner)}]},
                   {"type": "node", "id": 2, "lat": 29.7, "lon": -95.4, "tags": {"shop": "books", "name": "Fixture"}}]}
        layers, issues = osm_features(payload, source_info("osm_current", "test"), Projection(32615))
        self.assertFalse(issues)
        self.assertEqual(len(layers["site"][0].geometry.interiors), 1)
        self.assertEqual(len(layers["place"]), 1)

    def test_bad_relation_not_replaced_with_bbox(self):
        payload = {"elements": [{"type": "relation", "id": 1, "tags": {"type": "site", "amenity": "school"}, "members": []}]}
        layers, issues = osm_features(payload, source_info("osm_current", "test"), Projection(32615))
        self.assertEqual(layers["site"], [])
        self.assertEqual(len(issues), 1)

    def test_duplicate_provider_ids_do_not_keep_arbitrary_winner(self):
        record = {"geometry": mapping(Point(-95.4, 29.7)), "properties": {"fd_id": 1, "occtype": "RES1"}}
        records, issues = geojson_features({"type": "FeatureCollection", "features": [record, record]},
                                          source_info("nsi", "test"), Projection(32615))
        self.assertFalse(records)
        self.assertEqual(len(issues), 2)

    def test_cache_replay_and_integrity(self):
        with TemporaryDirectory() as temporary:
            client = CachedClient(Path(temporary))
            kwargs = {"provider": "fixture", "release": "test"}
            with self.assertRaises(FileNotFoundError):
                client.get_json("https://example.invalid", **kwargs)
            request = {"provider": "fixture", "release": "test", "query_bbox_wgs84": None, "snapshot": None,
                       "query_schema_version": 1, "url": "https://example.invalid", "params": {}, "form": None}
            directory = Path(temporary) / "fixture" / hashlib.sha256(canonical(request)).hexdigest()
            directory.mkdir(parents=True)
            raw = b'{"features": []}'
            (directory / "response.json").write_bytes(raw)
            (directory / "metadata.json").write_text(json.dumps({"request": request, "sha256": hashlib.sha256(raw).hexdigest()}))
            self.assertEqual(client.get_json("https://example.invalid", **kwargs), {"features": []})
            (directory / "response.json").write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, "integrity"):
                client.get_json("https://example.invalid", **kwargs)


class LocalProviderTests(unittest.TestCase):
    def source(self, provider):
        config = LOCAL[provider]
        return Source(provider, config['name'], config['release'], '2026-09-28', config['temporal'], config['credit'], config['terms'], config['url'])

    def test_local_schema_dates_and_truncation(self):
        config = LOCAL['sonoma_schools']
        schema = {'name': config['name'], 'fields': [{'name': f} for f in config['fields']],
                  'maxRecordCount': 1000, 'editingInfo': {'dataLastEditDate': 1654891237240}}
        client = Mock()
        client.get_json.side_effect = [schema, {'type': 'FeatureCollection', 'features': []}]
        _, source = fetch_local(client, 'sonoma_schools', (-123, 38, -122, 39), '2026-09-28')
        self.assertIn('2022-06-10', source.release)
        self.assertEqual(source.temporal_status, 'pre_event_reference_vintage_unverified')
        for bad in ({'features': [], 'exceededTransferLimit': True}, {'features': [{}] * 1000}):
            client.get_json.side_effect = [schema, bad]
            with self.assertRaisesRegex(ValueError, 'truncated'):
                fetch_local(client, 'sonoma_schools', (-123, 38, -122, 39), '2026-09-28')
        client.get_json.side_effect = [{**schema, 'fields': []}]
        with self.assertRaisesRegex(ValueError, 'schema'):
            fetch_local(client, 'sonoma_schools', (-123, 38, -122, 39), '2026-09-28')

    def test_local_counts_and_literal_descriptions(self):
        for provider, fields, count, description in [
            ('bay_2017', {'BLDCNT': 1}, 1, {'DORAPPDESC': 'MOBILE HOME'}),
            ('sonoma_parcels', {'BuildingPrimaryCount': 1, 'BuildingSecondaryCount': 2}, 3, {'UseCodeDescription': 'RURAL RES/SINGLE RES'}),
            ('sonoma_parcels', {'BuildingPrimaryCount': 1, 'BuildingSecondaryCount': None}, None, {'UseCodeDescription': 'RURAL RES SFD W/GRANNY UNIT'}),
        ]:
            payload = {'type': 'FeatureCollection', 'features': [{'geometry': mapping(box(-122.74, 38.49, -122.739, 38.491)),
                       'properties': {'OBJECTID': 1, **fields, **description}}]}
            features, issues = local_features(payload, self.source(provider), Projection(32610))
            self.assertEqual(issues, [])
            self.assertEqual(features[0].properties['BUILDCOUNT'], count)
            claims = local_claims(features[0], accepted('parcel', building_promotion_allowed=False, structure_association='multi_structure'))
            self.assertEqual([(c.scope, c.category) for c in claims], [('parcel', 'residential')])
            self.assertEqual(claims[0].raw_value, description)
        for provider, field, value in [('bay_2017', 'DORAPPDESC', 'COUNTY'), ('sonoma_parcels', 'UseCodeDescription', 'RURAL RES/VACANT HOMESITE')]:
            f = Feature('1', box(0, 0, 10, 10), {field: value}, self.source(provider))
            self.assertEqual(local_claims(f, accepted('parcel')), [])

    def test_school_property_is_shared_site_and_never_verified_event_or_critical(self):
        f = Feature('1', box(-5, -5, 40, 20), {'SCHOOLNAME': 'Fixture combined school property'}, self.source('sonoma_schools'))
        roofs = {'a': box(0, 0, 10, 10), 'b': box(20, 0, 30, 10)}
        matches = site_matches(roofs, [f])
        statuses = {p: {'status': 'complete'} for p in SCENE_PROVIDERS['santa-rosa-wildfire_00000014']}
        for uid in roofs:
            claims = local_claims(f, matches[uid][0])
            row = build_row({'id': uid, 'uid': uid}, None, claims, [], statuses)
            self.assertTrue(row['flags']['school_site_context'])
            self.assertTrue(row['flags']['unverified_historical_reference_context'])
            self.assertFalse(row['flags']['critical_facility'])
            self.assertFalse(row['flags']['event_or_pre_event_context'])
            self.assertFalse(row['flags']['direct_building_place_context'])

    def test_duplin_parcel_model_codes_are_not_normalized_as_property_use(self):
        config = LOCAL['duplin_parcels']
        self.assertEqual(config['temporal'], 'current_only')
        self.assertNotIn('Name1', config['fields'])
        self.assertNotIn('Name2', config['fields'])
        schema = {'name': config['name'], 'fields': [{'name': f} for f in config['fields']]}
        client = Mock()
        client.get_json.side_effect = [schema, {'type': 'FeatureCollection', 'features': []}]
        _, source = fetch_local(client, 'duplin_parcels', (-78, 34, -77, 35), '2026-09-28')
        self.assertEqual(source.temporal_status, 'current_only')
        f = Feature('1', box(0, 0, 10, 10),
                    {'ValuationModel': '2', 'NeighborhoodName': 'Fixture subdivision'}, source)
        self.assertEqual(local_claims(f, accepted('parcel')), [])

    def test_bay_pre_event_structure_claim_can_be_held_without_losing_property_context(self):
        f = Feature('1', box(0, 0, 10, 10), {'DORAPPDESC': 'SINGLE FAMILY'}, self.source('bay_2017'))
        claims = local_claims(f, accepted('parcel', building_promotion_allowed=True))
        statuses = {p: {'status': 'complete'} for p in SCENE_PROVIDERS['hurricane-michael_00000247']}
        rows = [build_row({'id': 'a', 'uid': 'a'}, None, claims, [], statuses)]
        report = {'status': 'awaiting_manual_qa', 'input_sha256': {}, 'cache_entries': [], 'providers': statuses,
                  'buildings': rows, 'metrics': aggregate(rows), 'source_contribution': {}, 'provider_overlap': {}, 'qa': select_qa(rows)}
        review = {'input_sha256': {}, 'cache_response_sha256': {}, 'evidence_sha256': evidence_sha256(report), 'reviewed_uids': ['a'],
                  'decision': 'fixture only', 'claim_actions': [{'uid': 'a', 'provider': 'bay_2017', 'record_id': '1', 'kind': 'structure_use',
                  'action': 'withhold_claim', 'reason': 'Unlabeled competing roof outside the image.'}]}
        result = apply_review(report, review)
        flags = result['buildings'][0]['flags']
        self.assertTrue(flags['pre_event_aligned_useful_context'])
        self.assertFalse(flags['event_aligned_useful_context'])
        self.assertTrue(flags['parcel_only_context'])
        self.assertFalse(flags['direct_building_place_context'])
        self.assertEqual([c['displayable'] for c in result['buildings'][0]['claims']], [True, False])

    def test_osm_education_office_remains_noncritical_place(self):
        claims = osm_claims(feature(properties={'office': 'educational_institution', 'name': 'Fixture Prep'}), accepted('place', confidence='moderate'))
        self.assertEqual([(c.category, c.scope, c.critical_facility) for c in claims], [('education', 'place', False)])


class ReportingTests(unittest.TestCase):
    def test_florence_uses_duplin_and_global_provider_configuration(self):
        scene_id = "hurricane-florence_00000459"
        self.assertEqual(SCENE_COUNTS[scene_id], 56)
        providers = SCENE_PROVIDERS[scene_id]
        self.assertEqual(providers, ("duplin_parcels", "nsi", "osm_historical", "osm_current"))
        statuses = {p: {"status": "complete"} for p in providers}
        row = build_row({"id": "a", "uid": "a"}, None, [], [], statuses)
        self.assertIn("local_parcel_match", row["flags"])
        self.assertFalse(any(key.startswith("hcad_") for key in row["flags"]))

    def test_socal_uses_historical_current_osm_and_nsi_only(self):
        scene_id = "socal-fire_00000663"
        self.assertEqual(SCENE_COUNTS[scene_id], 48)
        providers = SCENE_PROVIDERS[scene_id]
        self.assertEqual(providers, ("osm_historical", "osm_current", "nsi"))
        statuses = {p: {"status": "complete"} for p in providers}
        row = build_row({"id": "a", "uid": "a"}, None, [], [], statuses)
        self.assertFalse(any(key.startswith("local_") for key in row["flags"]))
        self.assertFalse(any(key.startswith("hcad_") for key in row["flags"]))

    def test_rows_without_a_local_provider_omit_local_metrics(self):
        statuses = {p: {"status": "complete"} for p in ("nsi", "osm_historical", "osm_current")}
        row = build_row({"id": "a", "uid": "a"}, None, [], [], statuses)
        self.assertFalse(any(key.startswith("local_") for key in row["flags"]))

    def review_fixture(self):
        statuses = {p: {"status": "complete"} for p in PROVIDERS}
        modeled = nsi_claims(feature(provider="nsi", properties={"occtype": "RES1"}), accepted("nsi_structure"))
        dental = osm_claims(feature(properties={"amenity": "dentist", "name": "Old fixture name"}), accepted("place"))
        rows = [build_row({"id": "a", "uid": "a"}, None, modeled, [], statuses),
                build_row({"id": "b", "uid": "b"}, None, dental, [], statuses)]
        report = {"status": "awaiting_manual_qa", "input_sha256": {"label": "fixture"},
                  "cache_entries": [{"request": {"provider": "nsi"}, "sha256": "fixture"}],
                  "providers": statuses, "buildings": rows, "metrics": aggregate(rows),
                  "source_contribution": {}, "provider_overlap": {}, "qa": select_qa(rows)}
        review = {"input_sha256": report["input_sha256"], "cache_response_sha256": {"nsi": "fixture"},
                  "evidence_sha256": evidence_sha256(report),
                  "reviewed_uids": ["a", "b"], "decision": "fixture only", "claim_actions": [
                      {"uid": "a", "provider": "nsi", "record_id": "1", "action": "withhold_claim", "reason": "source footprint mismatch"},
                      {"uid": "b", "provider": "osm_current", "record_id": "1", "action": "withhold_name", "reason": "stale name"}]}
        return report, review

    def test_real_qa_holds_recompute_coverage_and_preserve_raw_claims(self):
        report, review = self.review_fixture()
        result = apply_review(report, review)
        self.assertEqual(result["metrics"]["combined_displayable_context"]["count"], 1)
        self.assertEqual(result["pre_qa_metrics"]["combined_displayable_context"]["count"], 2)
        self.assertFalse(result["buildings"][0]["claims"][0]["displayable"])
        self.assertEqual(result["source_contribution"]["nsi"]["displayable_buildings"], 0)
        dental = result["buildings"][1]["claims"][0]
        self.assertEqual(dental["raw_value"]["name"], "Old fixture name")
        self.assertIsNone(dental["mapped_name"])
        self.assertNotIn("Old fixture name", dental["label"])
        self.assertTrue(dental["displayable"])
        self.assertTrue(report["buildings"][0]["claims"][0]["displayable"])

    def test_explicit_partial_scope_can_review_complete_source_claims_only(self):
        report, review = self.review_fixture()
        report["providers"]["duplin_parcels"] = {"status": "partial"}
        report["status"] = "partial_provider_data"
        for row in report["buildings"]:
            row["evaluation_status"] = "partially_evaluated"
        review["excluded_providers"] = ["duplin_parcels"]
        review["evidence_sha256"] = evidence_sha256(report)
        result = apply_review(report, review)
        self.assertEqual(result["status"], "reviewed_with_findings_partial_scope")
        self.assertEqual(result["qa"]["excluded_providers"], ["duplin_parcels"])
        review["excluded_providers"] = []
        with self.assertRaisesRegex(ValueError, "exclude exactly"):
            apply_review(report, review)

    def test_real_qa_cannot_be_reused_after_inputs_or_provider_data_change(self):
        report, review = self.review_fixture()
        for key in ("input_sha256", "cache_response_sha256"):
            changed = deepcopy(review)
            changed[key] = {"different": "data"}
            with self.assertRaisesRegex(ValueError, "hashes differ"):
                apply_review(report, changed)
        changed = deepcopy(review)
        changed["reviewed_uids"] = ["a"]
        with self.assertRaisesRegex(ValueError, "all scene UIDs"):
            apply_review(report, changed)
        changed_report = deepcopy(report)
        changed_report["buildings"][0]["claims"][0]["label"] = "Changed normalization"
        with self.assertRaisesRegex(ValueError, "hashes differ"):
            apply_review(changed_report, review)

    def test_four_provider_pipeline_with_synthetic_data(self):
        # Deliberately invented fixtures: this validates software, not real Harvey coverage.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            buildings = [{"id": f"fixture_{i}", "uid": str(i)} for i in range(76)]
            polygons = [box(-95.4 + i * .0003, 29.75, -95.3999 + i * .0003, 29.7501) for i in range(76)]
            manifest = root / "scene.json"
            manifest.write_text(json.dumps({"scene_id": SCENE_ID, "buildings": buildings}))
            label = root / (SCENE_ID + "_post_disaster.json")
            label.write_text(json.dumps({"metadata": {"capture_date": "2017-09-01T12:00:00Z"}, "features": {"lng_lat": [
                {"properties": {"uid": str(i)}, "wkt": p.wkt} for i, p in enumerate(polygons)]}}))
            initial = manifest.read_bytes()
            hcad = {"type": "FeatureCollection", "features": [{"geometry": mapping(polygons[0]), "properties": {
                "OBJECTID": 1, "PARCEL_ID": "fixture", "Tax_Year": "2017", "LANDUSE_DS": "Residential", "BUILDCOUNT": 1}}]}
            nsi = {"type": "FeatureCollection", "features": [{"geometry": mapping(polygons[1].centroid), "properties": {"fd_id": 1, "occtype": "COM1"}}]}
            def osm(client, bbox, snapshot, historical):
                point = polygons[2].centroid
                payload = {"elements": [{"type": "node", "id": 1, "lon": point.x, "lat": point.y,
                           "tags": {"name": "Fixture School" if historical else "Fixture Hospital", "amenity": "school" if historical else "hospital"}}]}
                return payload, source_info("osm_historical" if historical else "osm_current", snapshot)
            with patch("app.backend.gis_context.audit.fetch_hcad", return_value=(hcad, source_info("hcad", "test"))), \
                 patch("app.backend.gis_context.audit.fetch_nsi", return_value=(nsi, source_info("nsi", "test"))), \
                 patch("app.backend.gis_context.audit.fetch_osm", side_effect=osm):
                report = run_audit(manifest, label, root / "cache", "2026-09-28")
            self.assertEqual(report["status"], "awaiting_manual_qa")
            self.assertEqual(report["metrics"]["combined_displayable_context"]["count"], 3)
            self.assertEqual(report["metrics"]["event_aligned_useful_context"]["count"], 2)
            self.assertEqual(report["metrics"]["no_context"]["count"], 73)
            self.assertEqual(report["metrics"]["historical_current_conflicts"]["count"], 1)
            self.assertIn("2", report["qa"]["selected_uids"])
            self.assertEqual(manifest.read_bytes(), initial)
            write_reports(report, root / "report")
            self.assertEqual(len(json.loads((root / "report" / "audit.json").read_text())["buildings"]), 76)

    def test_missing_input_is_unknown_not_zero_coverage(self):
        manifest = {"buildings": [{"id": str(i), "uid": str(i)} for i in range(76)]}
        report = empty_report(manifest, "missing raw POST labels")
        self.assertEqual(len(report["buildings"]), 76)
        for value in report["metrics"].values():
            self.assertIsNone(value["count"])
            self.assertIsNone(value["percent_of_76"])
            self.assertEqual(value["unknown_buildings"], 76)

    def test_no_context_only_after_complete_evaluation(self):
        statuses = {p: {"status": "complete"} for p in PROVIDERS}
        row = build_row({"id": "a", "uid": "a"}, None, [], [], statuses)
        self.assertTrue(row["flags"]["no_context"])
        statuses["nsi"] = {"status": "unavailable"}
        row = build_row({"id": "a", "uid": "a"}, None, [], [], statuses)
        self.assertIsNone(row["flags"]["no_context"])

    def test_missing_raw_input_never_queries_network(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "scene.json"
            manifest.write_text(json.dumps({"scene_id": SCENE_ID, "buildings": [{"id": str(i), "uid": str(i)} for i in range(76)]}))
            with patch("app.backend.gis_context.cache.urlopen", side_effect=AssertionError("Network must not be used")):
                report = run_audit(manifest, root / (SCENE_ID + "_post_disaster.json"), root / "cache", "test", True)
            self.assertEqual(report["status"], "blocked_missing_raw_input")

    def test_review_artifacts_escape_provider_text(self):
        report = empty_report({"buildings": [{"id": "<script>bad</script>", "uid": "a"}]}, "missing")
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_reports(report, root)
            self.assertEqual(len(list(root.iterdir())), 5)
            html = (root / "review.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>bad</script>", html)
            self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
