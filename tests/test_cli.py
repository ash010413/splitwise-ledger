import sys

import httpx
import pytest

from splitwise_ledger import cli


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "token mismatch"),
        (503, "restart the backend"),
    ],
)
def test_cli_reports_actionable_errors_without_response_secrets(monkeypatch, status, expected):
    monkeypatch.setattr(sys, "argv", ["cli", "connect"])
    monkeypatch.setattr(cli, "Settings", lambda: type("Config", (), {"app_api_token": "test"})())
    response = httpx.Response(
        status, json={"detail": "secret-value"}, request=httpx.Request("POST", "http://test")
    )
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: response)
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert expected in str(caught.value)
    assert "secret-value" not in str(caught.value)
