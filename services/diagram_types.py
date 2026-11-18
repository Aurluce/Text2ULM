"""Catalogue des types de diagrammes : libellés, règles de prompt, exemples, statistiques."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple, Type

from models.uml_model import (
    ActivityModel,
    BaseDiagram,
    ComponentModel,
    ERModel,
    SequenceModel,
    StateModel,
    UMLModel,
    UseCaseModel,
)

Stats = Callable[[BaseDiagram], List[Tuple[str, int]]]


@dataclass(frozen=True)
class DiagramType:
    key: str
    label: str
    icon: str
    description: str
    model: Type[BaseDiagram]
    schema_example: str      # structure JSON montrée au LLM
    rules: str               # règles propres à ce type
    detailed_extra: str      # consigne supplémentaire au niveau « Détaillé »
    examples: Dict[str, str]  # exemples de descriptions proposés dans l'interface
    stats: Stats


# --------------------------------------------------------------------------- #
# Diagramme de classes
# --------------------------------------------------------------------------- #
CLASS = DiagramType(
    key="class",
    label="Diagramme de classes",
    icon="",
    description="Structure statique : classes, attributs, héritage, compositions et cardinalités.",
    model=UMLModel,
    schema_example='''{"title":"Gestion des candidatures","classes":[{"name":"Utilisateur","kind":"abstract","attributes":["id: int","nom: string"],"methods":["seConnecter()"]},{"name":"Candidat","attributes":["telephone: string"]},{"name":"Candidature","attributes":["dateSoumission: date","statut: StatutCandidature"]},{"name":"StatutCandidature","kind":"enumeration","attributes":["EN_ATTENTE","ACCEPTEE","REFUSEE"]}],"relations":[{"source":"Candidat","target":"Utilisateur","type":"inheritance"},{"source":"Candidat","target":"Candidature","type":"association","source_cardinality":"1","target_cardinality":"*","label":"soumet"},{"source":"Candidature","target":"StatutCandidature","type":"dependency"}],"assumptions":["Un candidat peut exister sans avoir postulé."]}''',
    rules='''- Noms de classes au singulier, en PascalCase, sans espaces. Attributs au format "nom: type" (int, string, float, bool, date, datetime).
- "kind" vaut class, abstract, interface ou enumeration. Pour une énumération, "attributes" contient ses valeurs.
- Types de relation : association, inheritance, composition, aggregation, dependency, realization.
- inheritance et realization : "source" est la classe enfant (ou qui implémente), "target" la classe parente (ou l'interface). Ne mets pas de cardinalités.
- composition et aggregation : "source" est le tout, "target" la partie.
- Cardinalités possibles : "1", "0..1", "*", "1..*", "0..*". Uniquement pour association, composition et aggregation.
- Une relation plusieurs-à-plusieurs qui porte des attributs devient une classe intermédiaire (classe d'association).
- Chaque classe citée dans une relation doit exister dans "classes".''',
    detailed_extra="Ajoute les méthodes principales (\"methods\") de chaque classe métier, avec leurs paramètres.",
    examples={
        "Candidatures (simple)": "Un candidat soumet plusieurs candidatures. Une offre d'emploi reçoit plusieurs candidatures. Une candidature a une date de soumission et un statut (en attente, acceptée, refusée). Un candidat a un nom, un email et un téléphone. Une offre a un titre, une description et une date limite.",
        "Bibliothèque (héritage)": "Une bibliothèque gère des documents. Un document a un titre, un auteur et une année de publication. Livre et Revue sont des types de document : un livre a un ISBN, une revue a un numéro. Un membre a un nom et un email, et emprunte des documents. Chaque emprunt a une date de sortie et une date de retour prévue. Un membre ne peut pas avoir plus de cinq emprunts en cours.",
        "Plateforme de recrutement (complexe)": "Une plateforme de recrutement en ligne. Un Utilisateur a un id, un nom, un email et une dateInscription. Candidat, Recruteur et Administrateur sont des types d'Utilisateur. Un Candidat a un telephone, une ville et une disponibilité. Un Recruteur a un poste. Un Administrateur a un niveauAcces.\n\nUne Entreprise a un nom, un secteur, un siteWeb et une ville ; elle emploie plusieurs Recruteurs. Un Recruteur publie plusieurs Offres. Une Offre a un titre, une description, un typeContrat (CDI, CDD, STAGE), un salaire, une dateLimite et un statut (OUVERTE, FERMEE). Une Offre requiert plusieurs Competences ; une Competence peut être requise par plusieurs Offres. Un Candidat possède plusieurs Competences avec un niveau.\n\nUn Candidat possède un seul CV (fichierUrl, dateMiseAJour, resume). Un CV contient des Experiences (poste, employeur, dateDebut, dateFin) et des Formations (diplome, etablissement, anneeObtention) : elles n'existent pas sans le CV.\n\nUn Candidat soumet plusieurs Candidatures. Une Offre reçoit plusieurs Candidatures. Une Candidature a une dateSoumission, une lettreMotivation, un scoreMatching et un statut (EN_ATTENTE, PRESELECTIONNEE, ENTRETIEN, ACCEPTEE, REFUSEE). Une Candidature peut donner lieu à plusieurs Entretiens (date, duree, lieu, mode PRESENTIEL ou VISIO). Un Entretien est mené par un Recruteur et produit une Evaluation (note, commentaire, decision). Un Utilisateur reçoit plusieurs Notifications (message, dateEnvoi, estLue).",
    },
    stats=lambda m: [("Classes", len(m.classes)), ("Relations", len(m.relations))],
)

# --------------------------------------------------------------------------- #
# Modèle entité-association
# --------------------------------------------------------------------------- #
ER = DiagramType(
    key="er",
    label="Modèle entité-association (tables)",
    icon="",
    description="Schéma de base de données : tables, clés primaires et étrangères, cardinalités.",
    model=ERModel,
    schema_example='''{"title":"Bibliothèque","entities":[{"name":"Livre","attributes":[{"name":"id","type":"int","primary_key":true},{"name":"titre","type":"string","required":true},{"name":"auteur_id","type":"int","foreign_key":true}]},{"name":"Auteur","attributes":[{"name":"id","type":"int","primary_key":true},{"name":"nom","type":"string"}]}],"relations":[{"source":"Auteur","target":"Livre","source_cardinality":"1","target_cardinality":"0..*","label":"écrit"}],"assumptions":[]}''',
    rules='''- Une entité = une table ; son nom est au singulier. Les attributs sont en snake_case avec leur type (int, string, float, bool, date, datetime).
- Chaque entité a une clé primaire ("primary_key": true), en général "id", sauf indication contraire.
- Pour une relation un-à-plusieurs, ajoute la clé étrangère ("foreign_key": true) dans l'entité du côté « plusieurs ».
- Une relation plusieurs-à-plusieurs devient une entité de jonction avec deux clés étrangères (et ses éventuels attributs propres), reliée aux deux entités par deux relations un-à-plusieurs.
- Cardinalités possibles : "1", "0..1", "*" (zéro ou plusieurs), "1..*". "source_cardinality" est le nombre de "source" par "target", et inversement.
- Chaque entité citée dans une relation doit exister dans "entities".''',
    detailed_extra="Ajoute les colonnes d'audit utiles (created_at, updated_at) et les attributs d'unicité évidents.",
    examples={
        "Bibliothèque": "Une bibliothèque possède des livres. Chaque livre a un titre, un ISBN unique et une année. Un livre est écrit par un ou plusieurs auteurs, et un auteur peut écrire plusieurs livres. Les membres ont un nom, un email et une date d'inscription. Un membre emprunte des livres : chaque emprunt a une date de sortie, une date de retour prévue et une date de retour effective.",
        "Boutique en ligne": "Une boutique en ligne vend des produits (nom, prix, stock) classés dans une catégorie. Un client (nom, email, adresse) passe des commandes. Une commande a une date, un statut et un total, et contient plusieurs lignes de commande (produit, quantité, prix unitaire). Chaque commande est réglée par un paiement (montant, méthode, date).",
    },
    stats=lambda m: [("Tables", len(m.entities)), ("Relations", len(m.relations))],
)

# --------------------------------------------------------------------------- #
# Cas d'utilisation
# --------------------------------------------------------------------------- #
USECASE = DiagramType(
    key="usecase",
    label="Diagramme de cas d'utilisation",
    icon="",
    description="Fonctionnalités vues par les utilisateurs : acteurs, cas d'utilisation, include et extend.",
    model=UseCaseModel,
    schema_example='''{"title":"Bibliothèque","system_name":"Système de bibliothèque","actors":[{"name":"Lecteur","kind":"human"},{"name":"Système de paiement","kind":"system"}],"use_cases":[{"name":"Emprunter un livre"},{"name":"Vérifier l'abonnement"},{"name":"Payer une pénalité"}],"relations":[{"source":"Lecteur","target":"Emprunter un livre","type":"association"},{"source":"Emprunter un livre","target":"Vérifier l'abonnement","type":"include"},{"source":"Payer une pénalité","target":"Emprunter un livre","type":"extend"},{"source":"Système de paiement","target":"Payer une pénalité","type":"association"}],"assumptions":[]}''',
    rules='''- Un acteur est un rôle ou un système externe ("kind" : human ou system). Un cas d'utilisation est un verbe à l'infinitif + complément.
- Types de relation : association (acteur ↔ cas d'utilisation), include, extend, generalization.
- include : "source" est le cas de base, "target" le cas inclus (obligatoire). extend : "source" est le cas qui étend, "target" le cas de base (optionnel).
- generalization : "source" est l'enfant, "target" le parent (entre deux acteurs ou deux cas d'utilisation).
- Pas d'association directe entre deux cas d'utilisation. "system_name" est le nom du système (la frontière).
- Chaque acteur et chaque cas d'utilisation cité dans une relation doit être déclaré.''',
    detailed_extra="Ajoute les cas d'utilisation d'administration et de gestion d'erreurs qui découlent clairement du texte.",
    examples={
        "Bibliothèque universitaire": "Un étudiant peut rechercher un livre, emprunter un livre et réserver un livre. Emprunter un livre nécessite de vérifier l'abonnement de l'étudiant. Si le livre est en retard, l'étudiant peut payer une pénalité. Le bibliothécaire gère le catalogue et enregistre les retours. L'administrateur gère les comptes et peut faire tout ce que fait le bibliothécaire.",
        "Boutique en ligne": "Un client parcourt le catalogue, ajoute des produits au panier et passe une commande. Passer une commande inclut le paiement en ligne, réalisé avec un service de paiement externe. Le client peut aussi appliquer un code promo, de façon optionnelle. Le gestionnaire met à jour les stocks et traite les commandes. Un client connecté peut suivre ses commandes.",
    },
    stats=lambda m: [("Acteurs", len(m.actors)), ("Cas d'utilisation", len(m.use_cases)), ("Relations", len(m.relations))],
)

# --------------------------------------------------------------------------- #
# Séquence
# --------------------------------------------------------------------------- #
SEQUENCE = DiagramType(
    key="sequence",
    label="Diagramme de séquence",
    icon="",
    description="Échanges de messages dans le temps entre acteurs et composants, avec alternatives et boucles.",
    model=SequenceModel,
    schema_example='''{"title":"Connexion","participants":[{"name":"Utilisateur","kind":"actor"},{"name":"Application","kind":"boundary"},{"name":"Serveur","kind":"control"},{"name":"Base de données","kind":"database"}],"steps":[{"kind":"message","source":"Utilisateur","target":"Application","label":"saisit ses identifiants"},{"kind":"message","source":"Application","target":"Serveur","label":"authentifier(email, mdp)"},{"kind":"message","source":"Serveur","target":"Base de données","label":"chercher l'utilisateur"},{"kind":"group_start","group_type":"alt","label":"identifiants valides"},{"kind":"message","source":"Serveur","target":"Application","label":"jeton","arrow":"return"},{"kind":"group_else","label":"identifiants invalides"},{"kind":"message","source":"Serveur","target":"Application","label":"erreur 401","arrow":"return"},{"kind":"group_end"}],"assumptions":[]}''',
    rules='''- "steps" est la liste chronologique des échanges. Chaque pas a un "kind" : message, group_start, group_else, group_end ou note.
- message : "source", "target", "label" et "arrow" (sync par défaut, async pour un message asynchrone, return pour une réponse).
- Fragments : group_start avec "group_type" (alt, opt, loop, par ou break) et "label" (la condition), puis éventuellement group_else, puis group_end. Chaque group_start doit être fermé par un group_end.
- note : "source" est le participant concerné, "label" le texte.
- Types de participant : actor, participant, boundary (interface), control, entity, database, queue.
- Donne une réponse (arrow "return") aux appels importants. Les noms dans les messages doivent correspondre aux participants.''',
    detailed_extra="Ajoute les cas d'erreur et les réponses de retour implicites, sous forme d'alt.",
    examples={
        "Connexion avec double authentification": "L'utilisateur saisit son email et son mot de passe dans l'application. L'application les envoie au serveur d'authentification, qui vérifie les identifiants dans la base de données. Si les identifiants sont valides, le serveur envoie un code par SMS puis l'utilisateur saisit ce code ; si le code est correct, le serveur renvoie un jeton de session. Sinon, une erreur est renvoyée à l'application, qui l'affiche à l'utilisateur.",
        "Paiement en ligne d'une commande": "Le client valide son panier sur le site. Le site demande la création du paiement au service de paiement externe, qui renvoie une page de confirmation. Le client confirme le paiement. Le service de paiement notifie ensuite le site de façon asynchrone. Le site met à jour la commande en base de données et envoie un email de confirmation au client. En cas de refus, la commande reste en attente.",
    },
    stats=lambda m: [
        ("Participants", len(m.participants)),
        ("Messages", sum(1 for s in m.steps if s.kind == "message")),
    ],
)

# --------------------------------------------------------------------------- #
# Activité
# --------------------------------------------------------------------------- #
ACTIVITY = DiagramType(
    key="activity",
    label="Diagramme d'activité",
    icon="",
    description="Enchaînement d'actions d'un processus : décisions, boucles, traitements parallèles, couloirs.",
    model=ActivityModel,
    schema_example='''{"title":"Traitement d'une commande","steps":[{"kind":"start"},{"kind":"action","label":"Recevoir la commande"},{"kind":"if","label":"Stock disponible ?","branch":"oui"},{"kind":"action","label":"Préparer le colis"},{"kind":"else","label":"non"},{"kind":"action","label":"Prévenir le client du retard"},{"kind":"endif"},{"kind":"fork"},{"kind":"action","label":"Émettre la facture"},{"kind":"fork_again"},{"kind":"action","label":"Expédier le colis"},{"kind":"end_fork"},{"kind":"stop"}],"assumptions":[]}''',
    rules='''- "steps" est une liste à plat, dans l'ordre du processus. Commence par start et termine par stop.
- action : "label" est une action courte (verbe à l'infinitif).
- Décision : if ("label" = la condition, "branch" = étiquette de la branche principale), puis éventuellement else ("label" = étiquette de l'autre branche), puis endif.
- Boucle : while ("label" = la condition de poursuite, "branch" = étiquette), les actions répétées, puis endwhile ("label" = étiquette de sortie).
- Parallélisme : fork, les actions de la première branche, fork_again, les actions de la branche suivante, puis end_fork.
- Couloirs (facultatif) : un pas swimlane ("label" = nom de l'acteur) change le couloir des actions suivantes.
- Tout if, while et fork doit être fermé (endif, endwhile, end_fork). Pas de point-virgule dans les libellés.''',
    detailed_extra="Ajoute les cas d'échec et les boucles de nouvelle tentative qui découlent du texte.",
    examples={
        "Traitement d'une commande": "Une commande est reçue. On vérifie le paiement : s'il est refusé, on annule la commande et on prévient le client. Sinon, on vérifie le stock. Si le stock est insuffisant, on attend le réapprovisionnement puis on revérifie le stock. Quand tout est disponible, on prépare le colis, et en parallèle on émet la facture. Ensuite on expédie le colis et on envoie un email de suivi au client.",
        "Inscription et validation d'un compte": "L'utilisateur remplit le formulaire d'inscription. Le système vérifie que l'email n'est pas déjà utilisé ; si c'est le cas, il affiche une erreur et le processus s'arrête. Sinon, il crée le compte, envoie un email de confirmation et attend le clic de l'utilisateur sur le lien. Si le lien est cliqué dans les 24 heures, le compte est activé ; sinon il est supprimé.",
    },
    stats=lambda m: [
        ("Actions", sum(1 for s in m.steps if s.kind == "action")),
        ("Décisions", sum(1 for s in m.steps if s.kind in ("if", "while"))),
    ],
)

# --------------------------------------------------------------------------- #
# États
# --------------------------------------------------------------------------- #
STATE = DiagramType(
    key="state",
    label="Diagramme d'états",
    icon="",
    description="Cycle de vie d'un objet : états, événements, gardes et actions de transition.",
    model=StateModel,
    schema_example='''{"title":"Cycle de vie d'une commande","states":[{"name":"Brouillon"},{"name":"Payée","description":"paiement confirmé"},{"name":"Expédiée"},{"name":"Annulée"}],"transitions":[{"source":"[*]","target":"Brouillon"},{"source":"Brouillon","target":"Payée","event":"payer","guard":"montant > 0","action":"envoyer le reçu"},{"source":"Payée","target":"Expédiée","event":"expédier"},{"source":"Brouillon","target":"Annulée","event":"annuler"},{"source":"Expédiée","target":"[*]"},{"source":"Annulée","target":"[*]"}],"assumptions":[]}''',
    rules='''- Il s'agit du cycle de vie d'UN seul objet. Les états sont des noms ou des participes (Brouillon, Payée, En cours).
- Utilise "[*]" comme "source" pour l'état initial et comme "target" pour l'état final.
- Chaque transition peut porter un "event" (déclencheur), un "guard" (condition) et une "action" (effet). Ils sont facultatifs.
- Tout état cité dans une transition doit être déclaré dans "states". Pas d'état en double.''',
    detailed_extra="Ajoute les transitions d'erreur, d'annulation et d'expiration qui découlent du texte.",
    examples={
        "Cycle de vie d'une commande": "Une commande est créée à l'état brouillon. Quand le client paie, elle passe à payée. Quand le magasin l'expédie, elle passe à expédiée, puis à livrée à la réception. Un brouillon ou une commande payée peut être annulée ; une commande payée annulée est remboursée avant de passer à l'état annulée. Une commande livrée peut faire l'objet d'un retour dans les 14 jours.",
        "Candidature à une offre": "Une candidature est déposée à l'état « en attente ». Le recruteur peut la présélectionner ou la refuser. Une candidature présélectionnée donne lieu à un entretien ; après l'entretien, elle est soit acceptée soit refusée. Le candidat peut retirer sa candidature tant qu'elle n'est pas acceptée ou refusée.",
    },
    stats=lambda m: [("États", len(m.states)), ("Transitions", len(m.transitions))],
)

# --------------------------------------------------------------------------- #
# Composants / architecture
# --------------------------------------------------------------------------- #
COMPONENT = DiagramType(
    key="component",
    label="Diagramme de composants (architecture)",
    icon="",
    description="Architecture logicielle : applications, services, bases de données, équipements et leurs échanges.",
    model=ComponentModel,
    schema_example='''{"title":"Architecture web","components":[{"name":"Application web","kind":"component","group":"Frontend"},{"name":"API REST","kind":"component","group":"Backend"},{"name":"PostgreSQL","kind":"database","group":"Backend"},{"name":"Service de paiement","kind":"cloud"}],"links":[{"source":"Application web","target":"API REST","label":"HTTPS / JSON","style":"sync"},{"source":"API REST","target":"PostgreSQL","label":"SQL"},{"source":"Service de paiement","target":"API REST","label":"webhook","style":"async"}],"assumptions":[]}''',
    rules='''- Types d'élément ("kind") : component, database, node (serveur, microcontrôleur, appareil), cloud (service externe), queue (file de messages), interface, actor.
- "group" est facultatif : il regroupe des éléments dans un même paquet (Frontend, Backend, Réseau...).
- Un lien va de celui qui appelle ou utilise ("source") vers celui qui est appelé ("target"). "label" indique le protocole ou la donnée échangée.
- "style" vaut sync (appel direct) ou async (événement, message, webhook).
- Tout élément cité dans un lien doit être déclaré dans "components".''',
    detailed_extra="Ajoute les éléments d'infrastructure évidents (passerelle, cache, file de messages) uniquement s'ils sont mentionnés.",
    examples={
        "Application web e-commerce": "Le client utilise une application web (frontend React) qui appelle une API REST (backend Django) en HTTPS. L'API lit et écrit dans une base PostgreSQL et met en cache les catalogues dans Redis. Pour les paiements, l'API appelle un service de paiement externe, qui renvoie un webhook asynchrone. Un worker de tâches de fond lit une file de messages pour envoyer les emails.",
        "Objets connectés (IoT)": "Des capteurs ESP32 envoient leurs mesures en MQTT à un broker. Un service d'ingestion lit le broker et enregistre les données dans une base de séries temporelles. Une API REST expose ces données à un tableau de bord web. Le tableau de bord envoie aussi des commandes à l'API, qui les republie sur le broker vers les ESP32.",
    },
    stats=lambda m: [("Éléments", len(m.components)), ("Liens", len(m.links))],
)

# --------------------------------------------------------------------------- #
# Registre
# --------------------------------------------------------------------------- #
DIAGRAM_TYPES: Dict[str, DiagramType] = {t.key: t for t in (CLASS, ER, USECASE, SEQUENCE, ACTIVITY, STATE, COMPONENT)}
TYPE_ORDER: List[str] = list(DIAGRAM_TYPES)
DEFAULT_TYPE = "class"
