# PEKA design tokens

Connector uses the same semantic PEKA token contract as SaaS. The CSS variables live
in `frontend/src/peka-tokens.css`; `frontend/src/pekaTheme.ts` maps them into MUI's
palette, typography, controls, tables, cards, tabs, and focus treatment.

PEKA SaaS remains the baseline. Because SaaS and Connector are separate builds, the
token file is mirrored rather than imported across repository boundaries. This is a
temporary constraint until a versioned shared UI package is introduced. Token names
and values must remain aligned with `peka-saas/frontend/app/peka-tokens.css`.

Components should consume semantic tokens or the MUI theme. Do not add page-local
literal colors. Green, amber, red, blue, and gray are reserved for semantic state.
