# Sauvegarde et restauration

## Ce qui est sauvegardé

Chaque jour à **3 h, heure de Paris**, Supercronic, lancé dans le conteneur du bot, déclenche un snapshot restic de `data/` : données courantes et dossiers de saisons archivées. Si le conteneur est arrêté à cette heure, aucun rattrapage n'est prévu dans le dépôt.

La sauvegarde exclut `config.json`, `.env`, `token.json`, `curves.png`, les dossiers `restic` et `restore`, ainsi que les fichiers `*.tmp`. Conserver séparément et de façon sécurisée la configuration, les secrets, le mot de passe restic et les accès Google Drive : les snapshots seuls ne suffisent pas à reconstruire l'installation.

Le dépôt local est par défaut `data/restic` (`/data/restic` dans le conteneur). Il est chiffré par restic mais se trouve sur le même stockage que les données : ce n'est pas une sauvegarde hors site. La tâche copie les snapshots dans un second dépôt restic sur Google Drive, puis y dépose `tarotbot-latest.zip`, un export lisible **non chiffré par restic**, écrasé à chaque sauvegarde. Protéger l'accès Drive en conséquence.

La copie restic est additive, mais la rétention s'applique séparément aux deux dépôts et peut supprimer des snapshots distants. Par défaut : tous les snapshots pendant 30 jours, puis le plus récent par semaine pendant 183 jours supplémentaires, puis le plus récent par mois sans limite. Le nettoyage lourd (`prune`) sur Drive a lieu le dimanche par défaut.

## Configuration

Dans le `.env` de prod, configurer le remote rclone `gdrive` avec `RCLONE_CONFIG_GDRIVE_TYPE`, `RCLONE_CONFIG_GDRIVE_SCOPE`, `RCLONE_CONFIG_GDRIVE_ROOT_FOLDER_ID` et `RCLONE_CONFIG_GDRIVE_TOKEN` ; le [README](../README.md#configuration) décrit l'obtention du token. `BACKUP_DEST_PATH` choisit le sous-dossier Drive (défaut `TarotBot`), `RESTIC_REPOSITORY` le dépôt local, et `BACKUP_SRC_DIR` la source.

**Définir un mot de passe restic fort et le conserver séparément** : le mot de passe par défaut est public dans le code et n'assure donc pas une confidentialité utile. `RESTIC_PASSWORD` configure le secret. Les variantes `RESTIC_PASSWORD_FILE` et `RESTIC_PASSWORD_COMMAND` existent, mais en cas de copie entre dépôts, elles nécessitent aussi une configuration correcte de `RESTIC_FROM_PASSWORD_FILE` ou `RESTIC_FROM_PASSWORD_COMMAND` ; sinon le code peut utiliser le mot de passe par défaut pour la source. Tester la copie et la lecture des deux dépôts après toute modification. Changer une variable ne change pas la clé d'un dépôt existant : prévoir une migration de clé pour chaque dépôt et conserver l'ancien secret jusqu'à vérification.

La rétention se règle avec `BACKUP_KEEP_RECENT_DAYS`, `BACKUP_KEEP_WEEKLY_DAYS` et `BACKUP_REMOTE_PRUNE_WEEKDAY` (0 = lundi, 6 = dimanche). Les chemins et secrets doivent correspondre à la configuration réellement utilisée lors de la sauvegarde.

## Déclencher et contrôler

Depuis la racine du checkout de prod :

```bash
./run_backup.sh
# Ou, si le conteneur tourne :
docker compose exec tarotbot /usr/local/bin/backup.sh
# Consulter les résultats et avertissements :
docker compose logs --tail=100 tarotbot
```

`run_backup.sh` lance un conteneur jetable ; sa sortie apparaît dans le terminal, pas nécessairement dans les logs du service. Rechercher les messages de création du snapshot, de copie Drive et de dépôt du ZIP. **Un succès local ou un code de sortie nul ne prouve pas le succès Drive** : les erreurs de copie distante ou d'envoi du ZIP peuvent être affichées comme avertissements sans faire échouer la commande.

Pour inspecter les snapshots, depuis le conteneur en cours d'exécution :

```bash
docker compose exec tarotbot python -c 'from tarot_commands.backup_lib import snapshots; print(*snapshots(), sep="\n")'
docker compose exec tarotbot python -c 'from tarot_commands.backup_lib import snapshots, remote_repo; print(*snapshots(remote_repo()), sep="\n")'
```

Comparer les dates des snapshots aux sauvegardes attendues et vérifier périodiquement qu'une restauration en environnement isolé est possible. Le dépôt ne contient pas de contrôle `restic check` ni d'exercice de restauration complète planifié. Ne pas conclure à la réussite de la copie hors site sans la vérifier.

## Exports Discord

- `t/export` envoie un ZIP des données et saisons archivées, sans les secrets exclus ni le dépôt restic.
- `t/export backup` crée un snapshot et un ZIP du dépôt restic local, puis lance une copie Drive en arrière-plan. Ce n'est pas le même flux que la tâche planifiée : il ne garantit pas la création du dépôt distant, sa rotation ni l'envoi du ZIP `tarotbot-latest.zip`.

Un ZIP du dépôt restic contient le dépôt chiffré, pas directement les fichiers de saison ; il faut l'ouvrir avec restic et le mot de passe correspondant. Les exports Discord sont soumis à une limite de taille.

## Restaurer la saison courante

**Opération destructive.** Choisir d'abord la source et faire une copie indépendante de l'état courant, même s'il semble endommagé. La restauration ne réécrit que `history.json` et `players.json` ; elle ne restaure ni les saisons archivées ni les secrets. Le fichier `history.json` est obligatoire ; si `players.json` manque, les noms sont reconstruits depuis l'historique. Les données sont validées avant écriture, et une copie des fichiers précédents est conservée dans `data/_pre_restore_<horodatage>/` (10 dossiers au maximum). Les remplacements sont atomiques par fichier, pas pour l'ensemble des deux fichiers.

### Depuis l'hôte

Depuis `~/tarotbot`, avec une archive ZIP de données accessible sur l'hôte ou un snapshot du **dépôt local** :

```bash
./run_restore.sh ecraser_saison_en_cours /chemin/vers/backup.zip
# Ou le dernier snapshot local :
./run_restore.sh ecraser_saison_en_cours backup
# Ou un snapshot local précis :
./run_restore.sh ecraser_saison_en_cours <id-snapshot>
```

Le script arrête le bot, restaure dans un conteneur jetable et appelle `docker compose up -d` à la sortie, **même en cas d'échec** ; cette commande peut démarrer tous les services de la stack. Vérifier le résultat, `docker compose ps`, les logs et les données restaurées avant de reprendre l'utilisation.

### Depuis Discord

Réservé aux administrateurs : envoyer `t/restore IAMSURE` avec un ZIP de données joint, ou `t/restore IAMSURE backup` pour le dernier snapshot local. Après validation de la source, le bot joint un export de l'état courant et demande la confirmation exacte `ecraser_saison_en_cours` ; répondre `non` pour annuler. Le bot restant actif pendant cette procédure, éviter toute saisie concurrente.

## Si le dépôt local est perdu

Le dépôt Drive est indépendant. Depuis un conteneur bot en cours d'exécution, avec la configuration Drive et le mot de passe du dépôt distant, lister ses snapshots puis restaurer **d'abord dans un dossier de travail**, sans écraser `data/` :

```bash
docker compose exec tarotbot restic -r rclone:gdrive:TarotBot/restic snapshots
docker compose exec tarotbot restic -r rclone:gdrive:TarotBot/restic restore latest --target /data/restore/inspection
```

Remplacer `TarotBot` par la valeur effective de `BACKUP_DEST_PATH` et `latest` par l'identifiant choisi si nécessaire. Le client restic doit disposer du bon mot de passe via l'environnement configuré ou le demander de manière interactive ; ne pas le placer dans une commande enregistrée dans l'historique du shell. Le dossier `/data/restore/inspection` correspond à `./data/restore/inspection` sur l'hôte et est exclu des sauvegardes. Inspecter les fichiers extraits et leur arborescence avant toute reprise.

Pour la saison courante, préparer un ZIP de données contenant le `history.json` sélectionné et, si disponible, son `players.json`. Par exemple, si ces fichiers se trouvent directement dans `./data/restore/inspection`, depuis la racine du dépôt :

```bash
(cd data/restore/inspection && python3 -m zipfile -c ../saison-courante.zip history.json players.json)
./run_restore.sh ecraser_saison_en_cours data/restore/saison-courante.zip
```

Adapter le dossier aux fichiers effectivement extraits ; si `players.json` est absent, l'omettre de la commande ZIP. La restauration automatique n'importe pas les archives de saisons : leur remise en place nécessite une intervention manuelle distincte, après arrêt du bot, copie de sécurité, contrôle des noms et permissions, et sans écraser des archives existantes par inadvertance. Vérifier ensuite les données et redémarrer la stack.
