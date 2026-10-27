"""Garde-fous de l'environnement de debug."""

import os
from pathlib import Path

MARKER = ".debug"
STATE_FILES = ("players.json", "history.json")


class DebugGuardError(RuntimeError):
    pass


def refuse_prod_data(data_dir):
    """Refuse un dossier qui contient des données sans le marqueur debug."""
    data = Path(data_dir)
    if (data / MARKER).exists():
        return
    if any((data / name).exists() for name in STATE_FILES):
        raise DebugGuardError(
            f"{data} contient des données sans marqueur {MARKER} : "
            "aucune donnée existante n'a été modifiée."
        )


def check(data_dir=".", *, environ=None):
    """Refuse de démarrer le debug avec un token réel ou des données de prod."""
    env = os.environ if environ is None else environ
    if env.get("TAROT_DEBUG") != "1":
        raise DebugGuardError("TAROT_DEBUG=1 est requis pour l'environnement de debug.")
    if env.get("DISCORD_TOKEN"):
        raise DebugGuardError(
            "DISCORD_TOKEN est défini : refus de démarrer l'environnement de debug."
        )
    refuse_prod_data(data_dir)
