from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class ProviderName(StrEnum):
    DEMO = "demo"
    LINKEDIN_SESSION = "linkedin_session"


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date | None = None
    end: date | None = None
    is_current: bool = False

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "DateRange":
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must not be after end")
        if self.is_current and self.end:
            raise ValueError("a current range cannot have an end date")
        return self


class Experience(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    employment_type: str | None = Field(default=None, max_length=100)
    dates: DateRange = Field(default_factory=DateRange)


class Education(BaseModel):
    model_config = ConfigDict(extra="forbid")
    school: str = Field(min_length=1, max_length=300)
    degree: str | None = Field(default=None, max_length=300)
    field_of_study: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    dates: DateRange = Field(default_factory=DateRange)


class Certification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=300)
    issuer: str | None = Field(default=None, max_length=300)
    issued: date | None = None
    expires: date | None = None
    credential_id: str | None = Field(default=None, max_length=300)
    credential_url: HttpUrl | None = None


class Language(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    proficiency: str | None = Field(default=None, max_length=100)


class ProfileImages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: HttpUrl | None = None
    background: HttpUrl | None = None


class ProfileData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=300)
    headline: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=300)
    about: str | None = Field(default=None, max_length=20_000)
    experience: list[Experience] = Field(default_factory=list, max_length=100)
    education: list[Education] = Field(default_factory=list, max_length=100)
    skills: list[str] = Field(default_factory=list, max_length=500)
    certifications: list[Certification] = Field(default_factory=list, max_length=100)
    languages: list[Language] = Field(default_factory=list, max_length=100)
    images: ProfileImages = Field(default_factory=ProfileImages)

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: list[str]) -> list[str]:
        clean = [skill.strip() for skill in value if skill.strip()]
        return list(dict.fromkeys(clean))


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_url: str = Field(min_length=1, max_length=500)
    provider: ProviderName = ProviderName.LINKEDIN_SESSION


class SourceInfo(BaseModel):
    provider: ProviderName
    mode: str
    consented: bool
    licensed: bool = False
    match_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    dataset_version: str | None = None
    limitations: list[str] = Field(default_factory=list)


class ResolveMeta(BaseModel):
    request_id: str
    fetched_at: datetime
    cached: bool
    completeness: float = Field(ge=0.0, le=1.0)
    fields_present: list[str]
    warnings: list[str] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    schema_version: str = "1.1"
    canonical_url: HttpUrl
    public_identifier: str
    profile: ProfileData
    source: SourceInfo
    meta: ResolveMeta


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class ProviderCapability(BaseModel):
    name: ProviderName
    configured: bool
    real_data: bool
    description: str


class CapabilitiesResponse(BaseModel):
    providers: list[ProviderCapability]


class Problem(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    request_id: str
