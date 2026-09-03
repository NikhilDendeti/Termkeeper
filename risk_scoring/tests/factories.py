import factory
from factory.django import DjangoModelFactory

# Re-exported so `risk_scoring` tests can build a Contract/Clause without
# depending on `contracts.tests` paths directly - `contracts` factories are
# the single source of truth for those models.
from contracts.tests.factories import ClauseFactory, ContractFactory  # noqa: F401
from risk_scoring.models import RiskAssessment, SeverityChoices


class RiskAssessmentFactory(DjangoModelFactory):
    class Meta:
        model = RiskAssessment

    clause = factory.SubFactory(ClauseFactory)
    severity = SeverityChoices.MEDIUM
    asymmetry_score = 0.5
    explanation = "The clause imposes a one-sided notice burden on the vendor."
    suggested_rewrite = None
    linked_mismatch_flag_ids = factory.LazyFunction(list)
