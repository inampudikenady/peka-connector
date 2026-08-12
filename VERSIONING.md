# PEKA Connector versioning

PEKA Connector uses semantic versioning: `MAJOR.MINOR.PATCH`.

## MAJOR

A breaking architecture, API, or deployment change. Examples include the connector data-plane
redesign, an incompatible connector API change, or replacement of the packaging model.

## MINOR

A major new backward-compatible capability. Examples include a VMware or SolarWinds integration,
a new local document knowledge capability, or a connector-management capability.

## PATCH

A bug fix or small non-breaking improvement. Examples include a retry bug, incorrect status,
logging fix, or UI correction.

Every major development milestone must result in an explicit version decision before
merge/release. Architectural milestones must never be released without an intentional version
change.

`VERSION` is the authoritative PEKA Connector version. `release.json` is the shipped component
manifest and must match `VERSION`; release validation tests enforce that relationship.
