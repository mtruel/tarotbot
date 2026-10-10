from discord.ext import commands
from table2ascii import table2ascii as t2a

from tarot_commands.help import error_message

POIGNEES = {
    3: {"Simple: 13 Atouts": 20, "Double: 15 Atouts": 30, "Triple: 18 Atouts": 40},
    4: {"Simple: 10 Atouts": 20, "Double: 13 Atouts": 30, "Triple: 15 Atouts": 40},
    5: {"Simple: 8 Atouts": 20, "Double: 10 Atouts": 30, "Triple: 13 Atouts": 40},
}
CONTRAT_PAR_BOUT = [56, 51, 41, 36]
PRIMES = {
    "Simple Poignée": 20,
    "Double Poignée": 30,
    "Triple Poignée": 40,
    "Petit au bout": 10,
    "Chelem annoncé": 400,
    "Chelem non annoncé": 200,
    "Chelem chuté": -200,
}

# Limite Discord : 2000 caractères par message.
DISCORD_MAX_LEN = 2000

SOURCE = "Règlement officiel FFT, version du 1er juillet 2012."

RESUME = (
    "**Règlement officiel du Tarot (FFT) — résumé**\n\n"
    "**Cartes** : 78 cartes = 4 couleurs de 14 (Roi, Dame, Cavalier, Valet, puis 10 à As) "
    "+ 21 Atouts + l'Excuse.\n"
    "Les **3 Bouts** (Oudlers) : le 21, le Petit (1) et l'Excuse.\n\n"
    "**Valeurs** : Bout ou Roi 4,5 · Dame 3,5 · Cavalier 2,5 · Valet 1,5 · autre 0,5 "
    "→ **91 points**\n\n"
    "**Contrat** selon les Bouts du preneur : 0 → 56 · 1 → 51 · 2 → 41 · 3 → 36\n\n"
    "**Enchères** (coefficient) : Petite x1 · Garde x2 · Garde Sans x4 · Garde Contre x6.\n"
    "Tout contrat vaut 25 points : on ajoute 25 aux points de gain ou de perte, puis on "
    "multiplie.\n\n"
    "**Primes** : poignée 20/30/40 · Petit au bout 10 · chelem 400 (annoncé), "
    "200 (non annoncé), −200 (annoncé chuté).\n\n"
    "`t/rules full` : règlement détaillé · `t/rules contrats` · `t/rules poignees` · "
    "`t/rules descendante`\n"
    f"_{SOURCE}_"
)

# Règlement 4 joueurs découpé en blocs <= DISCORD_MAX_LEN, envoyés à la suite.
FULL_RULES = [
    (
        f"**Règlement officiel du Tarot (FFT)** — détail\n_{SOURCE}_\n\n"
        "**Cartes**\n"
        "Le Tarot se joue avec 78 cartes : 4 couleurs (Pique, Cœur, Carreau, Trèfle) de 14 "
        "cartes, 21 Atouts et l'Excuse.\n"
        "Dans chaque couleur, ordre décroissant de force : Roi, Dame, Cavalier, Valet (les "
        "Honneurs), puis 10, 9, 8, 7, 6, 5, 4, 3, 2, As.\n"
        "Les Atouts ont priorité sur les couleurs ; le 21 est le plus fort, le 1 (le Petit) "
        "le plus faible.\n"
        "L'Excuse est un joker : elle dispense de fournir la couleur ou l'Atout demandé.\n"
        "Le 21, le Petit et l'Excuse sont les 3 Bouts (ou Oudlers).\n\n"
        "Valeurs : Bout ou Roi 4,5 · Dame 3,5 · Cavalier 2,5 · Valet 1,5 · toute autre "
        "carte 0,5.\n"
        "Au décompte on compte deux par deux : Bout ou Roi + petite carte = 5, Dame + "
        "petite = 4, Cavalier + petite = 3, Valet + petite = 2, deux petites = 1.\n"
        "Total : 91 points."
    ),
    (
        "**Distribution**\n"
        "Avant la première donne, chacun tire une carte : la plus petite désigne le donneur "
        "(Pique < Cœur < Carreau < Trèfle ; l'Excuse ne compte pas).\n"
        "Le joueur en face du donneur bat les cartes ; le voisin de gauche coupe en laissant "
        "plus de 3 cartes.\n"
        "Le donneur distribue 3 par 3, dans le sens contraire des aiguilles d'une montre, et "
        "constitue le Chien : 6 cartes, sans prendre la première ni la dernière du paquet. "
        "Chaque joueur reçoit 18 cartes.\n"
        "Un joueur possédant le Petit sec (seul Atout, sans l'Excuse) doit l'annoncer et "
        "étaler son jeu : la donne est annulée avant les enchères."
    ),
    (
        "**Enchères**\n"
        "Le joueur à droite du donneur parle le premier ; chacun ne parle qu'une fois. Par "
        "ordre croissant :\n"
        "- Petite (Prise) : main moyenne ;\n"
        "- Garde : x2 ;\n"
        "- Garde Sans le Chien : x4, sans regarder le Chien ;\n"
        "- Garde Contre le Chien : x6, le Chien va à la Défense.\n"
        "Si les quatre joueurs passent, une nouvelle donne est distribuée.\n"
        "Sur un surcontrat (Garde Sans ou Garde Contre), on appelle l'arbitre."
    ),
    (
        "**Chien et Écart**\n"
        "Sur Petite ou Garde, le donneur tend le Chien au preneur, qui retourne ses 6 "
        "cartes, les incorpore à son jeu puis écarte 6 cartes (l'Écart), secrètes jusqu'à la "
        "fin.\n"
        "On ne peut écarter ni Roi ni Bout ; on n'écarte un Atout que si c'est "
        "indispensable, et on le montre à la Défense.\n"
        "Quand le preneur a dit « Jeu », l'Écart ne peut plus être consulté ni modifié (il "
        "reste rectifiable s'il ne fait pas 6 cartes, tant qu'aucune carte n'a été jouée).\n"
        "Sur Garde Sans, le Chien reste caché devant le preneur et compte avec ses levées. "
        "Sur Garde Contre, il va au défenseur face au preneur et compte avec la Défense.\n\n"
        "**Chelem**\n"
        "Le chelem est annoncé après le contrat ; on appelle l'arbitre. Réussi il rapporte "
        "400 points, non annoncé mais réussi 200 points, annoncé mais chuté 200 points de "
        "pénalité.\n"
        "Après une annonce, l'entame revient au demandeur."
    ),
    (
        "**Poignée**\n"
        "Une Poignée s'annonce et se présente, Atouts classés, juste avant de jouer sa "
        "première carte.\n"
        "Seuils : à 4 joueurs 10/13/15 Atouts, à 3 joueurs 13/15/18, à 5 joueurs 8/10/13.\n"
        "Primes : simple 20, double 30, triple 40 ; elles ne dépendent pas du contrat et "
        "vont au camp vainqueur de la donne.\n\n"
        "**Petit au bout**\n"
        "Si le Petit fait partie de la dernière levée, le camp qui la réalise touche une "
        "prime de 10 points, multipliée par le coefficient du contrat, quel que soit le "
        "résultat de la donne."
    ),
    (
        "**Jeu de la carte**\n"
        "L'entame est faite par le joueur à droite du donneur, puis chacun joue dans le sens "
        "contraire des aiguilles d'une montre.\n"
        "- À l'Atout : obligé de monter sur l'Atout le plus fort déjà en jeu ; sinon on "
        "« pisse » (un petit Atout).\n"
        "- À la couleur : on fournit la couleur demandée, sans obligation de monter.\n"
        "- Sans la couleur : on coupe (Atout) ; si le précédent a coupé, on surcoupe ou on "
        "« pisse ».\n"
        "- Sans couleur ni Atout : on défausse.\n"
        "L'Excuse ne permet pas de réaliser une levée (sauf au chelem) et reste la propriété "
        "de son camp."
    ),
    (
        "**Calcul des scores**\n"
        "Le preneur doit atteindre, selon ses Bouts : 56 (0 bout), 51 (1), 41 (2) ou 36 (3) "
        "points.\n"
        "S'il fait exactement le contrat, il est « juste fait » ; au-dessus ce sont des "
        "points de gain, en dessous des points de perte.\n"
        "Tout contrat vaut 25 points : on ajoute 25 aux points de gain ou de perte, puis on "
        "multiplie par le coefficient : Petite x1, Garde x2, Garde Sans x4, Garde Contre "
        "x6.\n"
        "On ajoute enfin les primes (poignée, Petit au bout, chelem).\n"
        "À 4 joueurs, chaque défenseur marque ce total (positif si le preneur chute) et le "
        "preneur le triple."
    ),
    (
        "**Le jeu à 3 joueurs**\n"
        "Même règle qu'à 4, mêmes contrats. Les cartes sont distribuées 4 par 4 (le Chien "
        "reste à 6 cartes), chaque joueur recevant 24 cartes.\n"
        "Poignées : simple 13 Atouts, double 15, triple 18.\n"
        "On compte au demi-point près : le demi-point va au camp gagnant. Les points du "
        "preneur sont multipliés par 2 (au lieu de 3)."
    ),
    (
        "**Le jeu à 5 joueurs**\n"
        "Un joueur est « mort » : il distribue et ne joue pas. Chacun est mort à tour de "
        "rôle.\n"
        "Les cartes sont distribuées 3 par 3, le Chien fait 3 cartes, chaque joueur reçoit 15 "
        "cartes.\n"
        "Avant de retourner le Chien, le preneur appelle un Roi (une Dame s'il a 4 Rois, "
        "etc.). Si la carte est au Chien ou si le preneur s'est appelé, il joue seul contre "
        "quatre ; sinon le détenteur devient son partenaire.\n"
        "Poignées : simple 8 Atouts, double 10, triple 13.\n"
        "La marque se répartit 2/3 pour le preneur et 1/3 pour le partenaire."
    ),
]


@commands.group(invoke_without_command=True)
async def rules(ctx, arg=None):
    """
    Règles du tarot : résumé, full, contrats, poignees, descendante.
    """
    if arg is None:
        await ctx.send(RESUME)
        return
    await ctx.send(
        error_message(
            "rules",
            f"« {arg} » n'est pas une règle. Sous-commandes : "
            "`full`, `contrats`, `poignees`, `descendante`.",
        )
    )


@rules.command(name="full")
async def rules_full(ctx):
    """Règlement officiel détaillé (plusieurs messages)."""
    for block in FULL_RULES:
        if len(block) > DISCORD_MAX_LEN:
            raise ValueError(f"Bloc de règles trop long : {len(block)} caractères.")
        await ctx.send(block)


@rules.command(name="contrats")
async def rules_contrats(ctx):
    """Points à atteindre selon le nombre de bouts."""
    body = []
    for i, v in enumerate(CONTRAT_PAR_BOUT):
        body.append([i, v])

    output = t2a(header=["Bouts", "Points"], body=body, first_col_heading=True)

    await ctx.send(f"```\n{output}\n```")


@rules.command(name="poignees")
async def rules_poignees(ctx, n_players=5):
    """
    Donne le nombre d'atouts pour les différentes poignées selon le nombre de joueurs "n_players".
    """
    try:
        n_players = int(n_players)
    except (TypeError, ValueError):
        n_players = None
    if n_players not in POIGNEES:
        await ctx.send(
            error_message(
                "rules poignees",
                "Le nombre de joueurs doit être 3, 4 ou 5. Exemple : `t/rules poignees 4`",
            )
        )
        return

    body = []
    for k, v in POIGNEES[n_players].items():
        body.append([k, v])

    output = t2a(header=["Poignée", "Prime"], body=body, first_col_heading=True)

    await ctx.send(f"Poignées à {n_players!s} joueurs:\n```\n{output}\n```")


@rules.command(name="descendante")
async def rules_descendante(ctx):
    """Règles de la descendante du labo (le moins de points gagne)."""
    await ctx.send(
        "**Descendante**\n"
        "Jeu du labo : chacun marque les points qu'il a faits, et **le but est d'en avoir "
        "le moins possible**.\n\n"
        "Le score de chaque joueur est calculé à partir des points de tous :\n"
        "```\n"
        "score = somme(points des autres) − (n − 1) x ses propres points\n"
        "```\n"
        "où `n` est le nombre de joueurs (3, 4 ou 5).\n"
        "Autrement dit, chaque joueur donne ses points à tous les autres, et garde "
        "`(n − 1) x` ses points à sa charge.\n\n"
        "Exemple à 3 joueurs, points respectifs 20 / 20 / 51 :\n"
        "- ceux à 20 marquent +31, celui à 51 marque −62 : le plus gros total perd.\n\n"
        "`t/descendante 20 20 51` pour saisir une donne."
    )
