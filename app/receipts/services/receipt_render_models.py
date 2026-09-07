from dataclasses import dataclass
from decimal import Decimal

_PLACEHOLDER = "-"

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")
_SCALES = ((1_000_000_000, "Billion"), (1_000_000, "Million"), (1_000, "Thousand"))


def _three_digit_words(n: int) -> str:
    parts = []
    hundreds, remainder = divmod(n, 100)
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if remainder:
        if remainder < 20:
            parts.append(_ONES[remainder])
        else:
            tens, ones = divmod(remainder, 10)
            word = _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
            parts.append(word)
    return " ".join(parts)


def _integer_to_words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    remaining = n
    for value, name in _SCALES:
        if remaining >= value:
            count, remaining = divmod(remaining, value)
            parts.append(f"{_three_digit_words(count)} {name}")
    if remaining:
        parts.append(_three_digit_words(remaining))
    return " ".join(parts)


def amount_to_words(amount: Decimal) -> str:
    """Render a currency amount as English words, e.g. Decimal("1250.00")
    -> "One Thousand Two Hundred Fifty Pesos and 00/100". Self-contained
    rather than a num2words-style dependency — the format needed is
    narrow (currency amounts only), which doesn't justify a new package.
    Coerces via `str()` first so a plain `int`/`float` amount (as several
    existing test doubles use) works the same as a real `Decimal` column
    value - consistent with this module's existing duck-typed inputs.
    """
    quantized = Decimal(str(amount)).quantize(Decimal("0.01"))
    pesos, cents = divmod(int(quantized * 100), 100)
    return f"{_integer_to_words(pesos)} Pesos and {cents:02d}/100"


def _attr_or_default(obj, name: str, default: str = _PLACEHOLDER) -> str:
    """`getattr(obj, name)`, falling back to `default` when the attribute
    is missing, None, or empty — the "-" placeholder convention used
    throughout a receipt's render context for absent data."""
    return getattr(obj, name, default) or default


@dataclass(frozen=True)
class ChargeLine:
    """One row of the "other charges" breakdown on a receipt (e.g. a late
    fee). Additional charge types (maintenance fees, adjustments, etc.) can
    be appended the same way once those concepts exist elsewhere in the
    codebase — none do yet."""

    label: str
    amount: Decimal


@dataclass(frozen=True)
class PropertyInfo:
    name: str
    address: str

    @classmethod
    def from_property(cls, property_) -> "PropertyInfo":
        return cls(name=_attr_or_default(property_, "name"), address=_attr_or_default(property_, "address"))


@dataclass(frozen=True)
class TenantInfo:
    name: str

    @classmethod
    def from_tenant(cls, tenant) -> "TenantInfo":
        return cls(name=_attr_or_default(tenant, "full_name"))


@dataclass(frozen=True)
class PaymentInfo:
    """A payment's financial breakdown for this receipt: the base amount
    paid, any other charges billed alongside it (e.g. a late fee), and the
    resulting total — grouped together since they're all part of the same
    payment's story, not independent receipt-level facts."""

    amount: Decimal
    other_charges: list[ChargeLine]
    total_amount: Decimal
    amount_in_words: str
    rental_period: str
    paid_at: str
    method: str
    reference_number: str

    @classmethod
    def from_payment(cls, payment, billing_record=None) -> "PaymentInfo":
        other_charges = []
        if billing_record is not None and billing_record.late_fee_applied:
            other_charges.append(ChargeLine(label="Late Fee", amount=billing_record.late_fee_amount_charged))

        total_amount = payment.amount + sum((charge.amount for charge in other_charges), start=Decimal("0"))

        if billing_record is not None:
            rental_period = f"{billing_record.period_start} – {billing_record.period_end}"
        else:
            rental_period = _PLACEHOLDER

        return cls(
            amount=payment.amount,
            other_charges=other_charges,
            total_amount=total_amount,
            amount_in_words=amount_to_words(total_amount),
            rental_period=rental_period,
            paid_at=payment.paid_at.isoformat(),
            method=_attr_or_default(payment, "payment_method"),
            reference_number=_attr_or_default(payment, "reference_number"),
        )


@dataclass(frozen=True)
class ReceiptRenderContext:
    """The full set of values a receipt template is rendered with. A
    dataclass rather than a bare dict so the fields a template may
    reference are declared once, in one place, instead of being implicit
    in whatever `_build_render_context` happens to return. Grouped into
    per-entity sub-dataclasses (property/tenant/payment) rather than one
    flat list of fields, mirroring the domain objects each group is
    sourced from."""

    receipt_number: int
    property: PropertyInfo
    tenant: TenantInfo
    payment: PaymentInfo
    contact_email: str
    notes: str
    contact_number: str

    @classmethod
    def build(
        cls,
        *,
        receipt_number: int,
        payment,
        property_,
        tenant,
        billing_record=None,
        manager_email: str | None = None,
    ) -> "ReceiptRenderContext":
        return cls(
            receipt_number=receipt_number,
            property=PropertyInfo.from_property(property_),
            tenant=TenantInfo.from_tenant(tenant),
            payment=PaymentInfo.from_payment(payment, billing_record),
            contact_email=manager_email or _PLACEHOLDER,
            notes=_PLACEHOLDER,
            contact_number=_PLACEHOLDER,
        )
