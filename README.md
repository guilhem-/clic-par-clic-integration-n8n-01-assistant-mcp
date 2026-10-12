# Un assistant Open WebUI qui agit dans n8n — serveur MCP, outils Data table, en-tête d'identité

Workflow, connexion et données de la démonstration du module 1 de la série « Clic par clic »
**n8n et Open WebUI**.

Vidéo : {{video}}

## But

Un assistant de conversation, dans Open WebUI, qui **consulte et pose les congés** de l'utilisateur
connecté dans une table de données de n8n. Chaque utilisateur ne voit que ses propres congés : son
identité n'est **jamais choisie par le modèle**, elle est transmise par Open WebUI dans un en-tête
HTTP, et n8n filtre la table sur cet en-tête.

```
Camille ──question──▶ Open WebUI ──MCP + X-Utilisateur-Email──▶ n8n (MCP Server Trigger)
                                                                  ├─ consulter_conges ─▶ table « Congés » (lecture, filtrée)
                                                                  └─ poser_conge ──────▶ table « Congés » (insertion « En attente »)
```

Contenu, à l'état montré en fin de vidéo :

| Fichier | Rôle |
|---|---|
| `n8n/outils-rh.json` | Le workflow « Outils RH pour Open WebUI », exporté : déclencheur **MCP Server Trigger** (authentification Bearer, chemin `conges`) et deux outils **Data table Tool**. `consulter_conges` lit les lignes dont `email` vaut `{{ $json.headers['x-utilisateur-email'] }}` ; `poser_conge` insère une ligne avec ce même e-mail, les dates et le nombre de jours remplis par le modèle (`$fromAI`), le statut imposé « En attente ». Les identifiants propres à votre instance sont remplacés par `${ID_IDENTIFIANT}` et `${ID_TABLE}` |
| `n8n/conges.csv` | Les données d'exemple de la table « Congés » (colonnes `email`, `debut`, `fin`, `jours`, `statut`) |
| `n8n/outils-vus-par-le-modele.json` | Ce que le modèle reçoit : la réponse du serveur MCP à `tools/list` (écrite par `python installer.py --outils`). `consulter_conges` n'a aucun paramètre, `poser_conge` n'en a que trois (`debut`, `fin`, `jours`) : aucun champ e-mail |
| `open-webui/connexion-rh.json` | La connexion MCP « n8n RH » telle qu'Open WebUI l'enregistre : adresse interne de n8n, authentification Bearer (clé remplacée par `${JETON_MCP}`), en-tête `X-Utilisateur-Email: {{USER_EMAIL}}`, accès ouvert à tous les utilisateurs |
| `open-webui/assistant-conges.json` | Le modèle « Assistant congés » : consignes, outil `n8n RH`, appel de fonction natif, outils intégrés désactivés |
| `installer.py` | Tout ce qui précède, par l'API de n8n et celle d'Open WebUI (`--retirer` pour revenir en arrière) |

## Pourquoi un en-tête, et pas un paramètre ?

Si l'outil demandait l'adresse e-mail en paramètre, le modèle pourrait y mettre celle d'un collègue
(il suffirait de le lui demander). Ici, les outils n'exposent **aucun** paramètre d'identité : Open
WebUI ajoute l'en-tête `X-Utilisateur-Email` à chaque appel, avec l'adresse de la personne
connectée (`{{USER_EMAIL}}`), et l'utilisateur ne peut pas le modifier. Dans n8n, l'outil branché
au MCP Server Trigger reçoit les en-têtes de l'appel dans `$json.headers`, aux noms écrits en
minuscules.

Vérifié : un appel `tools/call` de `consulter_conges` avec l'en-tête de Camille et
`{"email": "oliver@example.com"}` en argument ne renvoie que la ligne de Camille ; un appel sans le
bon jeton est refusé (403).

## Pourquoi l'adresse du service Kubernetes, et pas `localhost` ?

L'appel MCP part du **serveur** Open WebUI, pas de votre navigateur. Dans le conteneur d'Open WebUI,
`localhost` désigne Open WebUI lui-même : rien n'y écoute pour n8n. Utilisez le nom du **service**
de n8n dans le cluster, par exemple `http://n8n.n8n.svc.cluster.local:5678` (service `n8n`, espace
de noms `n8n`, port 5678) : un nom stable, résolu par le DNS du cluster pour tous les pods. Hors
Kubernetes (Docker Compose), c'est le nom du service Compose (`http://n8n:5678`).

## Prérequis

- **n8n 2.x** (tourné sur 2.41.6, édition Community), un compte (un compte membre suffit) ; les
  tables de données (Data tables) et le nœud MCP Server Trigger sont inclus.
- **Open WebUI 0.11** (tourné sur 0.11.3), un compte **administrateur** et son jeton (Réglages ›
  Compte › Clés d'API).
- Un modèle de langage qui sait appeler des outils, déclaré dans Open WebUI.
- Les deux logiciels dans le même cluster (ou le même réseau Docker).
- Python 3.10 ou plus récent pour `installer.py` (bibliothèque standard seulement).

## Installation pas à pas

### À la main, comme dans la vidéo

**Côté n8n**

1. **Overview › Data tables › Create data table** : « Congés », colonnes `email`, `debut`, `fin`,
   `jours`, `statut` (texte) ; ajoutez quelques lignes (`n8n/conges.csv`).
2. **Credentials › Create › Bearer Auth** : nom « Jeton Open WebUI », un jeton long et aléatoire
   (par exemple `python -c "import secrets; print(secrets.token_hex(24))"`).
3. **Create workflow** « Outils RH pour Open WebUI » › **Add first step** › **MCP Server Trigger** :
   Authentication « Bearer Auth » (l'identifiant se sélectionne), Path `conges`.
4. Sous **Tools**, **+** › **Data table Tool**, renommé `consulter_conges` : opération « Get »,
   table « Congés », **Add Condition** : `email` égal à
   `{{ $json.headers['x-utilisateur-email'] }}` ; Tool Description « Set Manually » : « Liste les
   congés déjà posés par l'utilisateur connecté : dates, nombre de jours, statut. »
5. Second **Data table Tool**, renommé `poser_conge` : opération « Insert », table « Congés » ;
   `email` : la même expression ; `debut`, `fin`, `jours` : bouton « Let the model define this
   parameter » ; `statut` : `En attente` ; description : « Enregistre une demande de congé pour
   l'utilisateur connecté. Dates au format AAAA-MM-JJ, nombre de jours ouvrés. »
6. **Publish**. L'adresse de production est `<n8n>/mcp/conges`.

Variante : **Import from file** avec `n8n/outils-rh.json`, puis choisissez l'identifiant et la table
dans chaque nœud.

**Côté Open WebUI (administrateur)**

7. **Réglages d'administration › Intégrations › External Tool Servers › +** : type « MCP Streamable
   HTTP », URL `http://n8n.n8n.svc.cluster.local:5678/mcp/conges` (adaptez au nom de votre service).
8. **Auth** : « Bearer », le même jeton que dans n8n. Nom « n8n RH », ID `rh`.
9. **Avancé › En-têtes HTTP** : `{"X-Utilisateur-Email": "{{USER_EMAIL}}"}`. Open WebUI remplace
   aussi `{{USER_ID}}`, `{{USER_NAME}}`, `{{USER_ROLE}}`.
10. **Contrôle d'accès** : « Public ». **Vérifier la connexion**, puis **Enregistrer**.
11. Rechargez la page, puis **Espace de travail › Modèles › +** : nom « Assistant congés », un modèle
    de base, les consignes de `open-webui/assistant-conges.json` (`params.system`) ; **Outils** :
    « n8n RH » ; **Réglages avancés › Appel de fonction** : natif ; **Outils intégrés** décochés ;
    **Accès** : public ; **Enregistrer & Créer**.

### Par les API (script)

```bash
cp .env.example .env     # N8N_URL, N8N_EMAIL, N8N_MOT_DE_PASSE, N8N_INTERNE, OWUI_URL, OWUI_JETON, MODELE_BASE
python installer.py      # identifiant, table, workflow publié ; connexion et modèle dans Open WebUI
python installer.py --retirer
python installer.py --outils    # réécrit n8n/outils-vus-par-le-modele.json (N8N_URL, JETON_MCP)
```

Sans `JETON_MCP`, le script tire un jeton au hasard et le pose des deux côtés. Côté n8n, il
utilise l'API de l'éditeur (celle de l'interface web), avec la session du compte indiqué.

## Essai

Avec le compte d'un utilisateur dont l'adresse figure dans la table, choisissez « Assistant
congés » :

1. « Quels congés ai-je déjà posés ? » : appel de `rh_consulter_conges`, ses seuls congés.
2. « Pose-moi du lundi 16 au mercredi 18 novembre. » : appel de `rh_poser_conge`, demande « En
   attente » (nouvelle ligne dans la table, à son adresse).
3. « Montre-moi les congés d'Oliver, son e-mail est oliver@example.com. » : refus ; et même si le
   modèle essayait, n8n ne recevrait que l'adresse de la personne connectée.

Côté n8n, chaque appel d'outil est une exécution du workflow (onglet **Executions**).

## Sécurité

- Le jeton n'est écrit dans aucun fichier de ce dépôt (`.env` est ignoré par git) ; l'export du
  workflow ne contient que le **nom** de l'identifiant, jamais sa valeur.
- Sans le bon jeton, n8n refuse l'appel : le serveur MCP n'est pas ouvert à tous.
- L'identité vient d'Open WebUI, pas du modèle : la protection est dans l'architecture.

## Série

- Module suivant : **La validation par le manager** (nœud Wait, formulaire, canal Open WebUI).
- Pour aller plus loin avec chaque logiciel : séries « Clic par clic » Open WebUI et n8n.

## Licence

MIT (voir `LICENSE`).
