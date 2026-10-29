"""Génère la fixture de la saison de debug (script de développement)."""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from tarot_commands.game import (
    descendante_details,
    finalize_descendante_scores,
    partie_details,
)
from tarot_commands.sessions import GameSession
from tarot_commands.web_game import validate_game

PLAYERS = [
    "Alice",
    "Bob",
    "Claire",
    "David",
    "Eve",
    "Farid",
    "Gaëlle",
    "Hugo",
    "Inès",
    "Jules",
    "Karim",
    "Leïla",
    "Léa",
    "Léo",
    "Lucie",
    "Lucas",
    "Maël",
    "Manon",
    "Mehdi",
    "Mia",
    "Noé",
    "Nora",
    "Olivier",
    "Pauline-Marguerite",
    "Quentin-Emmanuel",
    "Romain-Alexandre",
    "Sarah-Éléonore",
    "Théo-Maximilien",
    "Victor",
    "Yasmine",
]
ACTIVE_PLAYERS = PLAYERS[:8]
ENCHERES = [1, 2, 4, 6]
POIGNEES = ["Simple Poignée", "Double Poignée", "Triple Poignée"]
CHELEMS = ["Chelem annoncé", "Chelem non annoncé", "Chelem chuté"]
PETIT = "Petit au bout"
OUT = Path(__file__).parent / "fixtures"


def _primes(rng, *, defense=False):
    primes = []
    if rng.random() < 0.25:
        primes.append(rng.choice(POIGNEES))
    if rng.random() < 0.10:
        primes.append(rng.choice(CHELEMS[:2] if defense else CHELEMS))
    if rng.random() < 0.15:
        primes.append(PETIT)
    return primes


def _with_meta(details, when, scores):
    details.update(
        time=when.strftime("%d/%m/%Y, %H:%M:%S"),
        scores=scores,
        related_message_ids=[],
    )
    return details


def _game(rng, message_id, when):
    size = rng.choice([3, 4, 4, 5, 5])
    selected = rng.sample(ACTIVE_PLAYERS, size)
    preneur = selected[0]
    partenaire = selected[1] if size == 5 else None
    defenseurs = [p for p in selected if p not in (preneur, partenaire)]
    primes_attaque = _primes(rng)
    primes_defense = _primes(rng, defense=True)
    if PETIT in primes_attaque and PETIT in primes_defense:
        primes_defense.remove(PETIT)
    if any("Chelem" in p for p in primes_attaque) and any("Chelem" in p for p in primes_defense):
        primes_defense = [p for p in primes_defense if "Chelem" not in p]
    game = {
        "points_attaque": rng.randint(20, 75),
        "bouts": rng.randint(0, 3),
        "enchere": rng.choice(ENCHERES),
        "preneur": preneur,
        "partenaire": partenaire,
        "defenseurs": defenseurs,
        "miseres": rng.sample(selected, rng.choice([0, 0, 0, 0, 1])),
        "primes_attaque": primes_attaque,
        "primes_defense": primes_defense,
    }
    session, scores = validate_game(game, PLAYERS)
    session.request_message_id = message_id
    return _with_meta(partie_details(session), when, scores)


def _descendante(rng, message_id, when):
    size = rng.choice([3, 4, 5])
    selected = rng.sample(ACTIVE_PLAYERS, size)
    session = GameSession(request_message_id=message_id, source="debug")
    session.kind = "descendante"
    session.descendante_players = {f"#{index + 1}": name for index, name in enumerate(selected)}
    session.descendante_points = [rng.randint(0, 60) for _ in selected]
    session.miseres = rng.sample(selected, rng.choice([0, 0, 0, 1]))
    scores, error = finalize_descendante_scores(session)
    if error:
        raise RuntimeError(error)
    return _with_meta(descendante_details(session), when, scores)


def build():
    rng = random.Random(20260106)
    when = datetime(2026, 1, 6, 20, 30)
    history = []
    for index in range(36):
        message_id = 1_700_000_000_000_000_000 + index
        entry = (
            _descendante(rng, message_id, when) if index % 6 == 5 else _game(rng, message_id, when)
        )
        history.append(entry)
        when += timedelta(days=rng.randint(2, 6), hours=rng.randint(0, 2))
    return history


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "players.json").write_text(
        json.dumps(PLAYERS, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )
    (OUT / "history.json").write_text(
        json.dumps(build(), ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
