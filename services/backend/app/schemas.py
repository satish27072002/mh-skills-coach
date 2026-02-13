from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str


class Exercise(BaseModel):
    type: str
    steps: list[str]
    duration_seconds: int


class Resource(BaseModel):
    title: str
    url: str
    description: str | None = None


class PremiumCta(BaseModel):
    enabled: bool
    message: str


class TherapistResult(BaseModel):
    name: str
    address: str
    url: str
    phone: str
    distance_km: float
    email: str | None = None
    source_url: str | None = None


class TherapistSearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    location_text: str = Field(validation_alias=AliasChoices("location_text", "location"))
    radius_km: int | None = None
    limit: int | None = None


class TherapistSearchResponse(BaseModel):
    results: list[TherapistResult]


class BookingProposal(BaseModel):
    therapist_email: str
    requested_time: str
    subject: str
    body: str
    expires_at: str


class ChatResponse(BaseModel):
    coach_message: str
    exercise: Exercise | None = None
    resources: list[Resource] | None = None
    premium_cta: PremiumCta | None = None
    therapists: list[TherapistResult] | None = None
    booking_proposal: BookingProposal | None = None
    requires_confirmation: bool | None = None
    risk_level: str | None = None


class CheckoutSessionResponse(BaseModel):
    url: str
