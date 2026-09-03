# Re-exported so `reporting` tests can build fixtures without depending on
# other apps' test paths directly - each app's own factories module is the
# single source of truth for its models.
from contracts.tests.factories import ClauseFactory, ContractFactory  # noqa: F401
from pipeline.tests.factories import AuditLogEntryFactory, ExtractedTermFactory  # noqa: F401
from razorpay_integration.tests.factories import (  # noqa: F401
    MismatchFlagFactory,
    PlatformRecordFactory,
)
from risk_scoring.tests.factories import RiskAssessmentFactory  # noqa: F401
