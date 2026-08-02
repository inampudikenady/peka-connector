"""Central deterministic Zammad concepts, ticket types, and relevance scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass

CONCEPT_FAMILIES: dict[str, tuple[str, ...]] = {
    "memory": (
        "memory pressure",
        "out of memory",
        "resident memory",
        "memory utilization",
        "memory usage",
        "memory leak",
        "allocation failure",
        "allocation",
        "swapping",
        "swap",
        "heap",
        "oom",
        "memory",
        "ram",
    ),
    "access_request": (
        "please grant access",
        "grant access",
        "need access",
        "asking for access",
        "add user to group",
        "request permission",
        "permission request",
        "grant role",
        "assign entitlement",
        "need sudo",
        "authorize user",
        "provision access",
        "access request",
        "group membership",
    ),
    "authentication_incident": (
        "domain authentication",
        "invalid credentials",
        "account locked",
        "active directory",
        "secure channel",
        "authentication",
        "credentials",
        "credential",
        "password",
        "kerberos",
        "login",
        "log in",
        "sign in",
        "ldap",
        "ntlm",
        "sso",
    ),
    "authorization_incident": (
        "access denied",
        "permission denied",
        "insufficient privileges",
        "unauthorized operation",
        "forbidden",
    ),
    "account_administration": (
        "unlock account",
        "reset password",
        "disable account",
        "create account",
        "remove account",
    ),
    "disk": (
        "disk space",
        "filesystem usage",
        "file system",
        "filesystem",
        "inode",
        "volume",
        "mount",
        "storage",
        "disk",
    ),
    "network": (
        "packet loss",
        "connection timeout",
        "network",
        "connection",
        "connectivity",
        "unreachable",
        "dns",
        "route",
        "firewall",
        "latency",
    ),
    "application_failure": (
        "application failure",
        "service failed",
        "process crashed",
        "stack trace",
        "fatal error",
        "exception",
    ),
}

# These concepts are unsafe to infer from their generic neighboring words. For
# example, "storage pressure" is not memory evidence and "heartbeat failed" is
# not authentication evidence. At least one explicit anchor must be present in
# the ticket content before normal field weighting is allowed.
_REQUIRED_CONTENT_ANCHORS: dict[str, tuple[str, ...]] = {
    "memory": CONCEPT_FAMILIES["memory"],
    "authentication_incident": CONCEPT_FAMILIES["authentication_incident"],
}

_QUERY_STOP_WORDS = {
    "about",
    "related",
    "tickets",
    "ticket",
    "there",
    "where",
    "user",
    "asking",
    "show",
    "find",
    "have",
    "with",
    "mentioning",
    "problems",
    "problem",
}


@dataclass(frozen=True)
class RelevanceResult:
    score: float
    confidence: str
    reasons: list[str]
    concept_family: str | None

    @property
    def accepted(self) -> bool:
        return self.score >= 0.65


def _contains(text: str, phrase: str) -> bool:
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(phrase.casefold())}(?![a-z0-9])",
            text.casefold(),
        )
    )


def infer_concept_family(query: str) -> str | None:
    lowered = query.casefold()
    # Specific security families must win over the ambiguous word "access".
    for family in (
        "authentication_incident",
        "authorization_incident",
        "account_administration",
    ):
        if any(_contains(lowered, phrase) for phrase in CONCEPT_FAMILIES[family]):
            return family
    if (
        any(_contains(lowered, phrase) for phrase in CONCEPT_FAMILIES["access_request"])
        or "asking for access" in lowered
        or ("access" in lowered and re.search(r"\b(?:request|grant|need|provision)\b", lowered))
    ):
        return "access_request"
    for family in ("memory", "disk", "network", "application_failure"):
        if family.replace("_", " ") in lowered or any(
            _contains(lowered, phrase) for phrase in CONCEPT_FAMILIES[family]
        ):
            return family
    if re.search(r"\b(?:login|authentication|kerberos|password)\b", lowered):
        return "authentication_incident"
    return None


def expand_concepts(query: str) -> set[str]:
    family = infer_concept_family(query)
    tokens = {
        token
        for token in re.findall(r"[a-z0-9_.-]+", query.casefold())
        if len(token) > 3 and token not in _QUERY_STOP_WORDS
    }
    if family:
        tokens.update(CONCEPT_FAMILIES[family])
    return tokens


def score_ticket_relevance(
    query: str,
    *,
    ticket_number: str,
    title: str,
    initial_description: str | None,
    article_bodies: list[str],
    tags: list[str],
    asset_identifiers: list[str],
) -> RelevanceResult:
    lowered_query = query.casefold().strip()
    family = infer_concept_family(query)
    title_text = title.casefold()
    description = (initial_description or "").casefold()
    articles = "\n".join(article_bodies).casefold()
    tag_text = "\n".join(tags).casefold()
    reasons: list[str] = []
    signals: list[float] = []

    if lowered_query.lstrip("#") == ticket_number.casefold():
        return RelevanceResult(1.0, "high", ["Exact ticket number match"], family)

    family_phrases = list(CONCEPT_FAMILIES.get(family or "", ()))
    query_phrases = [
        phrase.strip()
        for phrase in re.findall(r"[a-z0-9]+(?:[ -][a-z0-9]+)+", lowered_query)
        if len(phrase.strip()) >= 5
    ]
    phrases = list(dict.fromkeys([*query_phrases, *family_phrases]))

    required_anchors = _REQUIRED_CONTENT_ANCHORS.get(family or "")
    if required_anchors:
        anchor_matches = [
            phrase
            for phrase in required_anchors
            if any(
                _contains(field, phrase)
                for field in (title_text, description, articles, tag_text)
            )
        ]
        if not anchor_matches:
            label = "authentication" if family == "authentication_incident" else family
            return RelevanceResult(
                0.0,
                "rejected",
                [f"Rejected: no explicit {label} anchor in ticket content"],
                family,
            )

    # An access request requires request/provisioning evidence. Authentication,
    # authorization, and account failures are deliberately negative evidence.
    if family == "access_request":
        request_evidence = [
            phrase
            for phrase in CONCEPT_FAMILIES["access_request"]
            if any(_contains(field, phrase) for field in (title_text, description, articles))
        ]
        negative = [
            phrase
            for other in (
                "authentication_incident",
                "authorization_incident",
                "account_administration",
            )
            for phrase in CONCEPT_FAMILIES[other]
            if any(_contains(field, phrase) for field in (title_text, description, articles))
        ]
        if negative and not request_evidence:
            return RelevanceResult(
                0.0,
                "rejected",
                [f"Rejected: {negative[0]} describes a different security intent"],
                family,
            )

    for phrase in phrases:
        if _contains(title_text, phrase):
            signals.append(0.95)
            reasons.append(f"Exact title match: {phrase}")
            break
    if not signals:
        significant = {
            token
            for token in re.findall(r"[a-z0-9]+", lowered_query)
            if len(token) > 3 and token not in _QUERY_STOP_WORDS
        }
        if family:
            significant.update(
                token
                for phrase in family_phrases
                for token in re.findall(r"[a-z0-9]+", phrase)
                if len(token) > 3
            )
        title_tokens = significant & set(re.findall(r"[a-z0-9]+", title_text))
        if title_tokens:
            signals.append(0.85)
            reasons.append(f"Title token match: {', '.join(sorted(title_tokens)[:3])}")

    for field, weight, label in (
        (description, 0.80, "Initial description contains"),
        (articles, 0.75, "Article body contains"),
        (tag_text, 0.70, "Tag match"),
    ):
        matched = next((phrase for phrase in phrases if _contains(field, phrase)), None)
        if matched:
            signals.append(weight)
            reasons.append(f"{label}: {matched}")

    asset_match = next(
        (
            value
            for value in asset_identifiers
            if value and _contains(lowered_query, value.casefold())
        ),
        None,
    )
    if asset_match:
        signals.append(0.90)
        reasons.append(f"Canonical asset match: {asset_match}")

    if not signals:
        generic_tokens = expand_concepts(query)
        matched = next(
            (
                token
                for token in generic_tokens
                if len(token) > 3
                and any(_contains(field, token) for field in (title_text, description, articles))
            ),
            None,
        )
        if matched:
            signals.append(0.25)
            reasons.append(f"Generic token match: {matched}")

    if not signals:
        return RelevanceResult(0.0, "rejected", ["No defensible content match"], family)
    score = min(1.0, max(signals) + min(0.08, 0.03 * (len(signals) - 1)))
    confidence = "high" if score >= 0.85 else "medium" if score >= 0.65 else "low"
    return RelevanceResult(round(score, 2), confidence, reasons, family)


def classify_ticket_type(text: str) -> tuple[str, str]:
    lowered = text.casefold()
    if any(_contains(lowered, phrase) for phrase in CONCEPT_FAMILIES["access_request"]):
        return "access_request", "Access provisioning or permission request language"
    if re.search(
        r"\b(?:reboot|required reboot|windows updates?|patch(?:ing)?|maintenance window|"
        r"scheduled maintenance|firmware update)\b",
        lowered,
    ):
        return "maintenance", "Scheduled maintenance, update, or reboot language"
    if re.search(r"\b(?:change request|planned change|deploy|migration|upgrade)\b", lowered):
        return "change", "Planned change language"
    if re.search(r"\b(?:root cause|recurring issue|known problem|problem record)\b", lowered):
        return "problem", "Problem-management language"
    if any(
        _contains(lowered, phrase)
        for family in (
            "authentication_incident",
            "authorization_incident",
            "application_failure",
        )
        for phrase in CONCEPT_FAMILIES[family]
    ) or re.search(
        r"\b(?:outage|unreachable|degraded|failed|failure|error|crash|oom|alert|"
        r"cannot scrape|high cpu|high memory|disk full)\b",
        lowered,
    ):
        return "incident", "Failure, outage, alert, or degradation evidence"
    if re.search(r"\b(?:service request|request for|please provide|please install)\b", lowered):
        return "service_request", "General fulfillment request language"
    if re.search(r"\b(?:for information|informational|notice|fyi)\b", lowered):
        return "informational", "Informational language"
    return "unknown", "No deterministic ticket-type evidence"
