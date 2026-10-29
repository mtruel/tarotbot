# Déploiement et exploitation

## Environnements

| | Debug | Prod |
|---|---|---|
| Checkout | `~/tarotbot-debug`, branche de travail | `~/tarotbot`, branche `main` |
| Compose | `docker-compose.debug.yml` | `docker-compose.yml` |
| Données | `./data-debug`, factices | `./data`, réelles |
| Bot | Faux bot, sans connexion Discord | Bot Discord réel |
| Web | `https://tarotbot-imb.beta.local.truel.fr`, accès LAN | `tarot-imb.beta.public.truel.fr` utilise les données de prod |

La bêta publique n'est **pas** une préproduction isolée. La décision et les limites de l'environnement de debug sont décrites dans [l'ADR](adr/0001-separer-environnement-debug-de-la-prod.md).

## Prérequis

- Docker et Docker Compose ; le réseau Docker externe `beta` doit exister et le reverse proxy doit être configuré séparément. Le dépôt ne configure pas le proxy.
- Pour la prod, `./data` doit être accessible en écriture à l'UID/GID 1000. Ne pas remplacer ce dossier par les données de debug.
- Un `.env` de prod hors Git, basé sur [`.env.example`](../.env.example), avec `DISCORD_TOKEN`, `TAROT_CHANNEL_ID`, `TAROT_INTERNAL_TOKEN`, `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, `DISCORD_OAUTH_REDIRECT_URI`, `DISCORD_GUILD_ID` et `WEB_SESSION_SECRET`. Le token interne doit être identique pour les deux services et comporter au moins 32 caractères ; `TAROT_CHANNEL_ID` doit être un identifiant de salon numérique valide. L'intent Discord **Message Content** doit être activé.
- Les identifiants de sauvegarde sont également fournis via `.env` ; voir [Sauvegarde et restauration](sauvegarde-restauration.md). Ne pas mettre de secrets dans Git ou dans l'image.

Le bot reçoit `.env` via `env_file` ; Compose utilise aussi ses variables pour interpoler la configuration du service web. Le repli `data/config.json` pour le token du bot est déprécié et n'est pas sauvegardé.

## Validation en debug

Depuis le worktree `~/tarotbot-debug` :

```bash
mkdir -p data-debug
# Vérifier que data-debug appartient à l'UID 1000.
docker compose -f docker-compose.debug.yml up -d --build
docker compose -f docker-compose.debug.yml ps
docker compose -f docker-compose.debug.yml logs -f tarotbot tarot-web-debug
```

Ouvrir `https://tarotbot-imb.beta.local.truel.fr` dans un navigateur et utiliser « Se connecter au mode debug » sur la page de connexion. Le lien `/auth/discord` crée une session fictive localement, sans contacter Discord. Après déconnexion, la page de connexion permet de se reconnecter. Les sessions web et aperçus des navigateurs sont isolés : se déconnecter dans l'un n'affecte pas les autres. La console du faux bot reste partagée entre les navigateurs. Cette connexion fictive n'est pas une protection par mot de passe : l'accès reste réservé au réseau local.

Vérifier le bandeau de debug et les parcours concernés, y compris `/debug/chat` si pertinent. La fixture comprend 30 joueurs fictifs, dont cinq noms longs consécutifs pour tester l'affichage. Le bandeau est replié par défaut : cliquer sur « MODE DEBUG » pour accéder à la console, aux informations et à la réinitialisation des données issues d'une fixture. La réinitialisation remplace les parties et joueurs de debug en cours pour tous les utilisateurs de cet environnement. Ne pas définir `DISCORD_TOKEN` dans cette stack et ne jamais y copier les données de prod. Certaines commandes liées aux fichiers ne sont pas disponibles dans la console ; une validation debug ne prouve pas le fonctionnement de Discord réel ni de la connexion OAuth de prod.

Pour recharger les modifications pendant le développement, suivre le [guide de surveillance en debug](watch-debug.md), qui précise les prérequis et les effets des redémarrages.

Arrêt :

```bash
docker compose -f docker-compose.debug.yml down
```

## Mise en production

1. Avant le merge, exécuter les vérifications décrites dans [Architecture](architecture.md#développement-et-tests) et valider la fonctionnalité en debug.
2. Avant une opération qui modifie les données, vérifier qu'une sauvegarde exploitable existe et connaître la [procédure de restauration](sauvegarde-restauration.md). Au démarrage, le bot peut également migrer l'état.
3. Merger la branche validée dans `main`. Depuis `~/tarotbot`, vérifier la branche et l'état du checkout, puis déployer :

```bash
git status --short --branch
git pull
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 tarotbot tarot-web
```

4. Vérifier que le bot est connecté, que le site et le parcours modifié fonctionnent, et que les logs ne signalent pas d'erreurs. `depends_on` ne garantit pas que le bot soit prêt quand le web démarre. Pour suivre les logs : `docker compose logs -f tarotbot tarot-web`.

Pour arrêter la stack : `docker compose down`. Cela n'efface pas le bind mount `./data`. Ne pas lancer `bot.py` ou `debug_bot.py` directement.

## En cas d'échec

Consulter d'abord `docker compose ps` et les logs des deux services. Vérifier les variables requises, le réseau externe et les droits de `data/` sans exposer les secrets. Si une migration ou une opération a modifié les données, revenir à une ancienne image ou à un ancien commit ne restaure pas ces données : évaluer séparément la restauration depuis une sauvegarde. Éviter tout retour arrière Git destructif sur un checkout contenant des modifications non sauvegardées.
