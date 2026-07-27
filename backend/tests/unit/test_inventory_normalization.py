from app.application.services.inventory import (
    endpoint_identity,
    normalize_cmdb_row,
    normalize_hostname,
    normalize_ip,
)
from app.application.services.prometheus import target_identities, validate_base_url


def test_hostname_fqdn_ip_and_empty_normalization() -> None:
    assert normalize_hostname(" Web01.EXAMPLE.com. ") == ("Web01.EXAMPLE.com", "web01")
    assert normalize_hostname(" Web01.EXAMPLE.com. ", fqdn=True) == (
        "Web01.EXAMPLE.com",
        "web01.example.com",
    )
    assert normalize_ip("2001:0db8::1") == ("2001:0db8::1", "2001:db8::1")
    assert normalize_ip("999.1.1.1") == ("999.1.1.1", None)
    assert normalize_hostname("   ") == (None, None)


def test_cmdb_row_requires_identity_and_preserves_display_case() -> None:
    normalized, errors = normalize_cmdb_row(
        {"Host": "  WEB01  ", "Owner": "  Platform Team  "},
        {"Host": "hostname", "Owner": "technical_owner"},
    )
    assert normalized["hostname"] == "WEB01"
    assert normalized["hostname_normalized"] == "web01"
    assert normalized["technical_owner"] == "Platform Team"
    assert errors == []

    _, errors = normalize_cmdb_row({"Owner": "Nobody"}, {"Owner": "technical_owner"})
    assert errors == ["at least one usable identity field is required"]


def test_prometheus_endpoint_parsing_strips_ports_without_dns() -> None:
    assert endpoint_identity("https://WEB01.example.com:9100/metrics") == (
        "fqdn",
        "web01.example.com",
    )
    assert endpoint_identity("10.0.0.7:9100") == ("ip_address", "10.0.0.7")
    assert endpoint_identity("[2001:db8::7]:9100") == ("ip_address", "2001:db8::7")
    identities = target_identities(
        {
            "scrapeUrl": "http://web01.example.com:9100/metrics",
            "labels": {"instance": "web01.example.com:9100", "job": "node"},
            "discoveredLabels": {"__address__": "web01.example.com:9100"},
        }
    )
    assert ("fqdn", "web01.example.com:9100", "web01.example.com") in identities
    assert ("hostname", "web01.example.com:9100", "web01") in identities


def test_prometheus_url_rejects_credentials_and_unsupported_schemes() -> None:
    assert validate_base_url("https://prometheus.example.com/") == (
        "https://prometheus.example.com"
    )
    for value in ("file:///etc/passwd", "https://user:pass@example.com", "ftp://example.com"):
        try:
            validate_base_url(value)
        except Exception:
            pass
        else:
            raise AssertionError(f"{value} should be rejected")
