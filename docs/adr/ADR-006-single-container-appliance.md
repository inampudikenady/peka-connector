# ADR-006: Single-container production appliance

- Status: Accepted
- Date: 2026-07-20

## Context

PEKA Connector is delivered as an on-premises appliance. Separate frontend and backend production containers add orchestration, networking, upgrade, diagnostics, and support complexity without providing a useful scaling boundary for a local single-instance connector.

## Decision

Produce one multi-stage Docker image. A Node.js stage compiles React, a Python stage installs the backend, and a minimal Python runtime contains both outputs. FastAPI serves versioned API routes and the compiled SPA on port 8080. SQLite uses `/data`, and customer documents are mounted at `/documents` read-only. The repository retains separate backend and frontend source trees and a two-process local development workflow.

## Consequences

Customers install, upgrade, monitor, and back up one container. UI and API versions are released atomically, and no internal reverse proxy is required. The frontend cannot be scaled or deployed independently in production, which is consistent with the appliance model. Changing UI assets requires rebuilding the appliance image.
