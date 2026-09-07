import pytest

from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.receipts.services.receipt_pdf import (
    _blocked_url_fetcher,
    load_default_template,
    render_receipt_pdf,
)
from app.receipts.services.receipt_render_models import ChargeLine, ReceiptRenderContext, amount_to_words


def _payment(**kwargs):
    defaults = dict(
        amount=Decimal("15000.00"),
        paid_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        payment_method="cash",
        reference_number="REF-1",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _billing_record(**kwargs):
    defaults = dict(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        late_fee_applied=False,
        late_fee_amount_charged=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _receipt_kwargs(**overrides):
    defaults = dict(
        receipt_number=1,
        payment=_payment(),
        property_=SimpleNamespace(name="Sunset Villa", address="123 Sunset Ave"),
        tenant=SimpleNamespace(full_name="Jane Doe"),
        billing_record=None,
        manager_email=None,
    )
    defaults.update(overrides)
    return defaults


def _render(template_html=None, **kwargs):
    return render_receipt_pdf(
        template_html=template_html or load_default_template(),
        **_receipt_kwargs(**kwargs),
    )


class TestLoadDefaultTemplate:
    def test_loads_html_containing_jinja_placeholders(self):
        html = load_default_template()
        assert "{{ receipt_number }}" in html
        assert "<html" in html


class TestRenderReceiptPdf:
    def test_output_starts_with_pdf_magic_bytes(self):
        assert _render().read(5) == b"%PDF-"

    def test_output_is_non_trivial_size(self):
        assert len(_render().read()) > 500

    def test_no_exception_with_optional_fields_unset(self):
        buf = _render(payment=_payment(payment_method=None, reference_number=None))
        assert buf.read(5) == b"%PDF-"

    def test_buffer_is_seeked_to_start(self):
        assert _render().tell() == 0

    def test_renders_a_custom_template_with_matching_placeholders(self):
        custom = "<html><body><p>Custom receipt {{ receipt_number }} for {{ tenant_name }}</p></body></html>"
        buf = _render(template_html=custom, receipt_number=42, tenant=SimpleNamespace(full_name="Custom Tenant"))
        assert buf.read(5) == b"%PDF-"

    def test_renders_without_crashing_when_template_references_an_external_image(self):
        """WeasyPrint treats a failed image fetch as non-fatal (like a
        browser) — the PDF still renders, just without that image. The
        actual SSRF guard is `_blocked_url_fetcher` itself, asserted below."""
        malicious = '<html><body><img src="http://169.254.169.254/latest/meta-data/"></body></html>'
        assert _render(template_html=malicious).read(5) == b"%PDF-"


class TestBlockedUrlFetcher:
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://example.com/logo.png",
            "file:///etc/passwd",
            "ftp://example.com/file",
        ],
    )
    def test_raises_for_any_network_or_local_scheme(self, url):
        with pytest.raises(ValueError):
            _blocked_url_fetcher(url)


class TestBuildRenderContext:
    def _context(self, **kwargs):
        return ReceiptRenderContext.build(**_receipt_kwargs(**kwargs))

    def _assert_no_field_is_blank(self, obj, path=""):
        for field in fields(obj):
            name = f"{path}.{field.name}" if path else field.name
            value = getattr(obj, field.name)
            if is_dataclass(value):
                self._assert_no_field_is_blank(value, name)
            elif isinstance(value, list):
                assert value or field.name == "other_charges", f"{name} is unexpectedly empty"
            else:
                assert value not in (None, ""), f"{name} rendered blank"

    def test_no_variable_is_ever_blank(self):
        ctx = self._context(billing_record=_billing_record(), manager_email="owner@example.com")
        self._assert_no_field_is_blank(ctx)

    def test_other_charges_is_empty_list_without_billing_record(self):
        ctx = self._context(billing_record=None)
        assert ctx.payment.other_charges == []

    def test_other_charges_is_empty_list_when_late_fee_not_applied(self):
        record = _billing_record(late_fee_applied=False, late_fee_amount_charged=None)
        ctx = self._context(billing_record=record)
        assert ctx.payment.other_charges == []

    def test_other_charges_contains_late_fee_line_when_applied(self):
        record = _billing_record(late_fee_applied=True, late_fee_amount_charged=Decimal("500.00"))
        ctx = self._context(billing_record=record)
        assert ctx.payment.other_charges == [ChargeLine(label="Late Fee", amount=Decimal("500.00"))]

    def test_notes_defaults_to_placeholder(self):
        ctx = self._context()
        assert ctx.notes == "-"

    def test_contact_number_defaults_to_placeholder(self):
        ctx = self._context()
        assert ctx.contact_number == "-"

    def test_property_address_reflects_property(self):
        ctx = self._context(property_=SimpleNamespace(name="Villa", address="456 Rizal St"))
        assert ctx.property.address == "456 Rizal St"

    def test_rental_period_placeholder_when_no_billing_record(self):
        ctx = self._context(billing_record=None)
        assert ctx.payment.rental_period == "-"

    def test_rental_period_reflects_billing_record_when_linked(self):
        record = _billing_record(period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))
        ctx = self._context(billing_record=record)
        assert ctx.payment.rental_period == "2026-03-01 – 2026-03-31"

    def test_total_amount_equals_payment_amount_without_billing_record(self):
        ctx = self._context(payment=_payment(amount=Decimal("15000.00")), billing_record=None)
        assert ctx.payment.total_amount == Decimal("15000.00")

    def test_total_amount_includes_late_fee_when_applied(self):
        record = _billing_record(late_fee_applied=True, late_fee_amount_charged=Decimal("500.00"))
        ctx = self._context(payment=_payment(amount=Decimal("15000.00")), billing_record=record)
        assert ctx.payment.total_amount == Decimal("15500.00")

    def test_total_amount_ignores_late_fee_when_not_applied(self):
        record = _billing_record(late_fee_applied=False, late_fee_amount_charged=None)
        ctx = self._context(payment=_payment(amount=Decimal("15000.00")), billing_record=record)
        assert ctx.payment.total_amount == Decimal("15000.00")

    def test_amount_in_words_reflects_total_amount(self):
        record = _billing_record(late_fee_applied=True, late_fee_amount_charged=Decimal("500.00"))
        ctx = self._context(payment=_payment(amount=Decimal("15000.00")), billing_record=record)
        assert ctx.payment.amount_in_words == amount_to_words(Decimal("15500.00"))

    def test_contact_email_reflects_manager_email_when_provided(self):
        ctx = self._context(manager_email="owner@example.com")
        assert ctx.contact_email == "owner@example.com"

    def test_contact_email_placeholder_when_no_manager(self):
        ctx = self._context(manager_email=None)
        assert ctx.contact_email == "-"


class TestAmountToWords:
    def test_whole_number_amount(self):
        assert amount_to_words(Decimal("1250.00")) == "One Thousand Two Hundred Fifty Pesos and 00/100"

    def test_amount_with_cents(self):
        assert amount_to_words(Decimal("1500.75")) == "One Thousand Five Hundred Pesos and 75/100"

    def test_magnitude_boundary_exactly_one_thousand(self):
        assert amount_to_words(Decimal("1000.00")) == "One Thousand Pesos and 00/100"
