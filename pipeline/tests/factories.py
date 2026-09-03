import factory
from factory.django import DjangoModelFactory

# Re-exported so `pipeline` tests can build a Contract/Clause without
# depending on `contracts.tests` paths directly - `contracts` factories are
# the single source of truth for those models.
from contracts.tests.factories import ClauseFactory, ContractFactory  # noqa: F401
from pipeline.models import AuditLogEntry, ExtractedTerm, PipelineStage, TermType


class ExtractedTermFactory(DjangoModelFactory):
    class Meta:
        model = ExtractedTerm

    clause = factory.SubFactory(ClauseFactory)
    term_type = TermType.PAYOUT_FREQUENCY
    value_raw = "net 30 days from the invoice date"
    value_structured = factory.LazyFunction(lambda: {"numeric_value": 30, "unit": "days"})
    extraction_confidence = 0.9
    needs_human_review = False


class AuditLogEntryFactory(DjangoModelFactory):
    class Meta:
        model = AuditLogEntry

    contract = factory.SubFactory(ContractFactory)
    clause = None
    stage = PipelineStage.SEGMENTATION
    prompt_version = "clause-segmentation-v1"
    llm_response_raw = factory.LazyFunction(lambda: {"clauses": []})
    model_name = "claude-sonnet-5"
    latency_ms = 100
