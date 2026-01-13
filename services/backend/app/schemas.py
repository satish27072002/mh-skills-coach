from pydantic import BaseModel


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


class ChatResponse(BaseModel):
    coach_message: str
    exercise: Exercise | None = None
    resources: list[Resource] | None = None
    premium_cta: PremiumCta | None = None


class CheckoutSessionResponse(BaseModel):
    url: str
