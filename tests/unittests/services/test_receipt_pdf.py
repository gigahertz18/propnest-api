import pytest

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.receipt_pdf import _blocked_url_fetcher, load_default_template, render_receipt_pdf


def _payment(**kwargs):
    defaults = dict(
        amount=Decimal("15000.00"),
        paid_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        payment_method="cash",
        reference_number="REF-1",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _render(template_html=None, **kwargs):
    return render_receipt_pdf(
        template_html=template_html or load_default_template(),
        receipt_number=kwargs.pop("receipt_number", 1),
        payment=kwargs.pop("payment", _payment()),
        property_=kwargs.pop("property_", SimpleNamespace(name="Sunset Villa")),
        tenant=kwargs.pop("tenant", SimpleNamespace(full_name="Jane Doe")),
    )


class TestLoadDefaultTemplate:
    def test_loads_html_containing_jinja_placeholders(self):
        html = load_default_template()
        assert "{{ receipt_number }}" in html
        assert "<html>" in html


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
