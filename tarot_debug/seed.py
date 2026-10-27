"""Seed et reset des données factices de l'environnement de debug."""

import shutil
from pathlib import Path

from tarot_debug.guardrails import MARKER, STATE_FILES, refuse_prod_data

FIXTURES = Path(__file__).parent / "fixtures"


def seed_data_dir(data_dir=".", *, reset=False):
    """Copie la fixture dans ``data_dir`` et pose le marqueur ``.debug``.

    Sans ``reset``, un dossier déjà seedé est laissé intact. Un dossier qui
    contient des données sans marqueur est refusé : c'est probablement la prod.
    """
    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    marker = data / MARKER
    if marker.exists() and not reset:
        return data
    refuse_prod_data(data)
    for name in STATE_FILES:
        shutil.copyfile(FIXTURES / name, data / name)
    marker.write_text("debug\n", encoding="utf-8")
    return data
