"""Task 1.3: base.html renders with no context."""

from __future__ import annotations

from django.template.loader import render_to_string


class TestBaseTemplateSmokeRender:
    def test_renders_with_no_context(self):
        html = render_to_string("report_ui/base.html")

        assert "<html" in html
        assert "Guardrail verification" in html
