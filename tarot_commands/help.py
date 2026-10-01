import difflib

from discord.ext import commands


# usage, résumé d'une ligne, texte détaillé
COMMANDS = [
    (
        'help',
        't/help [commande]',
        'liste les commandes, ou le détail d’une commande',
        'Sans argument, envoie la liste.\n'
        'Avec un nom, envoie le détail : `t/help auto`.\n'
        'Le préfixe t/ est accepté : `t/help t/auto`.',
    ),
    (
        'ping',
        't/ping',
        'vérifie que le bot répond',
        'Répond pong!. Aucun argument.',
    ),
    (
        'add_player',
        't/add_player <nom>',
        'ajoute un joueur au classement',
        'Ajoute un joueur avec un score de 0.\n'
        'Le nom est un seul mot. S’il est déjà présent, rien n’est modifié.\n'
        'Exemple : `t/add_player Alice`',
    ),
    (
        'add_players',
        't/add_players <nom1> <nom2> ...',
        'ajoute plusieurs joueurs',
        'Ajoute plusieurs joueurs d’un coup, séparés par des espaces, score 0.\n'
        'Les noms déjà présents sont signalés et ignorés.\n'
        'Exemple : `t/add_players Alice Bob Carol`',
    ),
    (
        'leaderboard',
        't/leaderboard',
        'classement par total de points',
        'Affiche le classement du plus haut total au plus bas. Aucun argument.',
    ),
    (
        'leaderboard2',
        't/leaderboard2',
        'classement par points/partie, avec W/L et écart-type',
        'Affiche, pour chaque joueur, les points par partie, le nombre de '
        'parties gagnées et perdues (un score positif ou nul compte comme une '
        'victoire) et l’écart-type. Aucun argument.',
    ),
    (
        'game',
        't/game <points>',
        'saisie d’une partie via menus',
        'Démarre une partie classique. <points> est le total entier marqué par '
        'l’attaque, entre 0 et 91.\n'
        'Des menus demandent ensuite l’enchère, les bouts, les primes, les '
        'misères et les joueurs. 3, 4 ou 5 joueurs. Le partenaire n’est '
        'possible qu’à 5.\n'
        'Exemple : `t/game 45`',
    ),
    (
        'auto',
        't/auto <message>',
        'saisie d’une partie en texte libre',
        '```\n'
        't/auto  preneur  enchère     points  bouts  avec  appelé  vs  défense\n'
        't/auto  Alice    garde sans  50      1      avec  Carol   vs  Bob Dave Eve\n'
        '\n'
        't/auto  preneur  enchère  points  bouts  vs  défense         prime\n'
        't/auto  Alice    garde    45      2      vs  Bob Carol Dave  prime petit au bout\n'
        '\n'
        't/auto  preneur  enchère  points  bouts  vs  défense         prime attaque                                prime défense                misere  joueur\n'
        't/auto  Alice    garde    45      2      vs  Bob Carol Dave  prime attaque simple poignee chelem annoncé  prime defense petit au bout  misere  Bob\n'
        '\n'
        't/auto  descendante  joueur  score  joueur  score  joueur  score\n'
        't/auto  descendante  Alice   20     Bob     20     Carol   51\n'
        '```\n'
        '**Enchères :** petite, garde, garde sans, garde contre.\n'
        '**Primes :** simple poignee, double poignee, triple poignee, petit au bout, '
        'chelem annoncé, chelem non annoncé, chelem chuté.',
    ),
    (
        'descendante',
        't/descendante <p1> <p2> ...',
        'saisie d’une descendante',
        'Donne les points de chaque joueur. Des menus demandent ensuite les '
        'noms, dans le même ordre. 3, 4 ou 5 joueurs.\n'
        'Exemple : `t/descendante 20 20 51`',
    ),
    (
        'undo',
        't/undo IAMSURE',
        'annule la dernière partie',
        'Retire la dernière partie du classement et de l’historique.\n'
        'Sans IAMSURE, le bot demande confirmation et ne change rien.\n'
        'Irréversible sans accès aux fichiers sur le serveur.',
    ),
    (
        'new_season',
        't/new_season IAMSURE',
        'archive la saison et repart à zéro',
        'Déplace players.json, history.json et players_backup.json dans un '
        'dossier daté, puis repart sur des fichiers vides.\n'
        'Sans IAMSURE, le bot demande confirmation et ne change rien.\n'
        'Irréversible sans accès aux fichiers sur le serveur.',
    ),
    (
        'poignees',
        't/poignees [n]',
        'seuils de poignée pour n joueurs',
        'Affiche le nombre d’atouts et la prime de chaque poignée.\n'
        'n vaut 3, 4 ou 5. Sans argument, n vaut 5.\n'
        'Exemple : `t/poignees 4`',
    ),
    (
        'contrats',
        't/contrats',
        'points à atteindre selon le nombre de bouts',
        'Affiche le contrat (points à faire) pour 0, 1, 2 et 3 bouts. '
        'Aucun argument.',
    ),
    (
        'scores_descendante',
        't/scores_descendante <n>',
        'scores de descendante pour n joueurs',
        'Affiche les points gagnés ou perdus selon le rang. n vaut 3, 4 ou 5.\n'
        'Exemple : `t/scores_descendante 4`',
    ),
    (
        'curves',
        't/curves',
        'envoie le graphe de l’historique',
        'Dessine l’historique des scores et envoie l’image dans le salon. '
        'Aucun argument.',
    ),
]


def _lookup(name):
    key = name.lower().removeprefix('t/').strip()
    for command in COMMANDS:
        if command[0] == key:
            return command
    return None


def more_info(name):
    return f'`t/help {name}` for more info'


def error_message(name, text):
    return f'{text}\n{more_info(name)}'


def unknown_command_message(name):
    key = name.lower().removeprefix('t/').strip()
    shown = f't/{key}' if key else 't/'
    names = [command[0] for command in COMMANDS]
    matches = difflib.get_close_matches(key, names, n=1, cutoff=0.6)
    if matches:
        return (
            f'Commande inconnue : `{shown}`.\n'
            f'Tu voulais dire `t/{matches[0]}` ?\n'
            f'{more_info(matches[0])}'
        )
    return f'Commande inconnue : `{shown}`.\n`t/help` for more info'


def explain_command_error(ctx, error):
    """Message utile pour une erreur de saisie, ou None si c'est un bug interne."""
    if isinstance(error, commands.CommandNotFound):
        return unknown_command_message(ctx.invoked_with or '')

    name = ctx.command.name if ctx.command else 'help'

    if isinstance(error, commands.MissingRequiredArgument):
        return error_message(name, _missing_text(name))

    if isinstance(error, commands.TooManyArguments):
        return error_message(name, _too_many_text(name))

    if isinstance(error, commands.ArgumentParsingError):
        return error_message(
            name,
            'Un guillemet est mal fermé. Retire les guillemets, ou ferme-les.',
        )

    if isinstance(error, commands.BadArgument):
        return error_message(name, 'Argument invalide. Vérifie la forme de la commande.')

    return None


def _missing_text(name):
    texts = {
        'add_player': 'Il manque le nom. Un seul mot. Exemple : `t/add_player Alice`',
        'add_players': (
            'Il manque les noms, séparés par des espaces. '
            'Exemple : `t/add_players Alice Bob Carol`'
        ),
        'auto': (
            'Il manque la description de la partie. '
            'Exemple : `t/auto Alice garde 45 2 vs Bob Carol`'
        ),
        'scores_descendante': (
            'Il manque le nombre de joueurs (3, 4 ou 5). '
            'Exemple : `t/scores_descendante 4`'
        ),
    }
    if name in texts:
        return texts[name]
    command = _lookup(name)
    usage = command[1] if command else f't/{name}'
    return f'Il manque un argument. Usage : `{usage}`'


def _too_many_text(name):
    texts = {
        'add_player': (
            'Un seul nom, sans espace. Pour plusieurs joueurs : '
            '`t/add_players Alice Bob`'
        ),
        'game': (
            'Un seul nombre : les points entiers de l’attaque, de 0 à 91. '
            'Exemple : `t/game 45`'
        ),
        'help': 'Une seule commande à détailler. Exemple : `t/help auto`',
        'poignees': 'Un seul nombre de joueurs : 3, 4 ou 5. Exemple : `t/poignees 4`',
        'scores_descendante': (
            'Un seul nombre de joueurs : 3, 4 ou 5. Exemple : `t/scores_descendante 4`'
        ),
        'undo': 'Pour confirmer : `t/undo IAMSURE`',
        'new_season': 'Pour confirmer : `t/new_season IAMSURE`',
        'ping': '`t/ping` ne prend pas d’argument.',
        'leaderboard': '`t/leaderboard` ne prend pas d’argument.',
        'leaderboard2': '`t/leaderboard2` ne prend pas d’argument.',
        'contrats': '`t/contrats` ne prend pas d’argument.',
        'curves': '`t/curves` ne prend pas d’argument.',
    }
    if name in texts:
        return texts[name]
    command = _lookup(name)
    usage = command[1] if command else f't/{name}'
    return f'Trop d’arguments. Usage : `{usage}`'


@commands.command()
async def help(ctx, command_name=None):
    """Liste les commandes, ou le détail d’une commande : t/help auto."""
    if command_name is None:
        lines = [f'`{usage}` {short}' for _, usage, short, _ in COMMANDS]
        await ctx.send('**Liste des commandes**\n' + '\n'.join(lines))
        return

    command = _lookup(command_name)
    if command is None:
        await ctx.send(unknown_command_message(command_name))
        return

    _, usage, short, detail = command
    await ctx.send(f'`{usage}`\n_{short}_\n\n{detail}')
