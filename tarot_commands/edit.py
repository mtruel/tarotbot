"""Commande t/edit : ecraser une partie enregistree via un nouveau parse t/auto."""

from __future__ import annotations

import discord
from discord.ext import commands

from tarot_commands.game import (
    EXPIRED_MSG,
    ParseError,
    _bind_calcul_view,
    _expire_calcul_view,
    autoparse,
    confirm_message_content,
    descendante_details,
    finalize_descendante_scores,
    finalize_partie_scores,
    partie_details,
    send_score_table,
)
from tarot_commands.help import error_message
from tarot_commands.history import replace_history_entry
from tarot_commands.sessions import (
    create_session,
    find_history_by_message_id,
    get_session,
    pop_session,
    temp_session,
)
from tarot_commands.state import load_history


def is_snowflake_token(token: str) -> bool:
    return token.isdigit() and 17 <= len(token) <= 20


def strip_optional_auto_prefix(body: str) -> str:
    """Accepte un corps nu ou prefixe par t/auto."""
    text = (body or "").strip()
    if not text.lower().startswith("t/"):
        return text
    rest = text[2:].lstrip()
    parts = rest.split(None, 1)
    if not parts or parts[0].lower() != "auto":
        return text
    return parts[1] if len(parts) > 1 else ""


def resolve_edit_target(content: str, reference_message_id: int | None):
    """Resout (target_id, corps_auto) ou (None, None) si usage invalide.

    Priorite a un id numerique explicite s'il est present (meme avec une reponse).
    """
    text = (content or "").strip()
    if not text and reference_message_id is None:
        return None, None

    parts = text.split(None, 1) if text else []
    if parts and is_snowflake_token(parts[0]):
        target = int(parts[0])
        body = parts[1] if len(parts) > 1 else ""
        return target, strip_optional_auto_prefix(body)

    if reference_message_id is not None:
        return reference_message_id, strip_optional_auto_prefix(text)

    return None, None


def extract_edit_body(content: str, fallback_target_id: int | None):
    """Retourne le corps auto d'un message t/edit, ou None si ce n'est pas t/edit.

    La cible explicite dans le texte est ignoree pour le re-parse : on utilise
    fallback_target_id (session.edit_target_message_id) pour extraire le corps
    en mode reponse.
    """
    if not content:
        return None
    text = content.strip()
    if not text.lower().startswith("t/"):
        return None
    rest = text[2:].lstrip()
    parts = rest.split(None, 1)
    if not parts or parts[0].lower() != "edit":
        return None
    after_edit = parts[1] if len(parts) > 1 else ""
    _target, body = resolve_edit_target(after_edit, fallback_target_id)
    if _target is None and fallback_target_id is None:
        return None
    return body


def handle_edit_message_edit(message_id: int, new_content: str, author_id: int):
    """Re-parse un message t/edit encore pending.

    Returns
    -------
    (action, payload)
        action in {'noop', 'updated', 'error', 'ignore'}
        payload : session mise a jour, message d'erreur, ou None
    """
    session = get_session(message_id)
    if session is None or session.source != "edit":
        return "ignore", None
    if session.author_id is not None and author_id != session.author_id:
        return "ignore", None

    body = extract_edit_body(new_content, session.edit_target_message_id)
    if body is None:
        return "ignore", None
    if not body.strip():
        return "error", (
            "Il manque le nouveau contenu (comme après `t/auto`). "
            f"Exemple : `t/edit {session.edit_target_message_id} Alice garde 50 2 vs Bob Carol`"
        )

    trial = temp_session()
    try:
        new_reparse = autoparse(body, trial)
    except ParseError as e:
        return "error", e.args[0]
    if new_reparse == session.reparse:
        return "noop", None
    session.copy_parse_from(trial)
    return "updated", session


class EditOverwriteButton(discord.ui.View):
    def __init__(self, request_message_id, *, timeout=180):
        super().__init__(timeout=timeout)
        self.request_message_id = request_message_id
        self.view_generation = 0
        session = get_session(request_message_id)
        if session is not None:
            _bind_calcul_view(session, self)

    async def on_timeout(self):
        await _expire_calcul_view(self)

    @discord.ui.button(label="Écraser", style=discord.ButtonStyle.danger)
    async def ecraser(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = get_session(self.request_message_id)
        if session is None:
            await interaction.response.send_message(EXPIRED_MSG)
            return

        target_id = session.edit_target_message_id
        if target_id is None:
            await interaction.response.send_message(EXPIRED_MSG)
            return

        history = load_history()
        entry = find_history_by_message_id(history, target_id)
        if entry is None:
            pop_session(self.request_message_id)
            await interaction.response.send_message(
                error_message(
                    "edit",
                    f"Aucune partie avec l’id `{target_id}` (peut-être déjà annulée).",
                )
            )
            return

        if session.kind == "descendante" or session.reparse.startswith("Descendante:\n"):
            scores, err = finalize_descendante_scores(session)
            details = descendante_details(session)
        else:
            scores, err = finalize_partie_scores(session)
            details = partie_details(session)

        if err:
            await interaction.response.send_message(err)
            return

        game_id = entry.get("message_id", target_id)
        replaced = replace_history_entry(target_id, scores, details)
        if replaced is None:
            pop_session(self.request_message_id)
            await interaction.response.send_message(
                error_message(
                    "edit",
                    f"Aucune partie avec l’id `{target_id}` (peut-être déjà annulée).",
                )
            )
            return

        button.disabled = True
        pop_session(self.request_message_id)
        await interaction.response.edit_message(view=self)
        await send_score_table(interaction, scores, game_id)


@commands.command()
async def edit(ctx, *, value: str = ""):
    """Ecrase une partie existante avec un nouveau parse t/auto.

    Usage :
    - t/edit <id> <corps auto>
    - en reponse a un message lie : t/edit <corps auto>
    """
    reference_id = None
    if ctx.message.reference is not None:
        reference_id = ctx.message.reference.message_id

    target_id, body = resolve_edit_target(value, reference_id)
    if target_id is None:
        await ctx.send(
            error_message(
                "edit",
                "Indique l’id de la partie, ou réponds au message (commande / tableau).\n"
                "Exemples : `t/edit 1557730091864301699 Alice garde 50 2 vs Bob Carol`\n"
                "ou en réponse : `t/edit Alice garde 50 2 vs Bob Carol`",
            )
        )
        return

    if not body.strip():
        await ctx.send(
            error_message(
                "edit",
                "Il manque le nouveau contenu (comme après `t/auto`). "
                f"Exemple : `t/edit {target_id} Alice garde 50 2 vs Bob Carol`",
            )
        )
        return

    history = load_history()
    entry = find_history_by_message_id(history, target_id)
    if entry is None:
        await ctx.send(
            error_message(
                "edit",
                f"Aucune partie liée à l’id `{target_id}`.",
            )
        )
        return

    rid = ctx.message.id
    session = create_session(
        rid,
        channel_id=ctx.channel.id,
        author_id=ctx.author.id,
        source="edit",
    )
    session.edit_target_message_id = entry.get("message_id", target_id)

    try:
        autoparse(body, session)
    except ParseError as e:
        pop_session(rid)
        await ctx.send(error_message("edit", e.args[0]))
        return

    confirm = await ctx.send(
        confirm_message_content(session),
        view=EditOverwriteButton(rid),
    )
    session.confirm_message_id = confirm.id
