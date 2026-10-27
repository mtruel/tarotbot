# Séparer l'environnement de debug de la prod

## Status

accepted

## Context

Le site public `tarot-imb.beta.public.truel.fr` et la prod partagent le même `docker-compose.yml`, le même conteneur `tarot-web` et le même volume `./data`. Toute évolution testée « en bêta » écrit donc dans les données réelles et peut casser la prod. Nous voulons un environnement de debug isolé, avec des données factices, une console de commandes et un bandeau visible.

## Decision

L'environnement de debug est une stack Compose distincte (`docker-compose.debug.yml`, projet `tarotbot-debug`) qui tourne depuis un second worktree git (`~/tarotbot-debug`) sur la branche de feature. Elle comprend deux services : un faux bot (`tarotbot`) qui importe `tarot_commands`, sert `/state`, `/commit` et `/debug/command`, et n'ouvre aucune connexion Discord ; et le web habituel (`tarot-web-debug`) avec `TAROT_DEBUG=1`, authentification contournée, bandeau debug et console de commandes. Les données viennent d'une fixture versionnée copiée dans `./data-debug`, réinitialisable depuis le bandeau. L'accès est LAN-only via `tarotbot-imb.beta.local.truel.fr`, routé par Caddy bêta vers `tarot-web-debug:8080`.

## Considered Options

- **Bot Discord réel de test** : plus fidèle, mais second token, second serveur, risque d'écriture réelle et configuration OAuth supplémentaire. Rejeté : le debug doit tester le code, pas l'intégration Discord.
- **Un seul checkout avec une branche** : simple, mais un `docker compose up --build` depuis une branche de feature reconstruit la prod. Rejeté au profit des worktrees.
- **Un seul conteneur debug** : plus simple à opérer, mais ne teste pas le chemin HTTP web → bot et mélange les responsabilités. Rejeté.
- **Snapshot de prod anonymisé** : plus réaliste, mais risque de fuite et plus de code. Rejeté au profit d'une fixture déterministe.

## Consequences

- La prod ne se déploie plus que depuis `~/tarotbot` sur `main` ; le développement courant se fait dans `~/tarotbot-debug`.
- Le code de debug vit dans `tarot_debug/` et `debug_bot.py`, avec des points d'extension dans `tarot_web` gardés par `TAROT_DEBUG` et un paramètre `channel_type` dans `internal_api` (défaut : `discord.TextChannel`).
- Le faux bot doit simuler les boutons, les menus et `wait_for` pour que la console rejoue les vraies commandes.
- Les commandes `t/restore`, `t/new_season`, `t/export` et `t/curves` restent hors console (restic/rclone/fichiers).
- Le home lab doit ajouter une route Caddy bêta, un libellé d'index et la doc associée.
