"""Deterministic presentation of reviewed evidence; never changes GIS matches.

Claims remain individually inspectable. Contexts normalize claims within a scope
and time; statements arrange those contexts for the UI without promoting their
scope or hiding mixed classifications. No model, provider or network calls.
"""

from collections import OrderedDict
import re


CATEGORIES = {
    "residential": "Residential", "education": "Education", "medical": "Medical / Healthcare",
    "commercial": "Commercial", "professional_services": "Professional Services",
    "industrial": "Industrial", "warehouse": "Warehouse", "government": "Government / Civic",
    "emergency_services": "Emergency Services", "religious": "Religious", "lodging": "Lodging",
    "recreation": "Recreation / Community", "transportation": "Transportation",
    "agricultural": "Agricultural", "mixed_use": "Mixed Use", "unknown": "Unknown",
}
CATEGORY_ALIASES = {
    "commercial_retail": "commercial", "office_professional": "professional_services",
    "multifamily": "residential", "mixed": "mixed_use", "recreation_community": "recreation",
    "government_civic": "government", "agriculture": "agricultural",
}
SCOPE_LABELS = {
    "place": "Mapped place", "building": "Building use", "modeled_building": "Modeled use",
    "property": "Property use", "site": "Site", "area": "Area",
}
SCOPE_ORDER = {scope: index for index, scope in enumerate(SCOPE_LABELS)}
TEMPORAL_LABELS = {
    "event_year": "2017 event-year", "pre_event_historical": "2017 pre-event",
    "current_only": "Current", "event_snapshot": "Mapped near disaster date",
    "current_modeled_not_event_aligned": "Current modeled context",
    "pre_event_reference_vintage_unverified": "2017 advertised · vintage unverified",
}


def key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


# Exact vocabulary aliases, not fuzzy matching or keyword guesses. Names never
# pass through this table. Unknown values retain their audited broad category.
VOCABULARY = {}


def vocabulary(category, subtype, label, *aliases):
    for alias in (label, *aliases):
        VOCABULARY[key(alias)] = {"category": category, "subtype": subtype, "label": label}


vocabulary("residential", "single_family", "Single-family residential", "SINGLE FAMILY", "Residential 1 Family",
           "Residential Single Family", "SINGLE FAMILY DWELLING", "house", "RURAL RES/SINGLE RES")
vocabulary("residential", "multifamily", "Multifamily residential")
vocabulary("residential", "multifamily_up_to_10", "Multifamily · Up to 10 units", "MULTI-FAMILY 10 LESS")
vocabulary("residential", "manufactured_housing", "Manufactured housing", "MOBILE HOME")
vocabulary("residential", "accessory_dwelling", "Single-family with accessory dwelling", "RURAL RES SFD W/GRANNY UNIT")
vocabulary("residential", "residential", "Residential", "residential area")
vocabulary("education", "school", "School", "PAROCHIAL SCHOOL")
vocabulary("education", "educational_institution", "Educational institution", "educational_institution")
vocabulary("medical", "dentist", "Dentist")
vocabulary("medical", "medical_office", "Medical office")
vocabulary("commercial", "retail", "Retail", "STORES, 1 STORY", "retail area")
vocabulary("commercial", "shopping_center", "Shopping center", "Strip Shopping Center", "Neighborhood Shopping Ctr")
vocabulary("commercial", "wholesale", "Wholesale")
vocabulary("commercial", "personal_repair", "Personal and repair services", "Personal/repair services")
vocabulary("commercial", "repair", "Repair services", "REPAIR SERVICE")
vocabulary("commercial", "vehicle_sales_repair", "Vehicle sales and repair", "VEH SALE/REPAIR")
vocabulary("commercial", "auto_service", "Auto service", "Auto Service Garage")
vocabulary("commercial", "convenience_store", "Convenience store", "convenience")
vocabulary("commercial", "tobacco_shop", "Tobacco shop", "tobacco")
vocabulary("professional_services", "office", "Office", "Office Building")
vocabulary("professional_services", "low_rise_office", "Low-rise office", "Office Bldgs. Low-Rise (1 to 4 Stories)")
vocabulary("professional_services", "professional_services", "Professional services")
vocabulary("professional_services", "bank", "Bank")
vocabulary("professional_services", "insurance", "Insurance services", "insurance")
vocabulary("professional_services", "association", "Association")
vocabulary("warehouse", "warehouse", "Warehouse / storage", "WAREHOUSE-STORAGE", "Warehouse - Metallic", "warehouse")
vocabulary("government", "government_services", "Government services")
vocabulary("recreation", "recreation", "Recreation", "Entertainment/recreation")
vocabulary("recreation", "park", "Park")
vocabulary("mixed_use", "retail_office_residential", "Retail, office and residential", "STORE/OFFICE/RESID")


def normalize_classification(value: str, category_hint: str = "unknown") -> list[dict]:
    """Preserve compounds as concepts instead of arbitrarily selecting a use."""
    # The audit's compound garage/warehouse description has two literal uses.
    pieces = value.split(";") if ";" in value else [value]
    if key(value) == key("Auto Service Garage,Warehouse - Metallic"):
        pieces = ["Auto Service Garage", "Warehouse - Metallic"]
    result = []
    for piece in pieces:
        concept = VOCABULARY.get(key(piece))
        if concept is None:
            category = CATEGORY_ALIASES.get(category_hint, category_hint)
            if category not in CATEGORIES:
                category = "unknown"
            concept = {"category": category, "subtype": None, "label": CATEGORIES[category]}
        if concept not in result:
            result.append(dict(concept))
    return result


def scope_for(claim: dict) -> str:
    if claim["kind"] == "modeled_occupancy":
        return "modeled_building"
    if claim["kind"] == "area_use":
        return "area"
    return {"parcel": "property", "place": "place", "building": "building", "site": "site"}[claim["scope"]]


def classification_for(claim: dict) -> str:
    if claim["kind"] == "mapped_name":
        return ""  # A name is not evidence of use.
    if claim["kind"] == "school_site":
        return "School"
    if claim["kind"] in {"site_use", "area_use"}:
        values = claim["original_values"]
        return next((str(values[k]) for k in ("amenity", "landuse", "leisure") if values.get(k)), "")
    value = claim["original_value"]
    if claim["name"]:
        value = value.removesuffix(" (" + claim["name"] + ")")
    return value


def compact_concepts(concepts: list[dict]) -> list[dict]:
    """Deduplicate aliases and absorb broad office/residential wording only when
    a compatible, more specific classification is present in the same context.
    Every original claim reference survives.
    """
    groups = OrderedDict()
    for concept in concepts:
        identity = (concept["category"], concept["subtype"])
        if identity not in groups:
            groups[identity] = {**concept, "supporting_claims": []}
        groups[identity]["supporting_claims"] = sorted(set(groups[identity]["supporting_claims"] + concept["supporting_claims"]))
    for category, broad, specific in (("professional_services", "office", "low_rise_office"),
                                     ("residential", "multifamily", "multifamily_up_to_10")):
        if (category, broad) in groups and (category, specific) in groups:
            broad_concept = groups.pop((category, broad))
            target = groups[(category, specific)]
            target["supporting_claims"] = sorted(set(target["supporting_claims"] + broad_concept["supporting_claims"]))
    return list(groups.values())


def category_for(concepts: list[dict]) -> str:
    categories = {c["category"] for c in concepts}
    return next(iter(categories)) if len(categories) == 1 else "mixed_use"


def label_for(concepts: list[dict]) -> str:
    if len(concepts) == 1:
        return concepts[0]["label"]
    words = {"medical": "healthcare", "professional_services": "professional", "commercial": "commercial",
             "education": "education", "residential": "residential", "warehouse": "warehouse"}
    categories = sorted({c["category"] for c in concepts})
    labels = [words.get(c, CATEGORIES[c].lower()) for c in categories]
    joined = " and ".join(labels) if len(labels) <= 2 else ", ".join(labels[:-1]) + " and " + labels[-1]
    return "Mixed " + joined + " uses"


def build_contexts(claims: list[dict]) -> list[dict]:
    groups = OrderedDict()
    for claim in claims:
        scope = scope_for(claim)
        identity = (scope, claim["kind"], claim["name"], claim["temporal_relation"], claim["modeled"], claim["multi_structure"])
        if identity not in groups:
            groups[identity] = {"scope": scope, "kind": claim["kind"], "name": claim["name"],
                                "temporal_relation": claim["temporal_relation"], "modeled": claim["modeled"],
                                "multi_structure": claim["multi_structure"], "supporting_claims": [],
                                "qualifications": [], "concepts": []}
        context = groups[identity]
        concepts = normalize_classification(classification_for(claim), claim["category_hint"])
        context["concepts"].extend({**c, "supporting_claims": [claim["id"]]} for c in concepts)
        context["supporting_claims"].append(claim["id"])
        context["qualifications"] = sorted(set(context["qualifications"] + claim["qualifications"]))
    contexts = []
    for context in groups.values():
        context["concepts"] = compact_concepts(context["concepts"])
        context.update(id=f"context-{len(contexts)}", category=category_for(context["concepts"]),
                       label=label_for(context["concepts"]), temporal_label=TEMPORAL_LABELS[context["temporal_relation"]])
        contexts.append(context)
    return contexts


def statement_text(context: dict) -> str:
    name, scope, category = context["name"], context["scope"], context["category"]
    if name and scope == "site":
        return "Within " + name + (" campus" if category == "education" else "")
    if name:
        return name + (" · " + context["label"] if category != "unknown" and scope == "place" else "")
    if scope == "site":
        return "Within a school site" if category == "education" else "Within a mapped " + context["label"].lower() + " site"
    if scope == "area":
        return context["label"] + " area"
    return context["label"]


def temporal_summary(contexts: list[dict]) -> str:
    relations = list(dict.fromkeys(c["temporal_relation"] for c in contexts))
    if len(relations) == 1:
        return TEMPORAL_LABELS[relations[0]]
    labels = []
    if "event_snapshot" in relations:
        labels.append("Historical mapping")
    if "current_only" in relations:
        labels.append("current mapping")
    if "pre_event_reference_vintage_unverified" in relations:
        labels.append("county vintage unverified")
    return " · ".join(labels)  # Cross-date consolidation is limited to named sites.


def build_statements(contexts: list[dict], claims: list[dict]) -> list[dict]:
    statements = []
    claim_by_id = {c["id"]: c for c in claims}
    for context in contexts:
        # Only the same named site/category can share a cross-date statement.
        # Different names and all other historical/current contexts stay separate.
        existing = next((s for s in statements if context["scope"] == "site" and context["name"]
                         and s["scope"] == "site" and s["name"] == context["name"]
                         and s["category"] == context["category"]), None)
        if existing:
            existing["context_ids"].append(context["id"])
            existing["supporting_claims"].extend(context["supporting_claims"])
            continue
        label = SCOPE_LABELS[context["scope"]]
        if context["kind"] == "mapped_name" and context["scope"] == "building":
            label = "Mapped building"
        elif context["kind"] == "structure_use":
            label = "Parcel-linked structure"
        statements.append({"id": f"statement-{len(statements)}", "scope": context["scope"], "name": context["name"],
                           "category": context["category"], "label": label, "text": statement_text(context),
                           "context_ids": [context["id"]], "supporting_claims": list(context["supporting_claims"]),
                           "corroborating_claims": [], "modeled": context["modeled"],
                           "corroboration_basis": "same_scoped_context"})
    context_by_id = {c["id"]: c for c in contexts}
    consumed = set()
    # School/site evidence can corroborate Education as a category across scopes.
    # It does NOT establish the identity/use of an individual roof. Name-only
    # records and mixed modeled contexts always retain their own statement.
    school_sites = [s for s in statements if s["scope"] == "site" and s["category"] == "education"]
    if school_sites:
        anchor = next((s for s in school_sites if s["name"]), school_sites[0])
        for statement in statements:
            if statement is anchor or statement["scope"] == "area":
                continue
            source_contexts = [context_by_id[c] for c in statement["context_ids"]]
            matching = [reference for c in source_contexts for concept in c["concepts"]
                        if concept["category"] == "education" and concept["subtype"] == "school"
                        for reference in concept["supporting_claims"]]
            if matching and not statement["name"]:
                anchor["corroborating_claims"].extend(matching)
                anchor["corroboration_basis"] = "education_category_only"
                if statement["category"] == "education":
                    consumed.add(statement["id"])
        # Generic school corroboration is category-only, even when it accompanies
        # the named site's presentation. Conflicting named sites remain separate.
    for statement in statements:
        if statement["id"] in consumed:
            continue
        target = context_by_id[statement["context_ids"][0]]
        if target["kind"] != "structure_use":
            continue
        for other in statements:
            candidate = context_by_id[other["context_ids"][0]]
            if (other["id"] in consumed or candidate["scope"] != "property" or candidate["multi_structure"]
                    or candidate["temporal_relation"] != target["temporal_relation"]
                    or [(c["category"], c["subtype"]) for c in candidate["concepts"]]
                    != [(c["category"], c["subtype"]) for c in target["concepts"]]):
                continue
            if ({claim_by_id[c]["source_key"] for c in candidate["supporting_claims"]}
                    == {claim_by_id[c]["source_key"] for c in target["supporting_claims"]}):
                statement["corroborating_claims"].extend(candidate["supporting_claims"])
                statement["corroboration_basis"] = "single_structure_parcel_support"
                consumed.add(other["id"])
    result = []
    for statement in statements:
        if statement["id"] in consumed:
            continue
        statement_contexts = [context_by_id[c] for c in statement["context_ids"]]
        statement["temporal_label"] = temporal_summary(statement_contexts)
        statement["corroborating_claims"] = sorted(set(statement["corroborating_claims"]))
        references = statement["supporting_claims"] + statement["corroborating_claims"]
        statement["supporting_sources"] = sorted({claim_by_id[c]["source_family"] for c in references})
        statement["has_multiple_sources"] = len(statement["supporting_sources"]) > 1
        result.append(statement)

    def rank(statement):
        priority = SCOPE_ORDER[statement["scope"]]
        if statement["scope"] == "building" and statement["name"]:
            priority = 0
        if statement["corroborating_claims"]:
            priority = min(priority, *(SCOPE_ORDER[scope_for(claim_by_id[c])] for c in statement["corroborating_claims"]))
        return priority, statement["category"] == "mixed_use"

    return sorted(result, key=rank)


def normalize_context(claims: list[dict], conflicts: list[dict] = ()) -> dict:
    contexts = build_contexts(claims)
    statements = build_statements(contexts, claims)
    area_only = bool(statements) and all(s["scope"] == "area" for s in statements)
    candidates = statements if area_only else [s for s in statements if s["scope"] != "area"]
    primary = candidates[:3]
    category = primary[0]["category"] if primary else "unknown"
    notes = []
    if conflicts:
        reasons = {c["reason"] for c in conflicts}
        if "modeled_vs_mapped_difference" in reasons:
            notes.append("Modeled and mapped uses differ; see source details.")
        if "historical_current_difference" in reasons:
            notes.append("Historical and current records differ; both are retained.")
    school_names = {s["name"] for s in statements if s["scope"] == "site" and s["category"] == "education" and s["name"]}
    if len(school_names) > 1:
        notes.append("School-site names differ by source.")
    primary_label = "Area context" if area_only else "Mapped context" if category == "unknown" else CATEGORIES[category]
    return {"version": 2, "primary_category": category, "primary_label": primary_label,
            "primary_statement_ids": [s["id"] for s in primary], "area_only": area_only,
            "has_multiple_supporting_sources": any(s["has_multiple_sources"] for s in primary),
            "contexts": contexts, "statements": statements, "claims": claims, "conflicts": list(conflicts), "notes": notes}
