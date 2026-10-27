"""Validation des saisies web avant d'appeler le calculateur historique."""

from tarot_commands.game import ENCHERE_NAMES, finalize_partie_scores
from tarot_commands.rules import PRIMES
from tarot_commands.sessions import GameSession
from tarot_commands.state import known_players


class InvalidGame(ValueError):
    pass


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise InvalidGame(f"{name} invalide.")
    return value


def _names(value, name, available):
    if not isinstance(value, list) or any(not isinstance(p, str) for p in value):
        raise InvalidGame(f"{name} invalide.")
    if len(value) > 5 or len(value) != len(set(value)) or any(p not in available for p in value):
        raise InvalidGame(f"{name} : joueur inconnu ou répété.")
    return value


def _primes(value, name):
    if (
        not isinstance(value, list)
        or len(value) > len(PRIMES)
        or any(not isinstance(p, str) for p in value)
        or len(value) != len(set(value))
    ):
        raise InvalidGame(f"{name} invalide.")
    if any(not isinstance(p, str) or p not in PRIMES for p in value):
        raise InvalidGame(f"{name} inconnue.")
    return value


def validate_game(data, players=None):
    """Construit une session depuis une liste blanche de champs, jamais depuis des scores client."""
    if not isinstance(data, dict):
        raise InvalidGame("Partie invalide.")
    available = set(known_players() if players is None else players)
    points = _integer(data.get("points_attaque"), "Points", 0, 91)
    bouts = _integer(data.get("bouts"), "Bouts", 0, 3)
    enchere = data.get("enchere")
    if isinstance(enchere, bool) or not isinstance(enchere, int) or enchere not in ENCHERE_NAMES:
        raise InvalidGame("Enchère invalide.")
    preneur = data.get("preneur")
    partenaire = data.get("partenaire")
    if not isinstance(preneur, str) or preneur not in available:
        raise InvalidGame("Preneur inconnu.")
    if partenaire is not None and (not isinstance(partenaire, str) or partenaire not in available):
        raise InvalidGame("Partenaire inconnu.")
    defenseurs = _names(data.get("defenseurs"), "Défenseurs", available)
    miseres = _names(data.get("miseres", []), "Misères", available)
    joueurs = [preneur, *([partenaire] if partenaire else []), *defenseurs]
    if len(joueurs) != len(set(joueurs)):
        raise InvalidGame("Un joueur ne peut occuper deux rôles.")
    if len(joueurs) not in (3, 4, 5) or len(defenseurs) < 2:
        raise InvalidGame("Le Tarot se joue à 3, 4 ou 5 avec au moins deux défenseurs.")
    if partenaire and len(joueurs) != 5:
        raise InvalidGame("Partenaire uniquement à 5 joueurs.")
    session = GameSession(request_message_id=0, source="web")
    session.points_attaque = points
    session.bouts = bouts
    session.enchere = enchere
    session.game_players = {
        "Preneur": [preneur],
        "Partenaire": [partenaire] if partenaire else [],
        "Défenseurs": defenseurs,
    }
    session.miseres = miseres
    session.primes_attaque = _primes(data.get("primes_attaque", []), "Prime attaque")
    session.primes_defense = _primes(data.get("primes_defense", []), "Prime défense")
    scores, error = finalize_partie_scores(session)
    if error:
        raise InvalidGame(error)
    return session, scores
