import pytest
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError

from app.billing.schemas.payment import PaymentCreate, PaymentCorrectionCreate, PaymentUpdate


def _create_payload(**kwargs):
    defaults = dict(contract_id=uuid4(), amount=Decimal("15000.00"))
    defaults.update(kwargs)
    return PaymentCreate(**defaults)


def _correction_payload(**kwargs):
    defaults = dict(amount=Decimal("12000.00"))
    defaults.update(kwargs)
    return PaymentCorrectionCreate(**defaults)


# ─── Valid formats per method ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payment_method,reference_number",
    [
        ("check", "123456"),
        ("gcash", "1234567890123"),
        ("bank transfer", "TXN-123456"),
        ("maya", "TXN-123456"),
    ],
)
class TestReferenceNumberValidFormats:
    def test_create_accepts_valid_format(self, payment_method, reference_number):
        payload = _create_payload(payment_method=payment_method, reference_number=reference_number)
        assert payload.reference_number == reference_number

    def test_correction_accepts_valid_format(self, payment_method, reference_number):
        payload = _correction_payload(payment_method=payment_method, reference_number=reference_number)
        assert payload.reference_number == reference_number


# ─── Invalid/missing formats per method ──────────────────────────────────────


@pytest.mark.parametrize(
    "payment_method,reference_number",
    [
        ("check", None),
        ("check", "12"),
        ("check", "12345678901"),
        ("check", "abcd"),
        ("gcash", None),
        ("gcash", "123456789012"),
        ("gcash", "12345678901234"),
        ("gcash", "abcd567890123"),
        ("bank transfer", None),
        ("bank transfer", "abc"),
        ("bank transfer", "a" * 35),
        ("maya", None),
        ("maya", "abc"),
        ("maya", "a" * 35),
    ],
)
class TestReferenceNumberInvalidFormats:
    def test_create_rejects_invalid_format(self, payment_method, reference_number):
        with pytest.raises(ValidationError):
            _create_payload(payment_method=payment_method, reference_number=reference_number)

    def test_correction_rejects_invalid_format(self, payment_method, reference_number):
        with pytest.raises(ValidationError):
            _correction_payload(payment_method=payment_method, reference_number=reference_number)


# ─── Exempt cases ─────────────────────────────────────────────────────────────


class TestReferenceNumberExemptCases:
    def test_cash_with_no_reference_number_passes(self):
        payload = _create_payload(payment_method="cash", reference_number=None)
        assert payload.reference_number is None

    def test_cash_with_arbitrary_reference_number_passes(self):
        payload = _create_payload(payment_method="cash", reference_number="anything-goes")
        assert payload.reference_number == "anything-goes"

    def test_unspecified_payment_method_with_no_reference_number_passes(self):
        payload = _create_payload(payment_method=None, reference_number=None)
        assert payload.reference_number is None

    def test_correction_cash_with_no_reference_number_passes(self):
        payload = _correction_payload(payment_method="cash", reference_number=None)
        assert payload.reference_number is None


# ─── PaymentUpdate partial-update scope decision ─────────────────────────────


class TestPaymentUpdateReferenceNumberFormat:
    def test_amount_only_update_is_unvalidated_regardless_of_format(self):
        """No payment_method in the payload means we can't know the row's
        real method without a DB read, so format-checking is skipped."""
        payload = PaymentUpdate(amount=Decimal("1.00"))
        assert payload.reference_number is None

    def test_reference_number_only_update_is_unvalidated(self):
        """Same reasoning — payment_method absent from the payload."""
        payload = PaymentUpdate(reference_number="not-a-valid-check-number")
        assert payload.reference_number == "not-a-valid-check-number"

    def test_both_fields_together_are_validated(self):
        with pytest.raises(ValidationError):
            PaymentUpdate(payment_method="check", reference_number="not-numeric")

    def test_both_fields_together_valid_format_passes(self):
        payload = PaymentUpdate(payment_method="check", reference_number="123456")
        assert payload.reference_number == "123456"
