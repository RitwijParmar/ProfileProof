from datetime import date

from profileproof.errors import ProviderUnavailable
from profileproof.models import (
    Certification,
    DateRange,
    Education,
    Experience,
    Language,
    ProfileData,
    ProfileImages,
    ProviderName,
)
from profileproof.url_policy import CanonicalProfileUrl

from .base import ProviderContext, ProviderResult


class DemoProvider:
    name = ProviderName.DEMO
    public_identifier = "profileproof-demo"

    async def fetch(
        self, profile_url: CanonicalProfileUrl, context: ProviderContext
    ) -> ProviderResult:
        del context
        if profile_url.public_identifier != self.public_identifier:
            raise ProviderUnavailable(
                "The public deployment does not scrape arbitrary LinkedIn profiles. "
                "Use https://www.linkedin.com/in/profileproof-demo for the synthetic demo, "
                "submit owner-consented data, or configure an approved LinkedIn integration."
            )
        profile = ProfileData(
            name="Aarav Mehta",
            headline="Staff Software Engineer | Distributed Systems & Reliability",
            location="Bengaluru, Karnataka, India",
            about=(
                "Synthetic demonstration profile used to exercise ProfileProof without copying "
                "personal data from LinkedIn. Builds reliable APIs and streaming platforms."
            ),
            experience=[
                Experience(
                    title="Staff Software Engineer",
                    company="Northstar Systems",
                    location="Bengaluru, India",
                    employment_type="Full-time",
                    description="Led a multi-region event platform and its reliability program.",
                    dates=DateRange(start=date(2023, 4, 1), is_current=True),
                ),
                Experience(
                    title="Senior Backend Engineer",
                    company="Atlas Compute",
                    location="Remote",
                    dates=DateRange(start=date(2020, 6, 1), end=date(2023, 3, 1)),
                ),
            ],
            education=[
                Education(
                    school="Indian Institute of Technology",
                    degree="Bachelor of Technology",
                    field_of_study="Computer Science",
                    dates=DateRange(start=date(2016, 7, 1), end=date(2020, 5, 1)),
                )
            ],
            skills=["Distributed Systems", "Python", "C++", "Kubernetes", "Observability"],
            certifications=[
                Certification(
                    name="Professional Cloud Architect",
                    issuer="Google Cloud",
                    issued=date(2024, 2, 1),
                )
            ],
            languages=[
                Language(name="English", proficiency="Professional working proficiency"),
                Language(name="Hindi", proficiency="Native or bilingual proficiency"),
            ],
            images=ProfileImages(),
        )
        return ProviderResult(
            profile=profile,
            mode="synthetic_demo",
            consented=True,
            limitations=[
                "This record is synthetic and is not associated with a real LinkedIn member.",
                "Profile images are intentionally omitted from the fixture.",
            ],
            warnings=["demo_data"],
        )
