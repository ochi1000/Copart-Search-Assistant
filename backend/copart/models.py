from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.copart.catalog import normalize_featured_item

US_STATE_MAP = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY"
}
US_STATE_CODES = set(US_STATE_MAP.values())
MAX_MODEL_YEAR = date.today().year + 1
GENERIC_VEHICLE_TYPE_TERMS = {"car", "cars", "vehicle", "vehicles"}

class VehicleFilterConstraints(BaseModel):
    """Guardrail schema for searching Copart inventory."""
    query: str = Field(..., description="Vehicle make/model (e.g. 'Toyota Tacoma', 'Honda Civic')")
    title_type: Optional[Literal["Clean Title", "Salvage Title", "Non-Repairable"]] = Field(
        default=None, description="Legal ownership document status"
    )
    run_and_drive: Optional[bool] = Field(
        default=None, description="Only return vehicles verified to start and drive under their own power"
    )
    buy_it_now: Optional[bool] = Field(
        default=None, description="Only return vehicles with an instant purchase price"
    )
    pure_sale: Optional[bool] = Field(
        default=None, description="Only return pure sale lots with no seller reserve price"
    )
    min_year: Optional[int] = Field(default=None, ge=1970, le=MAX_MODEL_YEAR, description="Minimum model year")
    max_year: Optional[int] = Field(default=None, ge=1970, le=MAX_MODEL_YEAR, description="Maximum model year")
    state: Optional[str] = Field(default=None, description="US state code or name (e.g. 'TX' or 'Texas')")
    damage: Optional[str] = Field(default=None, description="Damage type (e.g. 'Front End', 'Hail')")
    min_odometer: Optional[int] = Field(
        default=None,
        ge=0,
        description="Minimum reported odometer reading in miles",
    )
    max_odometer: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum reported odometer reading in miles",
    )
    featured_items: List[str] = Field(
        default_factory=list,
        description="Exact Copart Featured Items labels, such as 'Inspected' or 'Electric Vehicles'",
    )
    title_types: List[str] = Field(default_factory=list, description="Copart vehicle title type values")
    condition_types: List[str] = Field(default_factory=list, description="Copart vehicle condition type values")
    vehicle_types: List[str] = Field(default_factory=list, description="Vehicle type values")
    makes: List[str] = Field(default_factory=list, description="Vehicle makes")
    models: List[str] = Field(default_factory=list, description="Vehicle models")
    engine_types: List[str] = Field(default_factory=list, description="Engine type values")
    transmissions: List[str] = Field(default_factory=list, description="Transmission values")
    fuel_types: List[str] = Field(default_factory=list, description="Fuel type values")
    drive_trains: List[str] = Field(default_factory=list, description="Drive train values")
    cylinders: List[str] = Field(default_factory=list, description="Cylinder-count values")
    auction_names: List[str] = Field(default_factory=list, description="Auction name values")
    locations: List[str] = Field(default_factory=list, description="Copart yard/location values")
    body_styles: List[str] = Field(default_factory=list, description="Body style values")
    sale_lights: List[Literal["Green Light", "Yellow Light", "Red Light"]] = Field(
        default_factory=list,
        description="Sale light values",
    )
    min_autograde: Optional[float] = Field(default=None, ge=0, le=5)
    max_autograde: Optional[float] = Field(default=None, ge=0, le=5)
    zip_code: Optional[str] = Field(default=None, description="US ZIP code for proximity search")
    radius_miles: Optional[int] = Field(default=None, ge=1, le=500)
    sale_date_from: Optional[date] = None
    sale_date_to: Optional[date] = None
    newly_added: Optional[Literal["Last 24 Hours", "Last 7 Days"]] = None
    lots_anyone_can_bid_on: Optional[bool] = None
    wholesale_only: Optional[bool] = None
    exclude_upcoming_auctions: Optional[bool] = None
    exclude_purple_wave: Optional[bool] = None
    additional_facets: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Additional exact Copart facet labels mapped to selected values",
    )
    include_terms: List[str] = Field(
        default_factory=list,
        description=(
            "Optional row-text alternatives. A vehicle may contain any one of these "
            "terms (OR semantics). Prefer normal Copart facets when available."
        ),
    )
    exclude_terms: List[str] = Field(
        default_factory=list,
        description=(
            "Terms that must not appear in a vehicle row, such as 'Flood' or "
            "'Salvage Title'."
        ),
    )
    max_results: int = Field(default=4, ge=1, le=50, description="Number of results to extract")
    offset: int = Field(default=0, ge=0, description="Offset for 'show me more' follow-ups")

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, v):
        if not v or not isinstance(v, str):
            return v
        cleaned = v.strip().lower()
        if cleaned in US_STATE_MAP:
            return US_STATE_MAP[cleaned]
        state_code = cleaned.upper()
        if state_code in US_STATE_CODES:
            return state_code
        raise ValueError(f"Unknown US state: {v}")

    @field_validator("featured_items", mode="before")
    @classmethod
    def normalize_featured_items(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return [normalize_featured_item(item) for item in value]

    @field_validator(
        "title_types",
        "condition_types",
        "vehicle_types",
        "makes",
        "models",
        "engine_types",
        "transmissions",
        "fuel_types",
        "drive_trains",
        "cylinders",
        "auction_names",
        "locations",
        "body_styles",
        "include_terms",
        "exclude_terms",
        mode="before",
    )
    @classmethod
    def coerce_string_lists(cls, value):
        if value is None:
            return []
        values = [value] if isinstance(value, str) else value
        return [item.strip() if isinstance(item, str) else item for item in values]

    @field_validator("vehicle_types")
    @classmethod
    def remove_generic_vehicle_type_terms(cls, values):
        """Generic inventory nouns are not intentional Copart facet choices."""
        return [
            value
            for value in values
            if not (
                isinstance(value, str)
                and value.strip().lower() in GENERIC_VEHICLE_TYPE_TERMS
            )
        ]

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.title_type and self.title_type not in self.title_types:
            self.title_types.append(self.title_type)
        legacy_features = (
            (self.run_and_drive, "Run and Drive"),
            (self.buy_it_now, "Buy It Now"),
            (self.pure_sale, "Pure Sale Items"),
        )
        for enabled, feature in legacy_features:
            if enabled and feature not in self.featured_items:
                self.featured_items.append(feature)

        # Copart exposes these powertrains as Featured Items rather than
        # dependable Fuel type facet values. Tool-calling models commonly put
        # them in fuel_types, so normalize both representations here.
        powertrain_features = {
            "hybrid": "Hybrid",
            "electric": "Electric Vehicles",
            "electric vehicle": "Electric Vehicles",
            "electric vehicles": "Electric Vehicles",
            "ev": "Electric Vehicles",
            "battery electric": "Electric Vehicles",
        }
        remaining_fuel_types = []
        for value in self.fuel_types:
            normalized_value = (
                value.strip().lower() if isinstance(value, str) else ""
            )
            feature = powertrain_features.get(normalized_value)
            if feature:
                if feature not in self.featured_items:
                    self.featured_items.append(feature)
            else:
                remaining_fuel_types.append(value)
        self.fuel_types = remaining_fuel_types

        range_pairs = (
            ("min_year", self.min_year, "max_year", self.max_year),
            ("min_odometer", self.min_odometer, "max_odometer", self.max_odometer),
            ("min_autograde", self.min_autograde, "max_autograde", self.max_autograde),
            ("sale_date_from", self.sale_date_from, "sale_date_to", self.sale_date_to),
        )
        for min_name, minimum, max_name, maximum in range_pairs:
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"{min_name} cannot be greater than {max_name}")
        if self.radius_miles is not None and not self.zip_code:
            raise ValueError("zip_code is required when radius_miles is provided")
        return self

class VehicleDetailRequest(BaseModel):
    """Guardrail schema for inspecting a specific vehicle."""
    lot_id_or_url: str = Field(
        ..., 
        description="The 8-digit Copart Lot Number (e.g. '72087666') or direct Copart lot URL"
    )

class VehicleListing(BaseModel):
    """Structured data extracted for each vehicle lot."""
    title: str
    lot_number: str
    title_status: str
    damage: str
    odometer: str
    odometer_miles: Optional[int] = None
    yard_location: str
    current_bid: Optional[str] = ""
    buy_it_now_price: Optional[str] = ""
    condition: Optional[str] = ""
    link: str
    image_url: str
