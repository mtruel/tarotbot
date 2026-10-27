# TarotBot

Lexique des termes utilisés pour décrire les parties de tarot et leur saisie dans le bot.

## Parties et saisies

**Preneur** : Joueur qui annonce l’enchère et prend le contrat. Il est toujours placé avant l’enchère.
_Avoid_: Attaquant, joueur qui attaque

**Attaque** : Équipe formée du preneur et, lorsqu’il y en a un, de son partenaire.
_Avoid_: Preneur seul

**Défense** : Équipe des joueurs qui ne font pas partie de l’attaque.
_Avoid_: Défenseurs, lorsqu’il s’agit de désigner l’équipe entière

**Partenaire** : Joueur appelé par le preneur pour former l’attaque dans une partie à cinq joueurs. Dans une commande texte, il est indiqué par `avec` ou `with`.
_Avoid_: Appelé, coéquipier

**Réponse de saisie** : Message du bot associé à une commande de partie ; il présente soit une erreur de saisie, soit un récapitulatif à valider.
_Avoid_: Confirmation, lorsqu’il est question du message avant validation

**Joueur inconnu** : Nom qui ne correspond à aucun joueur du classement.
_Avoid_: Joueur invalide

## Environnements

**Prod** : Environnement de référence, avec le bot Discord réel et les données réelles.
_Avoid_: Production, live

**Environnement de debug** : Environnement isolé pour tester une évolution avant la prod, avec un bot simulé et des données factices.
_Avoid_: Version de test, bac à sable, staging

**Données factices** : Jeu de données versionné qui remplace les données réelles dans l'environnement de debug.
_Avoid_: Données de test, mock data

**Console de commandes** : Page de l'environnement de debug qui rejoue les commandes Discord et affiche leurs réponses.
_Avoid_: Page chat, chat de test
