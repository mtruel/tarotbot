"""Vues pures de l'historique (sans Discord, sans IO), partagees par t/delete et t/history.

Contient le recapitulatif detaille d'une partie, le format une-ligne, le parsing
des arguments de t/history, la selection et le rendu tronque en bloc de code.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from unidecode import unidecode

from tarot_commands.state import player_index, resolve_player

HISTORY_TIME = "%d/%m/%Y, %H:%M:%S"
DEFAULT_HISTORY_COUNT = 10
MAX_HISTORY_COUNT = 50
TAIL_LINES = 4
CODE_FENCE = "```"

PRIME_ABBREV = {
    "Simple Poignée": "SP",
    "Double Poignée": "DP",
    "Triple Poignée": "TP",
    "Petit au bout": "PAB",
    "Chelem annoncé": "CA",
    "Chelem non annoncé": "CNA",
    "Chelem chuté": "CC",
}
_PRIME_ABBREV_NORM = {unidecode(name).casefold(): ab for name, ab in PRIME_ABBREV.items()}

_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$")
_RANGE_RE = re.compile(r"^(\d+)-(\d+)$")


def is_snowflake_token(token: str) -> bool:
    """Vrai si le token ressemble a un id de message Discord."""
    return token.isdigit() and 17 <= len(token) <= 20


# ---------------------------------------------------------------------------
# Recapitulatif detaille (t/delete, t/history <id>)
# ---------------------------------------------------------------------------


def _join_names(names):
    names = [n for n in (names or []) if n]
    if not names:
        return "—"
    return ", ".join(names)


def format_entry_summary(entry: dict) -> str:
    """Recapitulatif lisible d'une entree history (partie ou descendante)."""
    entry_type = entry.get("type", "partie")
    lines = []

    if entry_type == "descendante":
        joueurs = entry.get("joueurs") or []
        points = entry.get("points") or []
        pairs = []
        for i, name in enumerate(joueurs):
            pts = points[i] if i < len(points) else "?"
            pairs.append(f"{name} {pts}")
        lines.append("Descendante : " + (", ".join(pairs) if pairs else "—"))
    else:
        preneur = entry.get("preneur") or "?"
        enchere = entry.get("enchere") or "?"
        pts = entry.get("points_attaque")
        pts_txt = f"{pts}pts" if pts is not None else "?pts"
        bouts = entry.get("bouts")
        bouts_txt = (
            f"{bouts} bout" + ("" if bouts == 1 else "s") if bouts is not None else "? bouts"
        )
        partenaire = entry.get("partenaire")
        avec = f" avec {partenaire}" if partenaire else ""
        lines.append(f"{preneur} {enchere} {pts_txt} {bouts_txt}{avec}")
        lines.append(f"contre {_join_names(entry.get('defenseurs'))}")

        primes_a = entry.get("primes_attaque") or []
        primes_d = entry.get("primes_defense") or []
        primes_bits = []
        if primes_a:
            primes_bits.append("attaque : " + ", ".join(primes_a))
        if primes_d:
            primes_bits.append("défense : " + ", ".join(primes_d))
        if primes_bits:
            lines.append("poignées / primes : " + " · ".join(primes_bits))

    miseres = entry.get("miseres") or []
    if miseres:
        lines.append("misères : " + ", ".join(miseres))

    scores = entry.get("scores") or {}
    if scores:
        score_bits = [
            f"{name} {int(val) if val == int(val) else val}" for name, val in scores.items()
        ]
        lines.append("scores : " + ", ".join(score_bits))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Format une-ligne et sous-totaux (t/history)
# ---------------------------------------------------------------------------


def parse_entry_time(entry):
    """datetime naif de l'entree, ou None si le champ time est absent/illisible."""
    raw = entry.get("time")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, HISTORY_TIME)
    except (TypeError, ValueError):
        return None


def _abbreviate_prime(name):
    return _PRIME_ABBREV_NORM.get(unidecode(name).casefold(), name)


def _fmt_number(value):
    return int(value) if value == int(value) else value


def _fmt_signed(value):
    return f"{'+' if value >= 0 else ''}{_fmt_number(value)}"


def _primes_text(entry):
    """Primes attaque abregees, puis primes defense prefixees par `def:`."""
    bits = [_abbreviate_prime(p) for p in entry.get("primes_attaque") or []]
    bits += [f"def:{_abbreviate_prime(p)}" for p in entry.get("primes_defense") or []]
    return " ".join(bits)


def format_history_line(entry) -> str:
    """Une partie sur une seule ligne (monospace friendly)."""
    when = parse_entry_time(entry)
    stamp = when.strftime("%d/%m %H:%M") if when else "??"

    if entry.get("type") == "descendante":
        joueurs = entry.get("joueurs") or []
        points = entry.get("points") or []
        pairs = [
            f"{name} {points[i] if i < len(points) else '?'}" for i, name in enumerate(joueurs)
        ]
        contract = "Descendante  " + ", ".join(pairs)
    else:
        preneur, enchere = entry.get("preneur"), entry.get("enchere")
        if preneur or enchere:
            parts = [str(preneur or "?"), str(enchere or "?")]
        else:
            # Partie reconstruite (rebuild_history) : contrat inconnu.
            parts = ["(contrat inconnu)"]
        points_attaque = entry.get("points_attaque")
        if points_attaque is not None:
            parts.append(f"{_fmt_number(points_attaque)}pts")
        bouts = entry.get("bouts")
        if bouts is not None:
            parts.append(f"{bouts}b")
        if entry.get("partenaire"):
            parts.append(f"+{entry['partenaire']}")
        primes = _primes_text(entry)
        if primes:
            parts.append(primes)
        contract = " ".join(parts)

    scores = entry.get("scores") or {}
    scores_txt = " ".join(f"{name}{_fmt_signed(val)}" for name, val in scores.items())

    message_id = entry.get("message_id")
    id_txt = f"`{message_id}`" if message_id else "`-`"

    return f"{stamp}  {contract}  {scores_txt}  {id_txt}"


def win_loss(entries, player):
    """(victoires, defaites) pour un joueur, un score nul ou positif = victoire."""
    wins = losses = 0
    for entry in entries:
        scores = entry.get("scores") or {}
        if player not in scores:
            continue
        if scores[player] >= 0:
            wins += 1
        else:
            losses += 1
    return wins, losses


def player_subtotal(entries, player) -> str:
    """Ligne de synthese d'un joueur sur les parties selectionnees."""
    total = 0
    played = 0
    for entry in entries:
        scores = entry.get("scores") or {}
        if player in scores:
            total += scores[player]
            played += 1
    wins, losses = win_loss(entries, player)
    return f"Total {player} : {_fmt_signed(total)} pts · {played} parties · {wins}V / {losses}L"


# ---------------------------------------------------------------------------
# Parsing des arguments de t/history
# ---------------------------------------------------------------------------


@dataclass
class HistoryQuery:
    """Description d'une requete t/history, deja resolue (joueur canonique)."""

    mode: str  # 'count' | 'range' | 'window' | 'date_span' | 'detail'
    n: int | None = None
    start: int | None = None
    end: int | None = None
    since: datetime | None = None
    until: datetime | None = None
    label: str = ""
    player: str | None = None
    detail_id: int | None = None
    note: str = ""


def _unknown_player_message(token, players):
    matches = difflib.get_close_matches(token, players, n=1, cutoff=0.6)
    if matches:
        return f"Joueur inconnu : « {token} ». Tu voulais dire {matches[0]} ?"
    return f"Joueur inconnu : « {token} »."


def _extract_player(tokens, players):
    """Retire `player <nom>` des tokens et retourne le nom canonique (ou None).

    Le nom peut contenir des espaces : la plus longue suite de tokens qui
    correspond a un joueur connu l'emporte.
    """
    lowered = [tok.casefold() for tok in tokens]
    if "player" not in lowered:
        return None
    index = lowered.index("player")
    if index + 1 >= len(tokens):
        raise ValueError("Indique un joueur. Exemple : `t/history player Mathias`.")

    names = player_index(players)
    for stop in range(len(tokens), index + 1, -1):
        candidate = " ".join(tokens[index + 1 : stop])
        resolved = resolve_player(candidate, players, names)
        if resolved is not None:
            del tokens[index:stop]
            return resolved
    raise ValueError(_unknown_player_message(tokens[index + 1], players))


def _parse_date(token, today: date):
    """date d'un token dd/mm ou dd/mm/yyyy, sinon None.

    Sans annee : annee courante, ou l'annee precedente si la date serait future.
    """
    match = _DATE_RE.match(token)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        if year:
            return date(int(year), int(month), int(day))
        parsed = date(today.year, int(month), int(day))
        if parsed > today:
            parsed = date(today.year - 1, int(month), int(day))
        return parsed
    except ValueError:
        raise ValueError(f"Date invalide : « {token} ».") from None


def _start_of(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time())


def _end_of(day: date) -> datetime:
    return datetime.combine(day, datetime.max.time())


def _window(phrase, now: datetime):
    """(since, until, label) d'une fenetre nommee, ou None si inconnue.

    `today` / `this week` / `this month` : periode en cours jusqu'a maintenant.
    `yesterday` / `last week` / `last month` : periode calendaire precedente complete.
    """
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    first_of_month = today.replace(day=1)

    if phrase == "today":
        return _start_of(today), _end_of(today), "aujourd'hui"
    if phrase == "yesterday":
        day = today - timedelta(days=1)
        return _start_of(day), _end_of(day), f"hier ({day.strftime('%d/%m')})"
    if phrase == "this week":
        return _start_of(monday), _end_of(today), f"cette semaine (depuis le {monday:%d/%m})"
    if phrase == "last week":
        start = monday - timedelta(days=7)
        end = monday - timedelta(days=1)
        return (
            _start_of(start),
            _end_of(end),
            f"la semaine dernière (du {start:%d/%m} au {end:%d/%m})",
        )
    if phrase == "this month":
        return _start_of(first_of_month), _end_of(today), f"ce mois-ci ({today:%m/%Y})"
    if phrase == "last month":
        end = first_of_month - timedelta(days=1)
        start = end.replace(day=1)
        return _start_of(start), _end_of(end), f"le mois dernier ({start:%m/%Y})"
    return None


def parse_history_args(value, players, now=None) -> HistoryQuery:
    """Separe la clause `player`, le detail par id et le selecteur. Leve ValueError sinon."""
    now = now or datetime.now()
    today = now.date()
    tokens = (value or "").split()
    player = _extract_player(tokens, players)

    window = _window(" ".join(tok.casefold() for tok in tokens), now)
    if window is not None:
        since, until, label = window
        return HistoryQuery(mode="window", since=since, until=until, label=label, player=player)

    if len(tokens) == 1 and is_snowflake_token(tokens[0]):
        if player is not None:
            raise ValueError("Le détail par id ne se combine pas avec `player`.")
        return HistoryQuery(mode="detail", detail_id=int(tokens[0]))

    if not tokens:
        return HistoryQuery(mode="count", n=DEFAULT_HISTORY_COUNT, player=player)

    if len(tokens) == 1:
        token = tokens[0]

        range_match = _RANGE_RE.match(token)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start < 1 or end < 1 or start > end:
                raise ValueError("Tranche invalide. Exemple : `t/history 25-50`.")
            note = ""
            if end - start + 1 > MAX_HISTORY_COUNT:
                end = start + MAX_HISTORY_COUNT - 1
                note = f"limité à {MAX_HISTORY_COUNT}"
            return HistoryQuery(mode="range", start=start, end=end, player=player, note=note)

        day = _parse_date(token, today)
        if day is not None:
            return HistoryQuery(
                mode="date_span",
                since=_start_of(day),
                until=_end_of(day),
                label=f"le {day:%d/%m/%Y}",
                player=player,
            )

        if token.isdigit():
            count = int(token)
            if count < 1:
                raise ValueError("Le nombre doit être au moins 1. Exemple : `t/history 10`.")
            note = f"limité à {MAX_HISTORY_COUNT}" if count > MAX_HISTORY_COUNT else ""
            return HistoryQuery(
                mode="count", n=min(count, MAX_HISTORY_COUNT), player=player, note=note
            )

        raise ValueError(
            "Argument inconnu. Exemples : `t/history 10`, `t/history today`, "
            "`t/history this week`, `t/history player Mathias`."
        )

    if len(tokens) == 2:
        first = _parse_date(tokens[0], today)
        second = _parse_date(tokens[1], today)
        if first is not None and second is not None:
            if first > second:
                raise ValueError("La première date doit précéder la seconde.")
            return HistoryQuery(
                mode="date_span",
                since=_start_of(first),
                until=_end_of(second),
                label=f"du {first:%d/%m/%Y} au {second:%d/%m/%Y}",
                player=player,
            )

    raise ValueError("Trop d'arguments. Exemple : `t/history 10 player Mathias`.")


# ---------------------------------------------------------------------------
# Selection et rendu
# ---------------------------------------------------------------------------


def _sorted_recent(entries):
    """Plus recentes d'abord ; une entree sans time exploitable termine en queue."""

    def key(entry):
        return parse_entry_time(entry) or datetime.min

    return sorted(entries, key=key, reverse=True)


def select_history(query, history):
    """Applique filtre joueur puis selecteur, trie, retourne (entrees, en-tete)."""
    entries = list(history)
    if query.player:
        entries = [e for e in entries if query.player in (e.get("scores") or {})]
    entries = _sorted_recent(entries)

    base = "**Historique**"
    if query.player:
        base = f"{base} - {query.player}"
    note = f" ({query.note})" if query.note else ""

    if query.mode == "count":
        selected = entries[: query.n]
        shown = len(selected) or query.n
        return selected, f"{base} - {shown} dernières parties{note}"

    if query.mode == "range":
        total = len(entries)
        start, end = query.start or 1, query.end or 1
        shown_end = end if start > total else min(end, total)
        header = f"{base} - parties {start} à {shown_end} (sur {total}){note}"
        return entries[start - 1 : end], header

    since, until = query.since, query.until
    selected = [
        entry
        for entry in entries
        if (when := parse_entry_time(entry)) is not None
        and since is not None
        and until is not None
        and since <= when <= until
    ]
    return selected, f"{base} - {query.label}"


def empty_message(query) -> str:
    """Message affiche quand la selection est vide."""
    who = f" de {query.player}" if query.player else ""
    if query.mode == "count":
        return f"Aucune partie{who}."
    if query.mode == "range":
        return f"Aucune partie{who} pour cette tranche."
    return f"Aucune partie{who} sur cette période."


def clip_line(line, width):
    if len(line) <= width:
        return line
    return line[: max(0, width - 1)] + "…"


def _code_block(lines):
    return f"{CODE_FENCE}\n" + "\n".join(lines) + f"\n{CODE_FENCE}"


def render_history(entries, max_len=2000):
    """Bloc code des lignes, tronque par une ligne `...` si trop long.

    Garantit `len(texte) <= max_len` (sauf max_len absurde < cadre du bloc).

    Returns
    -------
    tuple[str, int]
        (texte du bloc, nombre de parties masquees ; 0 si rien n'est masque)
    """
    lines = [format_history_line(entry) for entry in entries]
    full = _code_block(lines)
    if len(full) <= max_len:
        return full, 0

    budget = max_len - len(_code_block([]))  # caracteres du corps, sauts de ligne inclus
    if budget <= len("..."):
        return _code_block(["..."]), len(lines)

    # Une ligne pathologique (noms enormes) ne doit pas faire sauter la limite.
    width = max(8, budget // (TAIL_LINES + 2))
    lines = [clip_line(line, width) for line in lines]
    if len(lines) == 1:
        return _code_block([clip_line(lines[0], budget)]), 0

    tail_count = min(TAIL_LINES, len(lines) - 1)
    while True:
        tail = lines[len(lines) - tail_count :] if tail_count else []
        used = sum(len(line) + 1 for line in tail) + len("...")
        if used <= budget or tail_count == 0:
            break
        tail_count -= 1

    head = []
    for line in lines[: len(lines) - tail_count]:
        if used + len(line) + 1 > budget:
            break
        head.append(line)
        used += len(line) + 1

    hidden = len(lines) - len(head) - len(tail)
    if hidden == 0:
        return _code_block([*head, *tail]), 0
    return _code_block([*head, "...", *tail]), hidden
