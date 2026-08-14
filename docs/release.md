# Connector release procedure

`VERSION` is the authoritative release value. `PEKA_CONNECTOR_VERSION` is a build input that must
match it. The Docker build validates the match, writes the value
into the installed Python package metadata, adds it to the OCI image labels, and exposes that
same runtime value through health, overview, diagnostics, registration, heartbeat, and document
delivery metadata. The About page reads the health API rather than maintaining its own version.

The customer-resident data-plane baseline is `2.0.1`. It bundles Qdrant `1.14.1`; the shipped
component mapping is recorded in `release.json` and exposed by `/api/v1/version`.

Accepted versions use semantic/PEP 440 syntax, including releases such as `0.3.0`, pre-releases
such as `0.4.0-rc.1` or `0.4.0rc1`, and development builds such as `0.4.0-dev` or
`0.4.0.dev0`. Invalid or ambiguous values such as `latest`, `v0.3.0`, and `0.3` fail the image
build. A generated runtime module preserves the exact build input because Python package metadata
may normalize equivalent pre-release spellings.

## Build and test

Run the normal verification suite before creating a release:

```sh
.venv/bin/ruff check backend
.venv/bin/mypy backend/app
.venv/bin/pytest backend
cd frontend && npm ci && npm run lint && npm run test && npm run build
cd ..
docker compose config
```

Set immutable build identity values, then build the same image used by both Compose services:

```sh
export PEKA_CONNECTOR_VERSION="$(tr -d '\r\n' < VERSION)"
export PEKA_BUILD_REVISION="$(git rev-parse HEAD)"
export PEKA_BUILD_CREATED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export PEKA_BUILD_SOURCE="https://example.invalid/peka/peka-connector"
docker compose build --no-cache
docker compose up -d
```

Replace `PEKA_BUILD_SOURCE` with the canonical repository URL in the release environment. Tag the
source revision and image with the same release version according to the deployment registry
policy:

```sh
git tag -a "v${PEKA_CONNECTOR_VERSION}" -m "PEKA Connector ${PEKA_CONNECTOR_VERSION}"
git push origin "v${PEKA_CONNECTOR_VERSION}"
docker tag "peka-connector:${PEKA_CONNECTOR_VERSION}" \
  "registry.example.invalid/peka-connector:${PEKA_CONNECTOR_VERSION}"
docker push "registry.example.invalid/peka-connector:${PEKA_CONNECTOR_VERSION}"
```

Use the deployment's real registry name. Update the release notes before tagging. Do not edit the
About page or application constants for each build, and do not rely on a mutable `latest` tag as
the only release reference.

## Verify release identity

```sh
docker image inspect "peka-connector:${PEKA_CONNECTOR_VERSION}" \
  --format '{{json .Config.Labels}}'
curl -fsS http://localhost:8080/api/v1/health
docker compose logs connector | grep 'PEKA Connector starting version='
```

After signing in, verify that Overview and Diagnostics report the same version. A normal heartbeat
updates PEKA SaaS with that version; rebuilding or restarting the connector does not change its
persistent instance ID or connector registration. If SaaS inventory does not consume the version
from heartbeat payloads, SaaS needs a separate inventory-display change—do not re-register the
connector to compensate.
