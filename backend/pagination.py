"""
API-02 (pagination/filtering/sorting): a real, reusable LIMIT/OFFSET
pagination + sort-direction + total-count contract for endpoints whose
result set can grow unbounded per tenant over the product's lifetime --
ingestion history (DATA-08), audit lineage (ENT-03), and report export
history (REP-02). Each of those three already existed with a bare
`limit` param and no way to page past it, no filter, and a fixed sort
order.

Deliberately NOT retrofitted onto every GET endpoint in the app: most
(team roster, API keys, sessions, assumptions) are bounded by something
else already (team size, practical key/session counts) and gain nothing
real from pagination -- adding it there would be surface-area for its
own sake, not a real need. Same project convention as TEN-04's contained
slice: pick the honest, real need, not every endpoint the item's title
could technically cover.

This module owns the shape every paginated response follows (`items`,
`total_count`, `limit`, `offset`, `has_more`) so the three real callers
build an identical envelope rather than three subtly different ones --
db_manager.py's three query functions each still own their own SQL
(different tables, different filter columns), this only standardizes
what wraps their results.
"""
from typing import List


def envelope(items: List[dict], total_count: int, limit: int, offset: int) -> dict:
    """The one shared response shape for a page of results. has_more is
    computed from total_count/offset/len(items), never trusted from the
    caller, so it's always consistent with what was actually returned."""
    return {
        "items": items,
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(items)) < total_count,
    }


def clamp_limit(limit: int, default: int = 20, minimum: int = 1, maximum: int = 200) -> int:
    """Same clamp-don't-reject convention db_manager's own pre-API-02
    `limit` params already used (e.g. get_ingestion_history) -- an
    out-of-range value is silently brought into range rather than a 422,
    since a too-large limit isn't a client error worth failing the whole
    request over."""
    if limit is None:
        return default
    return max(minimum, min(int(limit), maximum))


def clamp_offset(offset: int) -> int:
    if offset is None or offset < 0:
        return 0
    return int(offset)


def normalize_sort(sort: str, default: str = "desc") -> str:
    sort = (sort or default).strip().lower()
    return sort if sort in ("asc", "desc") else default
