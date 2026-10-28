# Surveillance en debug

Depuis le worktree dédié `~/tarotbot-debug`, démarrer la stack puis lancer la surveillance dans un terminal séparé (Docker Compose 2.32 ou supérieur) :

```bash
mkdir -p data-debug
# Vérifier que data-debug appartient à l'UID 1000.
docker compose -f docker-compose.debug.yml up -d --build
docker compose -f docker-compose.debug.yml watch --no-up
```

Les sources sont montées en lecture seule depuis ce worktree. Les changements dans `tarot_commands/`, `tarot_debug/` et les fichiers Python de `tarot_web/` redémarrent les services concernés ; ceux de `debug_bot.py` reconstruisent le faux bot. Les templates, CSS et JavaScript sont relus sans redémarrage : actualiser le navigateur pour les voir (au besoin, forcer l'actualisation). Le navigateur ne se recharge pas automatiquement. Le bandeau « MODE DEBUG » est replié par défaut ; cliquer dessus pour accéder à la console et à la réinitialisation des données.

Les redémarrages interrompent les requêtes en cours et effacent l'état en mémoire de la console ; les données factices sur disque restent intactes. Arrêter la surveillance avec Ctrl+C : les conteneurs continuent de tourner. Sans surveillance, les changements Python montés nécessitent un redémarrage manuel du service concerné.

Après modification du `Dockerfile`, de `pyproject.toml`, de `uv.lock` ou de la configuration Compose, relancer `docker compose -f docker-compose.debug.yml up -d --build`, puis redémarrer la surveillance. Ne pas définir `DISCORD_TOKEN` et ne jamais copier de données de production dans cette stack.
