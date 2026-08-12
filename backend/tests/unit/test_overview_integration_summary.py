from app.infrastructure.database.models.integration import ConnectorIntegrationModel
from app.infrastructure.database.repositories.operations import summarize_external_integrations


def integration(
    integration_type: str,
    *,
    enabled: bool = True,
    status: str = "healthy",
) -> ConnectorIntegrationModel:
    return ConnectorIntegrationModel(
        connector_id="connector-id",
        integration_type=integration_type,
        display_name=integration_type,
        category="test",
        enabled=enabled,
        status=status,
    )


def test_no_integrations_have_zero_summary_counts() -> None:
    assert summarize_external_integrations([]) == {
        "enabled": 0,
        "healthy": 0,
        "attention": 0,
    }


def test_knowledge_store_is_not_an_integration() -> None:
    assert summarize_external_integrations([integration("documents")]) == {
        "enabled": 0,
        "healthy": 0,
        "attention": 0,
    }


def test_one_healthy_external_integration() -> None:
    assert summarize_external_integrations([integration("prometheus")]) == {
        "enabled": 1,
        "healthy": 1,
        "attention": 0,
    }


def test_one_unhealthy_external_integration_needs_attention() -> None:
    assert summarize_external_integrations(
        [integration("loki", status="degraded")]
    ) == {"enabled": 1, "healthy": 0, "attention": 1}


def test_disabled_and_unconfigured_integrations_do_not_count() -> None:
    assert summarize_external_integrations(
        [integration("prometheus", enabled=False), integration("loki", enabled=False)]
    ) == {"enabled": 0, "healthy": 0, "attention": 0}
