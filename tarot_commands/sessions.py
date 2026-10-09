"""Sessions de saisie en cours, indexees par l'id du message Discord de commande."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Optional


def _empty_game_players():
    return {'Preneur': [], 'Partenaire': [], 'Défenseurs': []}


def _empty_descendante_players():
    return {'#1': None, '#2': None, '#3': None, '#4': None, '#5': None}


@dataclass
class GameSession:
    request_message_id: int
    channel_id: Optional[int] = None
    author_id: Optional[int] = None
    confirm_message_id: Optional[int] = None
    view_generation: int = 0
    kind: str = 'partie'  # 'partie' | 'descendante'
    source: str = 'auto'  # 'auto' | 'game' | 'descendante'
    reparse: str = ''
    enchere: Optional[int] = None
    game_players: dict = field(default_factory=_empty_game_players)
    bouts: Optional[int] = None
    primes_attaque: list = field(default_factory=list)
    primes_defense: list = field(default_factory=list)
    points_attaque: Optional[int] = None
    descendante_players: dict = field(default_factory=_empty_descendante_players)
    descendante_points: list = field(default_factory=list)
    miseres: list = field(default_factory=list)

    def clear_parse_state(self):
        """Remet a zero les champs de partie / descendante (garde les ids meta)."""
        self.enchere = None
        self.game_players = _empty_game_players()
        self.bouts = None
        self.primes_attaque = []
        self.primes_defense = []
        self.points_attaque = None
        self.descendante_players = _empty_descendante_players()
        self.descendante_points = []
        self.miseres = []
        self.reparse = ''
        self.kind = 'partie'

    def copy_parse_from(self, other: 'GameSession'):
        self.kind = other.kind
        self.reparse = other.reparse
        self.enchere = other.enchere
        self.game_players = deepcopy(other.game_players)
        self.bouts = other.bouts
        self.primes_attaque = list(other.primes_attaque)
        self.primes_defense = list(other.primes_defense)
        self.points_attaque = other.points_attaque
        self.descendante_players = deepcopy(other.descendante_players)
        self.descendante_points = list(other.descendante_points)
        self.miseres = list(other.miseres)


pending: dict[int, GameSession] = {}


def create_session(
    request_message_id: int,
    *,
    channel_id: Optional[int] = None,
    author_id: Optional[int] = None,
    source: str = 'auto',
) -> GameSession:
    session = GameSession(
        request_message_id=request_message_id,
        channel_id=channel_id,
        author_id=author_id,
        source=source,
    )
    pending[request_message_id] = session
    return session


def get_session(request_message_id: Optional[int]) -> Optional[GameSession]:
    if request_message_id is None:
        return None
    return pending.get(request_message_id)


def pop_session(request_message_id: Optional[int]) -> Optional[GameSession]:
    if request_message_id is None:
        return None
    return pending.pop(request_message_id, None)


def clear_all_sessions():
    pending.clear()


def temp_session() -> GameSession:
    """Session non enregistree dans pending, pour parse d'essai (edits)."""
    return GameSession(request_message_id=0)


def semantic_from_session(session: GameSession) -> tuple:
    if session.kind == 'descendante' or (
        session.reparse.startswith('Descendante:\n')
    ):
        joueurs = [p for p in session.descendante_players.values() if p]
        return (
            'descendante',
            tuple(joueurs),
            tuple(session.descendante_points),
            tuple(session.miseres),
        )
    partenaire = session.game_players['Partenaire']
    return (
        'partie',
        tuple(session.game_players['Preneur']),
        partenaire[0] if partenaire else None,
        tuple(session.game_players['Défenseurs']),
        session.points_attaque,
        session.bouts,
        session.enchere,
        tuple(session.primes_attaque),
        tuple(session.primes_defense),
        tuple(session.miseres),
    )


def semantic_from_history(entry: dict[str, Any]) -> Optional[tuple]:
    entry_type = entry.get('type')
    if entry_type == 'descendante':
        return (
            'descendante',
            tuple(entry.get('joueurs') or []),
            tuple(entry.get('points') or []),
            tuple(entry.get('miseres') or []),
        )
    if entry_type == 'partie':
        return (
            'partie',
            (entry.get('preneur'),) if entry.get('preneur') else (),
            entry.get('partenaire'),
            tuple(entry.get('defenseurs') or []),
            entry.get('points_attaque'),
            entry.get('bouts'),
            entry.get('multiplicateur'),
            tuple(entry.get('primes_attaque') or []),
            tuple(entry.get('primes_defense') or []),
            tuple(entry.get('miseres') or []),
        )
    return None


def find_history_by_message_id(history: list, message_id: int) -> Optional[dict]:
    for entry in history:
        if entry.get('message_id') == message_id:
            return entry
    return None
