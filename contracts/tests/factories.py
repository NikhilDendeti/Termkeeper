import factory
from factory.django import DjangoModelFactory

from contracts.models import Clause, Contract, RazorpayReferenceType


class ContractFactory(DjangoModelFactory):
    class Meta:
        model = Contract

    engagement_id = factory.Sequence(lambda n: f"ENG-{n}")
    raw_text = factory.Faker("paragraph", nb_sentences=10)
    source_filename = "sample_contract.txt"
    razorpay_reference_type = RazorpayReferenceType.PAYOUT
    razorpay_reference_id = factory.Sequence(lambda n: f"pout_{n:06d}")


class ClauseFactory(DjangoModelFactory):
    class Meta:
        model = Clause

    contract = factory.SubFactory(ContractFactory)
    sequence_index = factory.Sequence(lambda n: n)
    clause_text = factory.Faker("paragraph", nb_sentences=3)
