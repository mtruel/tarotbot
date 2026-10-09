from typing import Any

import discord
from discord.ext import commands
from table2ascii import table2ascii as t2a

from tarot_commands.help import error_message
from tarot_commands.history import append_related_message_id, update_history
from tarot_commands.rules import CONTRAT_PAR_BOUT, PRIMES
from tarot_commands.sessions import (
    GameSession,
    clear_all_sessions,
    create_session,
    find_history_by_message_id,
    get_session,
    pop_session,
    semantic_from_history,
    semantic_from_session,
    temp_session,
)
from tarot_commands.state import known_players, load_history, player_index, resolve_player

# Re-exports pour les tests
__all__ = [
    "GameSession",
    "ParseError",
    "autoparse",
    "create_session",
    "get_session",
    "handle_auto_edit",
    "pop_session",
    "reset_cache",
]
from unidecode import unidecode


class ParseError(Exception):
    pass


ENCHERE_NAMES = {1: "Petite", 2: "Garde", 4: "GardeSans", 6: "GardeContre"}

EXPIRED_MSG = "Saisie expirée ou introuvable. Relance la commande."


def reset_cache():
    """Vide toutes les sessions pending (tests / nettoyage)."""
    clear_all_sessions()


def partie_details(session: GameSession):
    partenaire = session.game_players["Partenaire"]
    return {
        "message_id": session.request_message_id,
        "type": "partie",
        "enchere": ENCHERE_NAMES.get(session.enchere, session.enchere),
        "multiplicateur": session.enchere,
        "preneur": session.game_players["Preneur"][0],
        "partenaire": partenaire[0] if partenaire else None,
        "defenseurs": list(session.game_players["Défenseurs"]),
        "bouts": session.bouts,
        "points_attaque": session.points_attaque,
        "primes_attaque": list(session.primes_attaque),
        "primes_defense": list(session.primes_defense),
        "miseres": list(session.miseres),
    }


def descendante_details(session: GameSession):
    joueurs = [p for p in session.descendante_players.values() if p]
    return {
        "message_id": session.request_message_id,
        "type": "descendante",
        "joueurs": joueurs,
        "points": list(session.descendante_points),
        "miseres": list(session.miseres),
    }


def confirm_message_content(session: GameSession) -> str:
    if session.kind == "descendante" or session.reparse.startswith("Descendante:\n"):
        return (
            f"Somme des points = {sum(session.descendante_points)}."
            f"**Is this parse correct?:**\n{session.reparse}"
        )
    return f"**Is this parse correct?:**\n{session.reparse}"


class SelectEnchere(discord.ui.Select):
    def __init__(self, request_message_id):
        self.request_message_id = request_message_id
        options = [
            discord.SelectOption(label="Petite", emoji="🤏"),
            discord.SelectOption(label="Garde", emoji="✋"),
            discord.SelectOption(label="GardeSans", emoji="✊"),
            discord.SelectOption(label="GardeContre", emoji="💪"),
        ]
        super().__init__(placeholder="👋 Enchère:", max_values=1, min_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        session = get_session(self.request_message_id)
        if session is None:
            await interaction.response.send_message(EXPIRED_MSG, ephemeral=True)
            return
        if self.values[0] == "Petite":
            session.enchere = 1
        elif self.values[0] == "Garde":
            session.enchere = 2
        elif self.values[0] == "GardeSans":
            session.enchere = 4
        elif self.values[0] == "GardeContre":
            session.enchere = 6
        await interaction.response.send_message(content=f"Choix: {self.values[0]}!", ephemeral=True)


class SelectBouts(discord.ui.Select):
    def __init__(self, request_message_id):
        self.request_message_id = request_message_id
        options = [
            discord.SelectOption(label="0"),
            discord.SelectOption(label="1"),
            discord.SelectOption(label="2"),
            discord.SelectOption(label="3"),
        ]
        super().__init__(placeholder="🧶 Bouts:", max_values=1, min_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        session = get_session(self.request_message_id)
        if session is None:
            await interaction.response.send_message(EXPIRED_MSG, ephemeral=True)
            return
        session.bouts = int(self.values[0])
        await interaction.response.send_message(content=f"Choix: {self.values[0]}!", ephemeral=True)


# Discord refuse un menu de plus de 25 options (HTTP 400).
MAX_SELECT_OPTIONS = 25


def menu_players(history=None, player_names=None):
    """Noms proposes dans les menus, limites a MAX_SELECT_OPTIONS.

    Au-dela de la limite, on garde les joueurs ayant joue le plus recemment,
    puis les inscrits sans partie (ordre de la liste des joueurs). L'ordre d'affichage reste
    celui de la liste des joueurs. t/auto reconnait toujours tous les joueurs.
    """
    if history is None:
        history = load_history()
    players = known_players(history, player_names)
    if len(players) <= MAX_SELECT_OPTIONS:
        return players
    recent = {}
    for entry in reversed(history):
        for name in entry["scores"]:
            recent.setdefault(name, len(recent))
    ranked = sorted(players, key=lambda p: recent.get(p, len(players) + players.index(p)))
    kept = set(ranked[:MAX_SELECT_OPTIONS])
    return [p for p in players if p in kept]


class SelectPlayers(discord.ui.Select):
    def __init__(self, role, emote, request_message_id):
        self.request_message_id = request_message_id
        PLAYERS = menu_players()

        options = [discord.SelectOption(label=player_name) for player_name in PLAYERS]

        self.role = role
        if self.role == "Misère":
            max_values = 5
        elif self.role == "Défenseurs":
            max_values = 4
        else:  # Descendante #1->#5, Preneur, Partenaire, Misères
            max_values = 1

        if self.role == "Preneur":
            min_values = 1
        elif self.role in ["Partenaire"]:
            min_values = 0
        elif self.role == "Défenseurs":
            min_values = 2
        elif self.role in [
            "#1",
            "#2",
            "#3",
            "#4",
            "#5",
        ]:  # Descendante: we give the right amount of SelectMenus
            min_values = 1  # so all should be answered.
        else:
            min_values = 0  # should never happen

        super().__init__(
            placeholder=f"{emote} {self.role}:",
            max_values=max_values,
            min_values=min_values,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        session = get_session(self.request_message_id)
        if session is None:
            await interaction.response.send_message(EXPIRED_MSG, ephemeral=True)
            return
        if self.values:
            if "#" in self.role:  # Descendante
                session.descendante_players[self.role] = self.values[0]
                await interaction.response.send_message(
                    content=f"Choix: {self.values[0]!s}!", ephemeral=True
                )
            elif self.role != "Misères":
                session.game_players[self.role] = self.values
                await interaction.response.send_message(
                    content=f"Choix: {self.values!s}!", ephemeral=True
                )
            else:  # Misère
                session.miseres = self.values
                await interaction.response.send_message(
                    content=f"Choix: {self.values!s}!", ephemeral=True
                )


class SelectPrimes(discord.ui.Select):
    def __init__(self, request_message_id, attaque=True):
        self.request_message_id = request_message_id
        self.attaque = attaque
        self.defense = not attaque
        emote = "⚔" if self.attaque else "🛡️"
        options = [
            discord.SelectOption(label="Simple Poignée", emoji="✊"),
            discord.SelectOption(label="Double Poignée", emoji="✊"),
            discord.SelectOption(label="Triple Poignée", emoji="✊"),
            discord.SelectOption(label="Petit au bout", emoji="☝️"),
            discord.SelectOption(label="Chelem annoncé", emoji="🤑"),
            discord.SelectOption(label="Chelem non annoncé", emoji="🤭"),
            discord.SelectOption(label="Chelem chuté", emoji="😭"),
        ]
        if self.defense:
            del options[-1]
            del options[-2]
        super().__init__(
            placeholder="{} Primes {}:".format(emote, "Attaque" if self.attaque else "Défense"),
            max_values=3,
            min_values=0,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        session = get_session(self.request_message_id)
        if session is None:
            await interaction.response.send_message(EXPIRED_MSG, ephemeral=True)
            return
        if self.attaque:
            session.primes_attaque = self.values
        else:
            session.primes_defense = self.values
        await interaction.response.send_message(content=f"Choix: {self.values!s}!", ephemeral=True)


def _bind_calcul_view(session: GameSession, view: discord.ui.View) -> discord.ui.View:
    """Associe la View Calcul a la session ; les timeouts des anciennes Views sont ignores."""
    session.view_generation += 1
    # Attributs dynamiques lus ensuite via getattr dans _expire_calcul_view
    bound: Any = view
    bound.request_message_id = session.request_message_id
    bound.view_generation = session.view_generation
    return view


async def _expire_calcul_view(view: discord.ui.View):
    session = get_session(getattr(view, "request_message_id", None))
    if session is None:
        return
    if getattr(view, "view_generation", None) == session.view_generation:
        pop_session(session.request_message_id)


class SelectViewGame(discord.ui.View):
    def __init__(self, request_message_id, *, timeout=300):
        super().__init__(timeout=timeout)
        self.request_message_id = request_message_id
        self.add_item(SelectPlayers("Preneur", "⚔️", request_message_id))
        self.add_item(SelectPlayers("Partenaire", "🗡️️", request_message_id))
        self.add_item(SelectPlayers("Défenseurs", "🛡️", request_message_id))
        self.add_item(SelectEnchere(request_message_id))
        self.add_item(SelectBouts(request_message_id))


class SelectViewDescendante(discord.ui.View):
    def __init__(self, request_message_id, n_players, *, timeout=300):
        super().__init__(timeout=timeout)
        self.request_message_id = request_message_id
        for i in range(n_players):
            self.add_item(SelectPlayers(f"#{i + 1}", "☂️️", request_message_id))


class SelectViewPrimes(discord.ui.View):
    def __init__(self, request_message_id, *, timeout=300):
        super().__init__(timeout=timeout)
        self.request_message_id = request_message_id
        self.add_item(SelectPrimes(request_message_id, attaque=True))
        self.add_item(SelectPrimes(request_message_id, attaque=False))
        self.add_item(SelectPlayers("Misères", "😇️", request_message_id))


def finalize_partie_scores(session: GameSession):
    """Valide une partie et calcule les scores.

    Returns
    -------
    (scores, None) ou (None, message_erreur)
    """
    if not session.game_players["Preneur"]:
        return None, "Preneur?"

    if len(session.game_players["Défenseurs"]) < 2:
        return None, "Pas assez de défenseurs."

    if session.game_players["Preneur"][0] in session.game_players["Défenseurs"]:
        return None, "Le Preneur défend aussi?"

    if (
        session.game_players["Partenaire"]
        and session.game_players["Partenaire"][0] in session.game_players["Défenseurs"]
    ):
        return None, "Le Partenaire défend aussi?."

    if (
        session.game_players["Partenaire"]
        and session.game_players["Partenaire"][0] in session.game_players["Preneur"]
    ):
        return None, "Le Partenaire est Preneur?."

    n_players = len(
        session.game_players["Preneur"]
        + session.game_players["Partenaire"]
        + session.game_players["Défenseurs"]
    )

    if n_players not in [3, 4, 5]:
        return None, f"Le Tarot ne se joue pas à {n_players}."

    if session.game_players["Partenaire"] and n_players != 5:
        return None, "Pas de partenaire à moins de 5."

    n_chelem_tot = 0
    for x in [session.primes_attaque, session.primes_defense]:
        if x:
            n_poignees = 0
            n_chelem = 0
            for p in x:
                if "Poignée" in p:
                    n_poignees += 1
                if "Chelem" in p:
                    n_chelem += 1
            if n_poignees > 1:
                return None, "Plus d'un type de Poignée."
            if n_chelem > 1:
                return None, "Plus d'un type de Chelem."
            if n_chelem == 1:
                n_chelem_tot += 1

    if n_chelem_tot > 1:
        return None, "Un chelem par équipe."

    if (
        session.primes_attaque
        and session.primes_defense
        and "Petit au bout" in session.primes_attaque
        and "Petit au bout" in session.primes_defense
    ):
        return None, "Un seul Petit."

    if session.bouts is None:
        session.bouts = 0

    if not session.enchere:
        return None, "Pas de réponse pour les enchères."

    for player in session.miseres:
        if not (
            player in session.game_players["Preneur"]
            or player in session.game_players["Partenaire"]
            or player in session.game_players["Défenseurs"]
        ):
            return None, f"Le joueur {player} est listé dans les misères mais ne joue pas."

    return calcul_scores(session), None


def finalize_descendante_scores(session: GameSession):
    """Valide une descendante et calcule les scores.

    Returns
    -------
    (scores, None) ou (None, message_erreur)
    """
    n_players = sum([bool(v) for v in session.descendante_players.values()])

    if n_players != len(session.descendante_points):
        return None, "Merci de remplir toutes les entrées."

    test_unique_dict = {player: 0 for player in session.descendante_players.values() if player}
    if len(test_unique_dict) != n_players:
        return None, "Liste de joueurs non injective."

    for player in session.miseres:
        if player not in [p for p in session.descendante_players.values() if p]:
            return None, f"Le joueur {player} est listé dans les misères mais ne joue pas."

    scores = calcul_score_descendante(session.descendante_players, session.descendante_points)
    scores = affecte_miseres(scores, session)
    return scores, None


class GameCalculButton(discord.ui.View):
    def __init__(self, request_message_id, *, timeout=180):
        super().__init__(timeout=timeout)
        self.request_message_id = request_message_id
        self.view_generation = 0
        session = get_session(request_message_id)
        if session is not None:
            _bind_calcul_view(session, self)

    async def on_timeout(self):
        await _expire_calcul_view(self)

    @discord.ui.button(label="Calcul", style=discord.ButtonStyle.blurple)
    async def calcul(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = get_session(self.request_message_id)
        if session is None:
            await interaction.response.send_message(EXPIRED_MSG)
            return

        scores, err = finalize_partie_scores(session)
        if err:
            await interaction.response.send_message(err)
            return

        game_id = session.request_message_id
        update_history(scores, partie_details(session))
        button.disabled = True  # After updating the score!
        pop_session(self.request_message_id)
        await interaction.response.edit_message(view=self)
        await send_score_table(interaction, scores, game_id)


class DescendanteCalculButton(discord.ui.View):
    def __init__(self, request_message_id, *, timeout=180):
        super().__init__(timeout=timeout)
        self.request_message_id = request_message_id
        self.view_generation = 0
        session = get_session(request_message_id)
        if session is not None:
            _bind_calcul_view(session, self)

    async def on_timeout(self):
        await _expire_calcul_view(self)

    @discord.ui.button(label="Calcul", style=discord.ButtonStyle.blurple)
    async def calcul(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = get_session(self.request_message_id)
        if session is None:
            await interaction.response.send_message(EXPIRED_MSG)
            return

        scores, err = finalize_descendante_scores(session)
        if err:
            await interaction.response.send_message(err)
            return

        game_id = session.request_message_id
        update_history(scores, descendante_details(session))
        button.disabled = True  # After updating the score!
        pop_session(self.request_message_id)
        await interaction.response.edit_message(view=self)
        await send_score_table(interaction, scores, game_id)


@commands.command()
async def game(ctx, value=-999):
    """
    Entre une nouvelle partie avec [value] points faits par l'attaque: lance des menus à remplir pour les détails.

    Attention, le nombre de points à rentrer doit être ENTIER!! Sinon la commande renverra une erreur.

    Par exemple, si l'attaque ne fait que deux plis avec que des cartes valant 0.5 points, l'attaque a marqué 5 points
    donc il faut rentrer "t/game 5".
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        await ctx.send(
            error_message(
                "game",
                "Les points de l’attaque doivent être un entier entre 0 et 91, "
                "sans virgule. Exemple : `t/game 45`",
            )
        )
        return

    if v == -999:
        await ctx.send(
            error_message(
                "game",
                "Il manque les points de l’attaque, un entier entre 0 et 91. Exemple : `t/game 45`",
            )
        )
        return

    if v < 0 or v > 91:
        await ctx.send(
            error_message(
                "game",
                f"{v} est hors limites. Les points de l’attaque vont de 0 à 91. "
                "Exemple : `t/game 45`",
            )
        )
        return

    rid = ctx.message.id
    session = create_session(
        rid,
        channel_id=ctx.channel.id,
        author_id=ctx.author.id,
        source="game",
    )
    session.points_attaque = v
    session.kind = "partie"
    await ctx.send("Alors? 👀", view=SelectViewGame(rid))
    await ctx.send("Des primes?", view=SelectViewPrimes(rid))
    await ctx.send("", view=GameCalculButton(rid))


def calcul_scores(session: GameSession):
    # we consider all values to be legal (checked in the "calcul" button)
    assert session.points_attaque is not None
    assert session.bouts is not None
    assert session.enchere is not None
    delta = session.points_attaque - CONTRAT_PAR_BOUT[session.bouts]
    s = delta / abs(delta) if delta != 0 else 1
    primes_attaque = {k: (v if k in session.primes_attaque else 0) for (k, v) in PRIMES.items()}
    primes_defense = {k: (v if k in session.primes_defense else 0) for (k, v) in PRIMES.items()}
    score = session.enchere * (
        abs(delta) + 25 + s * (primes_attaque["Petit au bout"] - primes_defense["Petit au bout"])
    )
    score += (
        primes_attaque["Simple Poignée"]
        + primes_attaque["Double Poignée"]
        + primes_attaque["Triple Poignée"]
        + primes_defense["Simple Poignée"]
        + primes_defense["Double Poignée"]
        + primes_defense["Triple Poignée"]
    )

    score += (
        primes_attaque["Chelem annoncé"]
        + primes_attaque["Chelem non annoncé"]
        + primes_attaque["Chelem chuté"]
    )

    score_attaquant = s * score * len(session.game_players["Défenseurs"])
    score_attaquant -= (
        len(session.game_players["Défenseurs"]) * primes_defense["Chelem non annoncé"]
    )
    score_defense = -s * score + primes_defense["Chelem non annoncé"]
    scores = {}

    if session.game_players["Partenaire"]:
        scores[session.game_players["Partenaire"][0]] = score_attaquant // 3
        scores[session.game_players["Preneur"][0]] = (2 * score_attaquant) // 3
    else:
        scores[session.game_players["Preneur"][0]] = score_attaquant

    for def_name in session.game_players["Défenseurs"]:
        scores[def_name] = score_defense

    scores = affecte_miseres(scores, session)

    return scores


def calcul_score_descendante(descendante_players, descendante_points):
    players = [p for p in descendante_players.values() if p]
    n_players = len(players)
    scores = {p: 0 for p in players}
    for idx, player in enumerate(players):
        player_points = descendante_points[idx]
        scores[player] -= n_players * player_points  # will receive +player_points in the next loop
        for player2 in players:  # this includes the current player!
            scores[player2] += player_points
    return scores


@commands.command()
async def descendante(ctx, *points):
    """
    Entre une nouvelle partie en descendante.

    Il faut donner les scores des joueurs, puis une interface demandera les noms des joueurs, et affectera les scores.

    Par exemple "t/descendante 20 20 51" fera remplir les noms de 3 joueurs dont les points respectifs
    sont 20, 20 et 51.
    """
    try:
        points = [int(point) for point in points]
    except (TypeError, ValueError):
        await ctx.send(
            error_message(
                "descendante",
                "Chaque score doit être un entier entre 0 et 91. "
                "Exemple : `t/descendante 20 20 51`",
            )
        )
        return
    n_players = len(points)

    if n_players not in [3, 4, 5]:
        await ctx.send(
            error_message(
                "descendante",
                f"Il faut 3, 4 ou 5 scores, un par joueur. Reçu : {n_players}. "
                "Exemple : `t/descendante 20 20 51`",
            )
        )
        return

    for point in points:
        if point < 0 or point > 91:
            await ctx.send(
                error_message(
                    "descendante",
                    f"{point} est hors limites. Chaque score va de 0 à 91. "
                    "Exemple : `t/descendante 20 20 51`",
                )
            )
            return

    rid = ctx.message.id
    session = create_session(
        rid,
        channel_id=ctx.channel.id,
        author_id=ctx.author.id,
        source="descendante",
    )
    session.descendante_points = points
    session.kind = "descendante"
    await ctx.send(
        f"Somme des points = {sum(points)}.\nJoueurs respectifs:",
        view=SelectViewDescendante(rid, n_players),
    )
    await ctx.send("", view=DescendanteCalculButton(rid))


def get_score_table_string(scores):
    body = []
    for k, v in scores.items():
        body.append([k, "{}{}".format("+" if v >= 0 else "", int(v))])

    output = t2a(header=["Nom", "Score"], body=body, first_col_heading=True)
    return output


def format_score_table_message(scores, game_id):
    """Tableau ASCII + id canonique en sous-texte Discord (gris, copiable)."""
    return f"```\n{get_score_table_string(scores)}\n```\n-# id: `{game_id}`"


async def send_score_table(interaction, scores, game_id):
    """Envoie le tableau et enregistre l'id du message dans related_message_ids."""
    msg = await interaction.followup.send(format_score_table_message(scores, game_id))
    score_msg_id = getattr(msg, "id", None)
    if score_msg_id is not None:
        append_related_message_id(game_id, score_msg_id)
    return msg


def affecte_miseres(scores, session: GameSession):
    all_players = (
        session.game_players["Preneur"]
        + session.game_players["Partenaire"]
        + session.game_players["Défenseurs"]
    )
    n_players = len(all_players)

    for misere_player in session.miseres:
        # misere_player will lose 10 in the following loop, so all other players give misere_player 10
        scores[misere_player] += n_players * 10
        for player in all_players:
            scores[player] -= 10
    return scores


def str_idx_to_split_idx(s, str_idx, split=" "):
    """
    Gives the index in s.split(split) corresponding to the index str_idx in the string
    Parameters
    ----------
    s : str
        input string
    str_idx : int
        index within s
    split : str, optional
        split argument for s.split(split), default to ' '

    Returns
    -------
    i : int
    """
    if s[str_idx] == split:
        raise ValueError(
            f"Input string index {str_idx} corresponds to a split <{split}> in input string {s}"
        )
    if str_idx > len(s):
        raise ValueError(f"index {str_idx} >= {len(s)} length of input string")
    s_list = s.split(split)
    split_start_idx_in_str = 0
    for e_idx, e in enumerate(s_list):
        if split_start_idx_in_str <= str_idx < split_start_idx_in_str + len(e):  # str_idx is in e
            return e_idx
        split_start_idx_in_str += len(e) + 1


def find_split_idx_of_subsequence(s, sub, split=" "):
    """
    Finds the index within s.split(split) of the last element of sub.split(split)
    For example if s = 'i am now a tuna', the output for split=' ' and sub='now a' is 3.

    Parameters
    ----------
    s : str
        input string
    sub : str
        substring to locate within s
    split : str, optional
        split argument for s.split(split), default to ' '

    Returns
    -------
    i : int
    """
    str_idx = s.find(sub)  # let it raise ValueError if not found
    if str_idx == -1:
        raise ValueError(f"sub {sub} is not a substring of {s}")
    return str_idx_to_split_idx(s, str_idx + len(sub) - 1, split)


def clean_msg(msg):
    return (
        msg.replace(".", "")
        .replace(",", "")
        .replace(":", "")
        .replace(";", "")
        .replace("'", "")
        .replace('"', "")
    )


def autoparse(msg, session: GameSession):
    enchere_name = None
    session.clear_parse_state()
    msg = clean_msg(msg)
    msg_list = msg.split(" ")
    msg_lower_list = msg.lower().split(" ")
    msg_decode_lower = unidecode(msg).lower()
    msg_decode_lower_list = msg_decode_lower.split(" ")

    PLAYERS = known_players()
    names = player_index(PLAYERS)

    preneur_token = msg_list[0]
    preneur = resolve_player(preneur_token, PLAYERS, names)
    if preneur is None:
        if unidecode(preneur_token).lower() in ["desc", "descendante"]:
            return autoparse_desc(msg, session)
        raise ParseError(
            f"Le premier mot doit être le preneur, déjà ajouté au classement, "
            f"ou desc / descendante. « {preneur_token} » n’est pas un joueur. "
            f"Vérifie l’orthographe, ou ajoute-le avec `t/add_player {preneur_token}`."
        )
    session.game_players["Preneur"] = [preneur]

    if "petite" in msg.lower():
        session.enchere = 1
        if "garde" in msg.lower():
            raise ParseError("Une seule enchère : petite, garde, garde sans ou garde contre.")
        enchere_name = "petite"
    elif "garde" in msg.lower():
        if "garde sans" in msg.lower():
            session.enchere = 4
            if "garde contre" in msg.lower():
                raise ParseError("Une seule enchère : garde sans ou garde contre, pas les deux.")
            enchere_name = "garde sans"
        elif "garde contre" in msg.lower():
            session.enchere = 6
            enchere_name = "garde contre"
        else:
            session.enchere = 2  # garde
            enchere_name = "garde"
    else:
        raise ParseError(
            "Il manque l’enchère : petite, garde, garde sans ou garde contre. "
            "Exemple : `t/auto Alice garde 45 2 vs Bob Carol`"
        )

    # find bid location
    try:
        find_split_idx_of_subsequence(msg.lower(), enchere_name)
    except ValueError:
        raise ParseError(
            f"Enchère « {enchere_name} » introuvable dans le message. "
            "Écris-la en toutes lettres : petite, garde, garde sans ou garde contre."
        ) from None

    vs_idx = None
    try:
        vs_idx = find_split_idx_of_subsequence(msg.lower(), "vs")
    except ValueError:
        raise ParseError(
            "Il manque vs entre l’attaque et la défense. "
            "Exemple : `t/auto Alice garde 45 2 vs Bob Carol`"
        ) from None

    avec_idx = None
    try:
        avec_idx = msg_lower_list.index("avec")
    except ValueError:
        try:
            avec_idx = msg_lower_list.index("with")
        except ValueError:  # parsed 1 vs rest, check that only 1 name before vs
            for e in msg_list[:vs_idx]:
                matched = resolve_player(e, PLAYERS, names)
                if matched and matched != preneur:
                    raise ParseError(
                        f"« {matched} » est avant vs alors que le preneur est {preneur}. "
                        f"S’il est partenaire : avec {matched} avant vs. "
                        f"S’il défend : place-le après vs."
                    ) from None

    # find partenaire name
    if avec_idx is not None:
        avec_count = 0
        for e in msg_list[avec_idx:vs_idx]:
            matched = resolve_player(e, PLAYERS, names)
            if matched:
                avec_count += 1
                session.game_players["Partenaire"].append(matched)
            if avec_count > 1:
                raise ParseError("Un seul partenaire après avec.")

    # determine segments for attack primes, defense primes and miseres
    # misere
    misere_idx = None
    if "misere" in msg_decode_lower_list:
        misere_idx = msg_decode_lower_list.index("misere")
    elif "miseres" in msg_lower_list:
        misere_idx = msg_lower_list.index("miseres")

    # primes
    prime_a_idx, prime_d_idx = None, None
    if "prime" in msg.lower():
        exists_prime_a = "prime att" in msg_decode_lower or "primes att" in msg_decode_lower
        if exists_prime_a:  # find primes attaque something
            try:
                prime_a_idx = find_split_idx_of_subsequence(msg_decode_lower, "prime att")
            except ValueError:
                try:
                    prime_a_idx = find_split_idx_of_subsequence(msg_decode_lower, "primes att")
                except ValueError:
                    raise ParseError(
                        "prime attaque est indiqué mais introuvable. "
                        "Écris prime attaque puis les primes, "
                        "par exemple prime attaque petit au bout."
                    ) from None
        exists_prime_d = "prime def" in msg_decode_lower or "primes def" in msg_decode_lower
        if exists_prime_d:  # find prime(s) défense something
            try:
                prime_d_idx = find_split_idx_of_subsequence(msg_decode_lower, "prime def")
            except ValueError:
                try:
                    prime_d_idx = find_split_idx_of_subsequence(msg_decode_lower, "primes def")
                except ValueError:
                    raise ParseError(
                        "prime défense est indiqué mais introuvable. "
                        "Écris prime défense puis les primes."
                    ) from None
        if not (exists_prime_a or exists_prime_d):  # only prime, assume for attack
            try:
                prime_a_idx = find_split_idx_of_subsequence(msg_decode_lower, "prime")
            except ValueError:
                raise ParseError(
                    "Le mot prime est indiqué mais introuvable. "
                    "Écris prime, prime attaque ou prime défense."
                ) from None

    segments_idx = sorted(
        [
            (k, v)
            for (k, v) in [
                ("vs", vs_idx),
                ("prime_a", prime_a_idx),
                ("prime_d", prime_d_idx),
                ("misere", misere_idx),
            ]
            if v is not None
        ],
        key=lambda c: c[1],
    )

    # handle segment by segment
    for seg_idx, (seg_name, seg_position) in enumerate(segments_idx):
        next_seg_position = (
            None if seg_idx == len(segments_idx) - 1 else segments_idx[seg_idx + 1][1]
        )
        segment_msg_list = msg_list[seg_position:next_seg_position]
        segment_msg = " ".join(segment_msg_list)
        if seg_name == "vs":
            def_players_count = 0
            for e in segment_msg_list:
                matched = resolve_player(e, PLAYERS, names)
                if matched:
                    session.game_players["Défenseurs"].append(matched)
                    def_players_count += 1
            if def_players_count <= 1 or def_players_count >= 5:
                raise ParseError(
                    f"Après vs, il faut 2, 3 ou 4 défenseurs déjà au classement. "
                    f"J’en ai trouvé {def_players_count} dans : {' '.join(segment_msg_list)}. "
                    "Vérifie les noms (t/add_player) et sépare-les par des espaces."
                )
            if session.game_players["Partenaire"] and def_players_count != 3:
                raise ParseError(
                    f"Avec un partenaire, il faut exactement 3 défenseurs après vs "
                    f"(partie à 5). J’en ai trouvé {def_players_count}."
                )
        elif seg_name == "prime_a":
            for prime_name in PRIMES:
                if unidecode(prime_name.lower()) in unidecode(segment_msg.lower()):
                    session.primes_attaque.append(prime_name)

        elif seg_name == "prime_d":
            for prime_name in PRIMES:
                if unidecode(prime_name.lower()) in unidecode(segment_msg.lower()):
                    session.primes_defense.append(prime_name)

        elif seg_name == "misere":
            for e in segment_msg_list:
                matched = resolve_player(e, PLAYERS, names)
                if matched:
                    session.miseres.append(matched)

    # find number of bouts: assume it's the only number between 0 and 3 separated by spaces
    for bouts in [0, 1, 2, 3]:
        found_bouts = 0
        if str(bouts) in msg_list:
            session.bouts = bouts
            found_bouts += 1
        if found_bouts > 1:
            raise ParseError("Un seul nombre de bouts : 0, 1, 2 ou 3.")

    # find score: assume it's the only number over 4 separated by spaces in the msg
    for e in msg_list:
        found_scores = 0
        if e.isnumeric() and int(e) >= 4:
            session.points_attaque = int(e)
            found_scores += 1
        if found_scores > 1:
            raise ParseError(
                "Un seul score (un nombre supérieur ou égal à 4). Les bouts restent 0, 1, 2 ou 3."
            )

    if session.points_attaque is None:
        raise ParseError(
            "Il manque le score de l’attaque : un nombre supérieur ou égal à 4. "
            "Exemple : `t/auto Alice garde 45 2 vs Bob Carol`"
        )

    session.kind = "partie"
    reparse = (
        f"Preneur:    {session.game_players['Preneur']},\n"
        f"Partenaire: {session.game_players['Partenaire']},\n"
        f"Score:      {session.points_attaque},\n"
        f"Bouts:      {session.bouts},\n"
        f"Enchère:    {enchere_name} ({session.enchere}),\n"
        f"Défense:    {session.game_players['Défenseurs']},\n"
        f"Primes Att: {session.primes_attaque},\n"
        f"Primes Déf: {session.primes_defense},\n"
        f"Misères:    {session.miseres}"
    )

    if session.bouts is None:
        reparse += "\n⚠️ Aucun bout (0, 1, 2 ou 3)."

    session.reparse = reparse
    return reparse


def autoparse_desc(msg, session: GameSession):
    """
    Parses a message starting with 'descendante', then a names and scores.
    Omitting punctuation, assumes 'descendante <name1> <score1> <name2> <score2> ...'
    """
    session.clear_parse_state()
    msg = clean_msg(msg)
    msg_list = msg.split(" ")

    PLAYERS = known_players()
    names = player_index(PLAYERS)

    player_idx = 1
    for e_idx, e in enumerate(msg_list):
        matched = resolve_player(e, PLAYERS, names)
        if matched:
            if e_idx == len(msg_list) - 1 or not msg_list[e_idx + 1].isnumeric():
                raise ParseError(
                    f"Il manque le score de {matched}. "
                    "Forme : `t/auto descendante Alice 20 Bob 20 Carol 51`"
                )
            session.descendante_players[f"#{player_idx}"] = matched
            session.descendante_points.append(int(msg_list[e_idx + 1]))
            player_idx += 1

    if player_idx == 1:
        raise ParseError(
            "Aucun joueur reconnu. Forme : `t/auto descendante Alice 20 Bob 20 Carol 51` "
            "(noms déjà au classement, chacun suivi de son score)."
        )

    session.kind = "descendante"
    reparse = "Descendante:\n"
    for player_score, player in list(
        zip(session.descendante_points, session.descendante_players.values(), strict=False)
    ):
        reparse = reparse + f"{player}: {player_score},\n"

    reparse = reparse[:-2]  # removes last ,\n
    session.reparse = reparse
    return reparse


def extract_auto_body(content: str):
    """Retourne le corps apres t/auto, ou None si ce n'est pas une commande auto."""
    if not content:
        return None
    text = content.strip()
    if not text.lower().startswith("t/"):
        return None
    rest = text[2:].lstrip()
    parts = rest.split(None, 1)
    if not parts or parts[0].lower() != "auto":
        return None
    return parts[1] if len(parts) > 1 else ""


def handle_auto_edit(message_id: int, new_content: str, author_id: int, history=None):
    """Logique pure pour une edition de message t/auto.

    Returns
    -------
    (action, payload)
        action in {'noop', 'updated', 'warn', 'error', 'ignore'}
        payload : session mise a jour, message d'erreur, ou None
    """
    body = extract_auto_body(new_content)
    if body is None:
        return "ignore", None

    session = get_session(message_id)
    if session is not None:
        if session.source != "auto":
            return "ignore", None
        if session.author_id is not None and author_id != session.author_id:
            return "ignore", None
        trial = temp_session()
        try:
            new_reparse = autoparse(body, trial)
        except ParseError as e:
            return "error", e.args[0]
        if new_reparse == session.reparse:
            return "noop", None
        session.copy_parse_from(trial)
        return "updated", session

    if history is None:
        history = load_history()
    entry = find_history_by_message_id(history, message_id)
    if entry is None:
        return "ignore", None

    trial = temp_session()
    try:
        autoparse(body, trial)
    except ParseError:
        # Edition illisible mais partie deja enregistree : avertir quand meme
        # si on ne peut pas comparer ; on avertit pour toute edition d'un
        # message deja lie a l'historique.
        return "warn", entry

    hist_sem = semantic_from_history(entry)
    new_sem = semantic_from_session(trial)
    if hist_sem is None or hist_sem == new_sem:
        return "noop", None
    return "warn", entry


@commands.command()
async def auto(ctx, *, value):
    """
    Tente d'interpréter le message et d'affecter les scores en conséquence. Cliquer sur le bouton valide et affecte.

    Elements de syntaxe imposés: (Attaque) 'vs' (Défense)

    Partenaire: mot-clef 'avec' ou 'with'

    Primes: 'prime attaque' ou 'prime défense' si nécessaire, et juste 'prime' est un raccourci pour Attaque

    Descendante: commencer par 'Descendante' ou desc puis mettre nom, score, nom, score etc

    """
    rid = ctx.message.id
    session = create_session(
        rid,
        channel_id=ctx.channel.id,
        author_id=ctx.author.id,
        source="auto",
    )
    try:
        reparse = autoparse(value, session)
    except ParseError as e:
        pop_session(rid)
        await ctx.send(error_message("auto", e.args[0]))
        return

    if session.kind == "descendante" or reparse.startswith("Descendante:\n"):
        confirm = await ctx.send(
            confirm_message_content(session),
            view=DescendanteCalculButton(rid),
        )
    else:
        confirm = await ctx.send(
            confirm_message_content(session),
            view=GameCalculButton(rid),
        )
    session.confirm_message_id = confirm.id
