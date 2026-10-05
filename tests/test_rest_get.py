"""Unit tests for REST http_get URL / path SSRF guards."""

from app.tools.rest_get import build_request_url, path_allowed


def test_path_allowed_under_prefix():
    allowed = ["/v1/orders", "/v1/customers"]
    assert path_allowed("/v1/orders", allowed)
    assert path_allowed("/v1/orders/123", allowed)
    assert path_allowed("v1/customers", allowed)
    assert not path_allowed("/v1/admin", allowed)
    assert not path_allowed("/v1/orders/../admin", allowed)
    assert not path_allowed("https://evil.example/v1/orders", allowed)


def test_path_allowed_empty_deny():
    assert not path_allowed("/anything", [])


def test_build_request_url_joins_and_keeps_host():
    url, err = build_request_url(
        "https://api.example.com/base",
        "/v1/orders",
        {"page": "1"},
    )
    assert err is None
    assert url == "https://api.example.com/base/v1/orders?page=1"


def test_build_request_url_rejects_traversal_and_absolute():
    url, err = build_request_url("https://api.example.com", "../secret", None)
    assert url is None
    assert err is not None

    url, err = build_request_url(
        "https://api.example.com", "https://evil.example/x", None
    )
    assert url is None
    assert err is not None


def test_build_request_url_rejects_bad_scheme():
    url, err = build_request_url("ftp://api.example.com", "/x", None)
    assert url is None
    assert err is not None
