"""Stable integration catalog metadata; no credentials or runtime state live here."""

from typing import Any

INTEGRATION_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "integration_type": "prometheus",
        "name": "Prometheus",
        "category": "Monitoring",
        "provider_roles": ["monitoring"],
        "capabilities": {"targets": True, "metrics": True, "health": True},
        "available": True,
        "configuration_fields": ["base_url", "authentication", "validate_tls", "polling_interval"],
    },
    {
        "integration_type": "loki",
        "name": "Loki",
        "category": "Logs",
        "provider_roles": ["logs"],
        "capabilities": {"logs": True, "evidence": True},
        "available": True,
        "configuration_fields": ["base_url", "authentication", "validate_tls", "request_timeout"],
    },
    {
        "integration_type": "zammad",
        "name": "Zammad",
        "category": "Ticketing",
        "provider_roles": ["ticketing"],
        "capabilities": {"tickets": True},
        "available": True,
        "configuration_fields": ["base_url", "access_token", "validate_tls", "sync_interval"],
    },
    {
        "integration_type": "servicenow",
        "name": "ServiceNow",
        "category": "Ticketing / CMDB",
        "provider_roles": ["ticketing", "cmdb"],
        "capabilities": {
            "incidents": True,
            "problems": True,
            "changes": True,
            "cmdb": True,
            "relationships": True,
            "service_catalog": False,
        },
        "available": True,
        "configuration_fields": [
            "instance_url",
            "username",
            "password",
            "verify_tls",
            "request_timeout_seconds",
            "page_size",
            "sync_interval_seconds",
        ],
    },
    {
        "integration_type": "solarwinds",
        "name": "SolarWinds",
        "category": "Monitoring",
        "provider_roles": ["monitoring"],
        "capabilities": {
            "nodes": True,
            "alerts": True,
            "interfaces": False,
            "volumes": False,
            "performance_metrics": True,
        },
        "available": False,
        "unavailable_reason": "The SolarWinds adapter is not implemented yet.",
        "configuration_fields": [
            "platform_url",
            "authentication_method",
            "username",
            "password",
            "token",
            "validate_tls",
            "polling_interval",
            "node_scope",
            "alert_scope",
            "collect_interfaces",
        ],
    },
    {
        "integration_type": "vmware_vcenter",
        "name": "VMware vCenter",
        "category": "Virtualization",
        "provider_roles": ["virtualization"],
        "capabilities": {
            "inventory": True,
            "health": True,
            "performance": True,
            "events": False,
            "datastore_capacity": True,
        },
        "available": False,
        "unavailable_reason": "The VMware vCenter adapter is not implemented yet.",
        "configuration_fields": [
            "vcenter_url",
            "username",
            "password",
            "validate_tls",
            "datacenter_scope",
            "cluster_scope",
            "inventory_sync_interval",
            "performance_collection_interval",
        ],
    },
    {
        "integration_type": "generic_cmdb",
        "name": "Local CMDB",
        "category": "CMDB",
        "provider_roles": ["cmdb"],
        "capabilities": {"inventory": True},
        "available": True,
        "configuration_fields": ["dataset"],
    },
    {
        "integration_type": "documents",
        "name": "Documents",
        "category": "Knowledge",
        "provider_roles": ["knowledge"],
        "capabilities": {"documents": True},
        "available": True,
        "configuration_fields": ["path", "scan_interval"],
    },
)

CATALOG_BY_TYPE = {item["integration_type"]: item for item in INTEGRATION_CATALOG}

STREAMS: tuple[str, ...] = ("monitoring", "logs", "ticketing", "cmdb", "knowledge")

STREAM_SOURCES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "prometheus": (("monitoring", "prometheus", "Prometheus"),),
    "loki": (("logs", "loki", "Loki"),),
    "zammad": (("ticketing", "zammad", "Zammad"),),
    "servicenow": (
        ("ticketing", "servicenow", "ServiceNow"),
        ("cmdb", "servicenow_cmdb", "ServiceNow CMDB"),
    ),
    "generic_cmdb": (("cmdb", "local_cmdb", "Local CMDB"),),
    "documents": (("knowledge", "documents", "Documents"),),
}

ROLE_CAPABILITIES: dict[str, dict[str, set[str]]] = {
    "ticketing": {
        "zammad": {"tickets"},
        "servicenow": {"incidents"},
    },
    "monitoring": {
        "prometheus": {"metrics"},
        "solarwinds": {"performance_metrics"},
    },
    "logs": {"loki": {"logs"}},
    "cmdb": {"generic_cmdb": {"inventory"}, "servicenow": {"cmdb"}},
    "virtualization": {"vmware_vcenter": {"inventory"}},
    "knowledge": {"documents": {"documents"}},
}

SECRET_FIELDS = {"access_token", "password", "client_secret", "token", "oauth_client_secret"}
