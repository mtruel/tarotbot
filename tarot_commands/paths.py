import os


def data_dir():
    """Retourne le dossier reel des fichiers d'etat du bot.

    En local, les JSON de la racine du depot sont des liens symboliques vers
    data/ ; dans le conteneur, ce sont de vrais fichiers dans /data (le
    repertoire de travail est le volume). On resout donc le chemin reel pour
    retomber sur le meme dossier dans les deux cas.
    """
    for name in ("players.json", "history.json", "config.json"):
        real = os.path.realpath(name)
        if os.path.isfile(real):
            return os.path.dirname(real)
    # Aucun fichier d'etat encore cree (clone neuf) : data/ si present, sinon cwd.
    return "data" if os.path.isdir("data") else "."
