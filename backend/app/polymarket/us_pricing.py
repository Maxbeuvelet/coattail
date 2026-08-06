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

# Polymarket US publishes a symmetric, uncertainty-weighted fee:
#
#     fee = THETA * contracts * p * (1 - p)          (docs.polymarket.us/fees)
#
# with THETA = 0.06 for takers and -0.0125 for makers (a rebate). We cross the
# spread on every copy, so we are always the taker.
#
# Expressed against the dollars staked, an ENTRY costs:
#     contracts = stake / p        ->  fee = 0.06 * stake * (1 - p)
# i.e. 6% of stake at p=0.01, 3% at p=0.50, 0.6% at p=0.90. Fees are largest on
# coin-flips and smallest on near-certainties — the opposite of the flat 1% this
# module assumed before, which understated the cost roughly 3x at typical prices.
US_TAKER_THETA = 0.06

# Retained only so older callers keep working; the flat model is not used for
# new P&L. See us_fee() for the real one.
US_FEE_RATE = 0.01


def us_fee(stake_usd: float, entry_price: float, exit_price: float | None = None) -> float:
    """Round-trip taker fee in dollars for a position of `stake_usd` opened at
    `entry_price` and (optionally) closed at `exit_price`.

    Contracts are fixed at entry, so the exit leg is charged on the same
    contract count at the exit price. A position left to settle rather than
    traded out pays no exit fee — pass exit_price=None for that case.
    """
    if entry_price <= 0:
        return 0.0
    contracts = stake_usd / entry_price
    fee = US_TAKER_THETA * contracts * entry_price * (1.0 - entry_price)
    if exit_price is not None and 0.0 < exit_price < 1.0:
        fee += US_TAKER_THETA * contracts * exit_price * (1.0 - exit_price)
    return round(fee, 4)

# key = teamA-teamB-YYYY-MM-DD  (ignores the differing league prefix: chi vs csl)
_KEY_RE = re.compile(r"-([a-z0-9]+)-([a-z0-9]+)-(\d{4}-\d{2}-\d{2})")
_WORD_RE = re.compile(r"[A-Z][a-zA-Z]{2,}")
_STOP = {
    "Will", "Half", "Over", "Under", "Spread", "Handicap", "Exact", "Score",
    "Both", "Teams", "Map", "Winner", "Game", "Match", "The", "Yes", "Total",
}


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
    # Generic club prefixes/suffixes. These MUST be dropped, not merely demoted:
    # "CA Unión" and "CA Lanús" share "ca", and treating that as a real token
    # made both teams' markets match, which the ambiguity check then threw away.
    "fc", "sc", "cd", "cf", "afc", "ac", "as", "sk", "bk", "ss", "cs", "rc",
    "sv", "vfl", "vfb", "if", "ik", "ca", "ec", "se", "cr", "sd", "ud", "ua",
    "il", "gf", "ps", "kf", "fk", "nk", "hk", "ks", "mfk", "gks", "us", "tsv",
    "fsv", "bsc", "psv", "sv", "club", "atletico", "atlético", "deportivo",
    "the", "de", "of", "and",
}
# Tokens shared by many different clubs. A match resting only on these is not a
# match — "Real Salt Lake" and "Real Betis" are not the same team.
_GENERIC = {
    "real", "city", "united", "atletico", "athletic", "sporting", "deportivo",
    "nacional", "san", "santos", "racing", "union", "dynamo", "olympic",
    "national", "new", "york", "los", "st", "saint",
}


def _deaccent(s: str) -> str:
    """Strip diacritics. Team names arrive accented ('CA Unión', 'Lanús', 'Tromsø')
    while the search index and our own word regex are ASCII, so without this the
    term extractor finds nothing and the lookup silently never runs."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ø", "o").replace("Ø", "O").replace("ß", "ss").replace("æ", "ae").replace("Æ", "Ae")


def _tokens(s: str) -> frozenset[str]:
    s = _deaccent(s).lower()
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
    r"halftime|half[- ]time|\bhalf\b|\bperiod\b|\bquarter\b|\bset\s*\d"
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
    # Esports map winners: "CS: A vs BESTIA - Map 2 Winner", outcome = the team.
    # Checked before _kind, which would read the trailing "Winner" as a moneyline.
    mm = re.search(r"\bmap\s*(\d+)\b", title or "", re.I)
    if mm and re.search(r"winner|\bwin\b", title or "", re.I):
        team = _tokens(outcome)
        return [(("map", int(mm.group(1)), team), True)] if team else []

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
    if kind == "map":
        return a[1] == b[1] and _same_team(a[2], b[2])
    return False


# ── market metadata (preferred over parsing the question text) ──
# Every US market carries `sportsMarketType` and a `marketSides` array whose
# entries name the team the proposition is about. That is far more reliable than
# regexing the question, and it identifies markets the text parser can't — e.g.
# "Who will win …", where the question names no single side.
_DENY_TYPE = re.compile(
    r"_player_|inning|first_five|first_inning|extra_innings|first_half|second_half"
    r"|_quarter|_period|map_rounds|map_total",
    re.I,
)


def _kind_from_type(t: str) -> tuple[str, int | None] | str | None:
    """Market kind from `sportsMarketType`.

    Returns (kind, map_number) when supported, the string 'deny' when the type is
    a scope we deliberately don't price (player props, part-innings, halves,
    season futures), or None when the type is unknown — in which case the caller
    falls back to parsing the question text.
    """
    if not t:
        return None
    if t == "futures" or _DENY_TYPE.search(t):
        return "deny"
    m = re.match(r"^esports_map_winner_(\d+)$", t)
    if m:
        return ("map", int(m.group(1)))
    if "spread" in t or "handicap" in t:
        return ("spr", None)
    if "total" in t:
        return ("tot", None)
    if t.endswith("_winner"):
        return ("ml", None)
    return None


def _team_tokens(team: dict | None) -> frozenset[str]:
    """Tokens for a market's team, from its canonical name and safe name. The
    `alias` nickname is skipped — it never appears in international titles and
    would only add collision risk."""
    if not team:
        return frozenset()
    out: set[str] = set()
    for field in ("name", "safeName"):
        v = team.get(field)
        if v:
            out |= _tokens(str(v))
    return frozenset(out)


def _line_from_identifier(ident: str) -> float | None:
    """Totals encode their line in the side identifier, e.g. '…-f5-3pt5' → 3.5."""
    m = re.search(r"(\d+)pt(\d+)", ident or "", re.I)
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


def _market_offers(m: dict) -> list[tuple[tuple, bool]]:
    """Propositions this market can express, as (proposition, yes_side_gives_it).

    A market is one binary instrument, but a two-way market with a different team
    on each side expresses the mirror proposition too — backing the Yankees is
    buying No on "Cardinals win". Only emitted when the two sides genuinely name
    different teams, so a Yes/No market (where both sides carry the same team,
    and a draw is possible) never gets a bogus mirror.
    """
    kind = _kind_from_type(str(m.get("sportsMarketType") or ""))
    if kind == "deny" or kind is None:
        return []
    kind_name, map_no = kind

    sides = _loads(m.get("marketSides"))
    long_side = next((s for s in sides if s.get("long")), None)
    short_side = next((s for s in sides if not s.get("long")), None)
    if long_side is None:
        return []
    ident = str(long_side.get("identifier") or "")
    desc = str(long_side.get("description") or "")
    long_team = _team_tokens(long_side.get("team"))
    short_team = _team_tokens((short_side or {}).get("team"))

    if kind_name == "ml":
        # Soccer's draw leg shares the winner type; the identifier marks it.
        if ident.endswith("-draw") or not long_team:
            return [(("draw",), True)] if ident.endswith("-draw") else []
        offers = [(("ml", long_team), True)]
        if short_team and not _same_team(short_team, long_team):
            offers.append((("ml", short_team), False))
        return offers

    if kind_name == "map":
        return [(("map", map_no, long_team), True)] if long_team else []

    if kind_name == "spr":
        line = _num(desc)
        if line is None or not long_team:
            return []
        offers = [(("spr", long_team, line), True)]
        if short_team and not _same_team(short_team, long_team):
            offers.append((("spr", short_team, -line), False))
        return offers

    if kind_name == "tot":
        line = _line_from_identifier(ident)
        if line is None:
            line = _num(re.sub(r".*?(more than|over|under|total)", "", str(m.get("question") or ""), flags=re.I))
        if line is None:
            return []
        side = "over" if desc.strip().lower().startswith("o") else (
            "under" if desc.strip().lower().startswith("u") else None
        )
        if side is None:
            return []
        other = "under" if side == "over" else "over"
        return [(("tot", line, side), True), (("tot", line, other), False)]

    return []


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
    # Everything needed to actually place this trade on Polymarket US. `slug`
    # identifies the market to the orders API; `buy_yes` says which side of it
    # to take. Populated only when `strict` matched — we never trade a market we
    # could not confidently identify.
    slug: str | None = None
    buy_yes: bool | None = None


async def _find_event(client: httpx.AsyncClient, event_slug: str, title: str) -> dict | None:
    k = _key(event_slug)
    if not k:
        return None
    # De-accent first: the index is ASCII and so is _WORD_RE, so 'CA Unión vs
    # CA Lanús' would otherwise yield no terms at all and never be looked up.
    seen: set[str] = set()
    terms = [
        w for w in _WORD_RE.findall(_deaccent(title))
        if w not in _STOP and w.lower() not in _CLUB_NOISE and not (w in seen or seen.add(w))
    ]
    for term in terms[:3]:
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


def _strict_match(event: dict, outcome: str, title: str) -> dict | None:
    """Market-aware match. Returns {price, question, slug, buy_yes} — everything
    needed to price the trade AND to place it — or None when nothing in the
    event asserts what this trade asserts, including when two markets both do,
    since an ambiguous match is not a match."""
    bets = _bets_international(title, outcome)
    if not bets:
        return None

    hits: dict[str, dict] = {}
    for m in event.get("markets", []):
        question = str(m.get("question") or "")
        # Prefer the market's own metadata; fall back to the question text only
        # when `sportsMarketType` is absent or unrecognised (never when it names
        # a scope we deliberately refuse).
        offers = _market_offers(m)
        if not offers:
            if _kind_from_type(str(m.get("sportsMarketType") or "")) == "deny":
                continue
            prop = _prop_us(question)
            offers = [(prop, True)] if prop is not None else []

        for prop, yes_gives in offers:
            # `want_true` is None when nothing matches — distinct from False,
            # which means "we want this proposition to be false".
            want_true = next((a for want, a in bets if _props_match(want, prop)), None)
            if want_true is None:
                continue
            # Buying Yes yields `prop` == yes_gives; we want `prop` == want_true.
            buy_yes = want_true == yes_gives
            price = _cost(m, buy_yes)
            if price is not None:
                hits[question] = {
                    "price": price,
                    "question": question,
                    "slug": str(m.get("slug") or "") or None,
                    "buy_yes": buy_yes,
                }
            break  # one proposition per market

    if len(hits) != 1:
        return None
    return next(iter(hits.values()))


def _strict_price(event: dict, outcome: str, title: str) -> tuple[float | None, str | None]:
    """Back-compat wrapper used by the shadow book and tests."""
    hit = _strict_match(event, outcome, title)
    return (hit["price"], hit["question"]) if hit else (None, None)


async def us_quotes(
    client: httpx.AsyncClient, event_slug: str, outcome: str, title: str
) -> UsQuote:
    """One fetch, both matchers — so legacy and strict price the same instant."""
    event = await _find_event(client, event_slug, title)
    if not event:
        return UsQuote()
    hit = _strict_match(event, outcome, title)
    fee = None
    if hit:
        for m in event.get("markets", []):
            if str(m.get("question") or "") == hit["question"]:
                fee = _num(m.get("feeCoefficient"))
                break
    return UsQuote(
        legacy=_legacy_price(event, outcome),
        strict=hit["price"] if hit else None,
        market=hit["question"] if hit else None,
        slug=hit["slug"] if hit else None,
        buy_yes=hit["buy_yes"] if hit else None,
        fee_coefficient=fee,
    )


async def us_price(client: httpx.AsyncClient, event_slug: str, outcome: str, title: str) -> float | None:
    """Back-compat shim: the original (legacy) price."""
    return (await us_quotes(client, event_slug, outcome, title)).legacy
