"""Price an international whale bet on Polymarket US (public gateway).

Used by the 'US shadow' comparison book: for each trade Coattail copies at the
international price, we also look up what it would cost on Polymarket US, so the
two equity curves can be compared.

Two matchers run off the SAME fetched event, so their prices are apples-to-apples
at the same instant:

  • `legacy`  — the original behaviour: match the *event*, then return the first
    market in it whose outcome string matches. Kept only so the existing shadow
    curve keeps accruing and can be compared against the fix. It is WRONG: a
    football event carries dozens of Yes/No markets (winner, draw, both-teams-
    to-score, spreads, totals…) and this returns whichever happens to be first,
    so it routinely prices a different question than the one that was bet.

  • `strict`  — matches the *market* as well, and prices it correctly. The
    trade's title and outcome are reduced to a claim (kind, team, line, side)
    and compared against the same reduction of each US market's question. No
    confident match → None. A low match rate with correct prices beats a high
    one with noise.

Price semantics (why `legacy` is doubly wrong)
---------------------------------------------
A US market is ONE binary proposition ("Will St Mirren FC win against Falkirk
FC…"), and `outcomePrices` is `[bestBid, bestAsk]` for that proposition — NOT a
price per entry of the `outcomes` array. `outcomes` itself is unordered: the
same event returns both `["Yes","No"]` and `["No","Yes"]`. Verified against the
`bestBidQuote`/`bestAskQuote` fields, and by the three-way soccer market summing
to ~1.00 across asks (Falkirk 0.03 + draw 0.20 + St Mirren 0.80).

So buying costs:
    Yes  →  bestAsk
    No   →  1 − bestBid        (selling Yes at the bid is buying No)

The legacy matcher indexes `outcomePrices[i]` by outcome index, so it reads a
bid as "Yes" and an ask as "No" — of a market it picked arbitrarily.

Note: markets carry `feeCoefficient` (0.06 on the samples inspected) against the
assumed `US_FEE_RATE` of 0.01. How that coefficient enters the real fee is not
documented here, so it is recorded but not applied — see US_FEE_RATE below.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

import httpx

GATEWAY = "https://gateway.polymarket.us"

# Estimated all-in Polymarket US trading cost as a fraction of the dollars
# staked, round-trip. A percent-of-notional model (not per-share) so it doesn't
# balloon on cheap longshot bets.
#
# CAVEAT: live markets report `feeCoefficient: 0.06`. If that is 6% of notional
# this is a 6x underestimate. Its formula isn't published on the gateway, so
# rather than guess we keep the conservative estimate and expose the observed
# coefficient (see UsQuote.fee_coefficient) for calibration later.
US_FEE_RATE = 0.01

# key = teamA-teamB-YYYY-MM-DD  (ignores the differing league prefix: chi vs csl)
_KEY_RE = re.compile(r"-([a-z0-9]+)-([a-z0-9]+)-(\d{4}-\d{2}-\d{2})")
_WORD_RE = re.compile(r"[A-Z][a-zA-Z]{3,}")
_STOP = {"Will", "Half", "Over", "Under", "Spread", "Handicap"}


def _key(slug: str | None) -> str | None:
    m = _KEY_RE.search(slug or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _loads(s) -> list:
    if isinstance(s, list):
        return s
    try:
        return json.loads(s) if s else []
    except (json.JSONDecodeError, TypeError):
        return []


# ── team-name normalisation ──────────────────────────────────
# Club suffixes/prefixes differ across venues ("St Mirren FC" vs "St. Mirren"),
# so they carry no signal and are dropped.
_CLUB_NOISE = {
    "fc", "sc", "cd", "cf", "afc", "ac", "as", "sk", "bk", "ss", "cs", "rc",
    "sv", "vfl", "vfb", "if", "ik", "club", "the", "de", "of", "and",
}
# Tokens shared by many different clubs. A match resting only on these is not a
# match — "Real Salt Lake" and "Real Betis" are not the same team.
_GENERIC = {
    "real", "city", "united", "atletico", "athletic", "sporting", "deportivo",
    "nacional", "san", "santos", "racing", "union", "dynamo", "olympic",
    "national", "new", "york", "los", "st", "saint",
}


def _tokens(s: str) -> frozenset[str]:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return frozenset(t for t in s.split() if t not in _CLUB_NOISE and len(t) > 1)


def _same_team(a: frozenset[str], b: frozenset[str]) -> bool:
    """Same club? Requires overlap on at least one *distinctive* token, so two
    clubs sharing only a generic word ('Real', 'United') don't collide."""
    if not a or not b:
        return False
    if a == b:
        return True
    shared = a & b
    return bool(shared) and bool(shared - _GENERIC)


# ── claims ───────────────────────────────────────────────────
# A "proposition" is what a market asks, venue-independent:
#   ("ml",   team_tokens)     team wins
#   ("draw",)                 the match ends level
#   ("btts",)                 both teams score
#   ("tot",  line, side)      total goals over/under `line`
#   ("spr",  team_tokens, l)  `team` covers the signed line `l`
# A bet is a proposition plus `affirm` (True = buy Yes, False = buy No).
#
# Anything else (halftime, map/period/set winners, first scorer, player props)
# is deliberately unsupported — easy to mis-pair, and rare enough that dropping
# them costs little. Same for "Who will win …" markets, whose bid/ask belongs to
# an unnamed side we can't identify from the question text.
_UNSUPPORTED = re.compile(
    r"halftime|half[- ]time|\bhalf\b|\bmap\s*\d|\bperiod\b|\bquarter\b|\bset\s*\d"
    r"|first to score|first goal|corner|booking|\bcard\b|\bplayer\b|leading at",
    re.I,
)
_NUM = r"[-+]?\d+(?:\.\d+)?"


def _num(s) -> float | None:
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(_NUM, str(s or ""))
    return float(m.group(0)) if m else None


def _kind(text: str) -> str | None:
    t = text or ""
    if _UNSUPPORTED.search(t):
        return None
    if re.search(r"\bcover\b|\bspread\b|\bhandicap\b", t, re.I):
        return "spr"
    if re.search(r"both teams?\s*(to\s*)?score|\bbtts\b", t, re.I):
        return "btts"
    if re.search(r"\bdraw\b", t, re.I):
        return "draw"
    if re.search(r"\bo/u\b|\bover\b|\bunder\b|\btotal\b", t, re.I):
        return "tot"
    if re.search(r"\bwin\b|\bwinner\b|\bbeat\b", t, re.I):
        return "ml"
    return None


def _yes_no(outcome: str) -> bool | None:
    o = (outcome or "").strip().lower()
    if o in ("yes", "y"):
        return True
    if o in ("no", "n"):
        return False
    return None


def _bets_international(title: str, outcome: str) -> list[tuple[tuple, bool]]:
    """Reduce a Coattail trade to the (proposition, affirm) pairs that express
    it. More than one when the same bet can be stated from either side — e.g.
    'Under 2.5' is both 'under 2.5 = Yes' and 'over 2.5 = No'."""
    kind = _kind(title)
    if kind is None:
        return []
    yn = _yes_no(outcome)

    if kind == "draw":
        return [(("draw",), yn)] if yn is not None else []

    if kind == "btts":
        return [(("btts",), yn)] if yn is not None else []

    if kind == "tot":
        # "Club A vs. Club B: O/U 2.5"  outcome Over|Under
        line = _num(re.sub(r".*?(o/u|over|under|total)", "", title, flags=re.I))
        side = (outcome or "").strip().lower()
        if line is None or side not in ("over", "under"):
            return []
        other = "under" if side == "over" else "over"
        return [(("tot", line, side), True), (("tot", line, other), False)]

    if kind == "spr":
        # "Spread: New York City FC (-1.5)"  outcome = the team being backed
        m = re.search(rf"spread:\s*(.+?)\s*\(\s*({_NUM})\s*\)", title, re.I)
        if not m:
            return []
        subject, line = _tokens(m.group(1)), float(m.group(2))
        backed = _tokens(outcome)
        if not backed:
            return []
        # Backing the subject takes its line; backing the opponent flips it.
        mine = line if _same_team(backed, subject) else -line
        bets = [(("spr", backed, mine), True)]
        if not _same_team(backed, subject) and subject:
            # Equivalently: "No" on the subject covering its own line.
            bets.append((("spr", subject, line), False))
        return bets

    # moneyline: "Will <team> win on 2026-07-31?"
    m = re.search(r"will\s+(?:the\s+)?(.+?)\s+win\b", title, re.I)
    if not m or yn is None:
        return []
    team = _tokens(m.group(1))
    return [(("ml", team), yn)] if team else []


def _prop_us(question: str) -> tuple | None:
    """The proposition a US market asks. Its bid/ask quote belongs to this."""
    kind = _kind(question)
    if kind is None:
        return None
    # "Who will win …" names no single side — its quote is unattributable.
    if re.match(r"\s*who\b", question or "", re.I):
        return None

    if kind == "draw":
        return ("draw",)

    if kind == "btts":
        return ("btts",)

    if kind == "tot":
        line = _num(re.sub(r".*?(o/u|over|under|total)", "", question, flags=re.I))
        if line is None:
            return None
        side = "over" if re.search(r"\bover\b", question, re.I) else (
            "under" if re.search(r"\bunder\b", question, re.I) else None
        )
        return ("tot", line, side) if side else None

    if kind == "spr":
        # "Will the St. Louis City SC cover -1.5 vs the Real Salt Lake"
        m = re.search(
            rf"will\s+(?:the\s+)?(.+?)\s+cover\s+({_NUM})\s+vs\.?\s+(?:the\s+)?(.+?)"
            r"(?:\s+in\b|\s+on\b|[?.]|$)",
            question,
            re.I,
        )
        if not m:
            return None
        return ("spr", _tokens(m.group(1)), float(m.group(2)))

    m = re.search(r"will\s+(?:the\s+)?(.+?)\s+win\b", question, re.I)
    if not m:
        return None
    team = _tokens(m.group(1))
    return ("ml", team) if team else None


def _props_match(a: tuple, b: tuple) -> bool:
    if not a or not b or a[0] != b[0]:
        return False
    kind = a[0]
    if kind in ("draw", "btts"):
        return True
    if kind == "tot":
        return abs(a[1] - b[1]) < 1e-9 and a[2] == b[2]
    if kind == "spr":
        return abs(a[2] - b[2]) < 1e-9 and _same_team(a[1], b[1])
    if kind == "ml":
        return _same_team(a[1], b[1])
    return False


# ── quoting ──────────────────────────────────────────────────
def _bid_ask(m: dict) -> tuple[float | None, float | None]:
    """Best bid/ask for the market's proposition. Prefers the explicit quote
    fields; `outcomePrices` is the same pair positionally ([bid, ask])."""
    bid = _num((m.get("bestBidQuote") or {}).get("value") if isinstance(m.get("bestBidQuote"), dict) else None)
    ask = _num((m.get("bestAskQuote") or {}).get("value") if isinstance(m.get("bestAskQuote"), dict) else None)
    if bid is None or ask is None:
        prs = _loads(m.get("outcomePrices"))
        if len(prs) >= 2:
            bid, ask = _num(prs[0]), _num(prs[1])
    return bid, ask


def _cost(m: dict, affirm: bool) -> float | None:
    """What it costs to take this side, at the touch."""
    bid, ask = _bid_ask(m)
    price = ask if affirm else (None if bid is None else 1.0 - bid)
    return price if price is not None and 0.0 < price < 1.0 else None


# ── lookup ───────────────────────────────────────────────────
@dataclass
class UsQuote:
    """Both matchers' prices for one trade, off a single gateway fetch."""
    legacy: float | None = None      # original (event-only) match — for comparison
    strict: float | None = None      # market-aware match, correctly priced
    market: str | None = None        # the US question `strict` actually priced
    fee_coefficient: float | None = None  # venue-reported fee param, for calibration


async def _find_event(client: httpx.AsyncClient, event_slug: str, title: str) -> dict | None:
    k = _key(event_slug)
    if not k:
        return None
    terms = [w for w in _WORD_RE.findall(title or "") if w not in _STOP]
    for term in terms[:2]:
        try:
            r = await client.get(f"{GATEWAY}/v1/search", params={"query": term, "limit": 20}, timeout=12)
            data = r.json()
        except Exception:  # noqa: BLE001
            continue
        for e in data.get("events", []):
            if _key(e.get("slug")) == k:
                return e
    return None


def _legacy_price(event: dict, outcome: str) -> float | None:
    """The original matcher, verbatim: first market in the event whose outcome
    string matches, priced by outcome index. Retained only so the old curve
    keeps accruing next to the fixed one — it is not correct."""
    oc = (outcome or "").lower()
    for m in event.get("markets", []):
        outs = _loads(m.get("outcomes"))
        prs = _loads(m.get("outcomePrices"))
        for i, o in enumerate(outs):
            ol = str(o).lower()
            if ol and i < len(prs) and (oc in ol or ol in oc):
                try:
                    return float(prs[i])
                except (TypeError, ValueError):
                    pass
    return None


def _strict_price(event: dict, outcome: str, title: str) -> tuple[float | None, str | None]:
    """Market-aware match. Returns (cost, matched_question), or (None, None)
    when nothing in the event asserts what this trade asserts — including when
    two markets both do, since an ambiguous match is not a match."""
    bets = _bets_international(title, outcome)
    if not bets:
        return None, None

    hits: list[tuple[float, str]] = []
    for m in event.get("markets", []):
        prop = _prop_us(str(m.get("question") or ""))
        if prop is None:
            continue
        for want, affirm in bets:
            if _props_match(want, prop):
                price = _cost(m, affirm)
                if price is not None:
                    hits.append((price, str(m.get("question") or "")))
                break

    # De-dup: the same question reached via two equivalent phrasings is one hit.
    unique = {q: p for p, q in hits}
    if len(unique) != 1:
        return None, None
    question, price = next(iter(unique.items()))
    return price, question


async def us_quotes(
    client: httpx.AsyncClient, event_slug: str, outcome: str, title: str
) -> UsQuote:
    """One fetch, both matchers — so legacy and strict price the same instant."""
    event = await _find_event(client, event_slug, title)
    if not event:
        return UsQuote()
    strict, market = _strict_price(event, outcome, title)
    fee = None
    for m in event.get("markets", []):
        if str(m.get("question") or "") == market:
            fee = _num(m.get("feeCoefficient"))
            break
    return UsQuote(
        legacy=_legacy_price(event, outcome), strict=strict, market=market, fee_coefficient=fee
    )


async def us_price(client: httpx.AsyncClient, event_slug: str, outcome: str, title: str) -> float | None:
    """Back-compat shim: the original (legacy) price."""
    return (await us_quotes(client, event_slug, outcome, title)).legacy
