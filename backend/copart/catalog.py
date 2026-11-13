"""Canonical Copart inventory filter names used by the LLM and browser adapter."""

FEATURED_ITEMS = (
    "Used Vehicles",
    "Buy It Now",
    "Run and Drive",
    "No License Required",
    "Pure Sale Items",
    "Inspected",
    "Electric Vehicles",
    "NPA Vehicles Only",
    "Rentals",
    "Public and General Business",
    "Hot Items",
    "Engine Start Program",
    "Enhanced Vehicles",
    "Hybrid",
    "Classics",
    "Exotics",
    "New Items",
    "Featured Vehicles",
    "Seller Certified",
    "Offsite Sales",
    "Recovered Thefts",
    "Fleet / Lease",
    "Bank / Repossessed",
    "Specialty Vehicles",
)

FEATURED_ITEM_ALIASES = {
    "used": "Used Vehicles",
    "used vehicle": "Used Vehicles",
    "buy now": "Buy It Now",
    "buy it now": "Buy It Now",
    "run & drive": "Run and Drive",
    "run and drive": "Run and Drive",
    "no license": "No License Required",
    "no license required": "No License Required",
    "pure sale": "Pure Sale Items",
    "pure sale items": "Pure Sale Items",
    "inspection": "Inspected",
    "inspected": "Inspected",
    "ev": "Electric Vehicles",
    "electric": "Electric Vehicles",
    "electric vehicle": "Electric Vehicles",
    "npa": "NPA Vehicles Only",
    "rental": "Rentals",
    "public": "Public and General Business",
    "engine start": "Engine Start Program",
    "enhanced": "Enhanced Vehicles",
    "new": "New Items",
    "featured": "Featured Vehicles",
    "offsite": "Offsite Sales",
    "recovered theft": "Recovered Thefts",
    "fleet": "Fleet / Lease",
    "lease": "Fleet / Lease",
    "bank repossessed": "Bank / Repossessed",
    "repossessed": "Bank / Repossessed",
    "repo": "Bank / Repossessed",
    "specialty": "Specialty Vehicles",
}

FACET_FIELDS = {
    "title_types": "Vehicle title type",
    "condition_types": "Vehicle condition type",
    "vehicle_types": "Vehicle type",
    "makes": "Make",
    "models": "Model",
    "engine_types": "Engine type",
    "transmissions": "Transmission",
    "fuel_types": "Fuel type",
    "drive_trains": "Drive train",
    "cylinders": "Cylinder",
    "auction_names": "Auction name",
    "locations": "Location",
    "body_styles": "Body style",
}

RANGE_FIELDS = {
    "odometer": "Odometer",
    "year": "Year",
    "autograde": "AutoGrade",
    "sale_date": "Sale date",
}

SUPPORTED_ADDITIONAL_FACETS = tuple(FACET_FIELDS.values())


def normalize_featured_item(value: str) -> str:
    cleaned = " ".join(value.strip().lower().split())
    if cleaned in FEATURED_ITEM_ALIASES:
        return FEATURED_ITEM_ALIASES[cleaned]
    for canonical in FEATURED_ITEMS:
        if cleaned == canonical.lower():
            return canonical
    raise ValueError(f"Unknown Copart featured item: {value}")
