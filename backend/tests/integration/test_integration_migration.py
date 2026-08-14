import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _alembic(backend: Path, database: Path, revision: str) -> None:
    environment = {
        **os.environ,
        "PEKA_JWT_SECRET": "migration-test-secret-that-is-long-enough",
        "PEKA_DATABASE_URL": f"sqlite+aiosqlite:///{database}",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=backend,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_existing_zammad_migrates_without_obsolete_provider_binding(
    tmp_path: Path,
) -> None:
    backend = Path(__file__).resolve().parents[2]
    database = tmp_path / "migration.db"
    _alembic(backend, database, "20260801_0011")
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            INSERT INTO product_settings
              (id, connector_display_name, environment_label, log_level, timezone,
               saas_status, connector_id, updated_at, heartbeat_interval_seconds,
               heartbeat_failure_count, heartbeat_job_enabled)
            VALUES
              (1, 'Connector', 'lab', 'INFO', 'UTC', 'registered', 'connector-a',
               '2026-08-03 00:00:00', 300, 0, 0);

            INSERT INTO zammad_configurations
              (id, name, instance_key, base_url, encrypted_access_token, token_configured,
               tls_verify, request_timeout_seconds, sync_interval_seconds,
               history_window_days, group_filters_json, include_closed_tickets, enabled,
               connection_state, last_successful_test_at, last_successful_sync_at,
               synchronized_ticket_count, synchronized_article_count, created_at, updated_at)
            VALUES
              ('11111111111111111111111111111111', 'Zammad', 'instance-a',
               'https://zammad.test', 'encrypted-ciphertext-preserved', 1, 1, 15, 900,
               90, '[]', 1, 1, 'connected', '2026-08-03 00:00:00',
               '2026-08-03 00:00:00', 1, 0, '2026-08-03 00:00:00',
               '2026-08-03 00:00:00');

            INSERT INTO zammad_tickets
              (id, configuration_id, instance_key, source, external_id, number, title,
               state, state_type, tags_json, created_at_source, updated_at_source,
               is_open, ticket_type, referenced_asset_ids_json,
               referenced_hostnames_json, referenced_fqdns_json,
               referenced_ip_addresses_json, search_text, visible, synchronized_at,
               created_at, updated_at, ticket_type_reason, asset_relationships_json)
            VALUES
              ('22222222222222222222222222222222',
               '11111111111111111111111111111111', 'instance-a', 'zammad', '1',
               '11007', 'Memory issue', 'open', 'open', '[]',
               '2026-08-03 00:00:00', '2026-08-03 00:00:00', 1, 'incident',
               '[]', '[]', '[]', '[]', 'memory issue', 1, '2026-08-03 00:00:00',
               '2026-08-03 00:00:00', '2026-08-03 00:00:00', '', '[]');
            """
        )
        connection.commit()
    finally:
        connection.close()

    _alembic(backend, database, "head")
    connection = sqlite3.connect(database)
    try:
        integration = connection.execute(
            "SELECT id, enabled FROM connector_integrations "
            "WHERE connector_id='connector-a' AND integration_type='zammad'"
        ).fetchone()
        assert integration is not None and integration[1] == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "connector_provider_bindings" not in tables
        activation = connection.execute(
            "SELECT stream, source_key, enabled, active "
            "FROM integration_stream_activations WHERE integration_id=?",
            (integration[0],),
        ).fetchone()
        assert activation == ("ticketing", "zammad", 1, 1)
        cache = connection.execute(
            "SELECT integration_id, integration_type, cache_status "
            "FROM zammad_tickets WHERE number='11007'"
        ).fetchone()
        assert cache == (integration[0], "zammad", "active")
        secret = connection.execute(
            "SELECT encrypted_access_token FROM zammad_configurations "
            "WHERE id='11111111111111111111111111111111'"
        ).fetchone()
        assert secret == ("encrypted-ciphertext-preserved",)
    finally:
        connection.close()


def test_v2_stream_state_prefers_active_source_and_retains_alternate_configuration(
    tmp_path: Path,
) -> None:
    backend = Path(__file__).resolve().parents[2]
    database = tmp_path / "selected-source-migration.db"
    _alembic(backend, database, "20260813_0017")
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            INSERT INTO connector_integrations
              (id, connector_id, integration_type, display_name, category, enabled, status,
               configuration_json, capabilities_json, initial_sync_status, created_at, updated_at)
            VALUES
              ('11111111111111111111111111111111', 'connector-a', 'servicenow',
               'ServiceNow', 'Ticketing / CMDB', 1, 'healthy', '{}',
               '{"incidents": true, "cmdb": false}', 'completed',
               '2026-08-13 09:00:00', '2026-08-13 09:00:00'),
              ('22222222222222222222222222222222', 'connector-a', 'zammad',
               'Zammad', 'Ticketing', 1, 'configured', '{}', '{"tickets": true}',
               'not_started', '2026-08-13 10:00:00', '2026-08-13 10:00:00');

            INSERT INTO integration_stream_activations
              (id, connector_id, integration_id, stream, source_key, source_name,
               enabled, active, activated_at, created_at, updated_at)
            VALUES
              ('33333333333333333333333333333333', 'connector-a',
               '11111111111111111111111111111111', 'ticketing', 'servicenow',
               'ServiceNow', 1, 1, '2026-08-13 09:00:00',
               '2026-08-13 09:00:00', '2026-08-13 09:00:00'),
              ('44444444444444444444444444444444', 'connector-a',
               '22222222222222222222222222222222', 'ticketing', 'zammad',
               'Zammad', 1, 0, NULL, '2026-08-13 10:00:00', '2026-08-13 10:00:00');
            """
        )
        connection.commit()
    finally:
        connection.close()

    _alembic(backend, database, "head")
    connection = sqlite3.connect(database)
    try:
        activations = connection.execute(
            "SELECT source_key, enabled, active FROM integration_stream_activations "
            "WHERE stream='ticketing' ORDER BY source_key"
        ).fetchall()
        assert activations == [("servicenow", 1, 1), ("zammad", 0, 0)]
        integrations = connection.execute(
            "SELECT integration_type, enabled, configuration_json "
            "FROM connector_integrations ORDER BY integration_type"
        ).fetchall()
        assert integrations == [
            ("servicenow", 1, "{}"),
            ("zammad", 0, "{}"),
        ]
    finally:
        connection.close()
