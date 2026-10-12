"""Un assistant Open WebUI qui agit dans n8n : installe ce que le module 1 fait à l'écran.

Côté n8n (API de l'éditeur, avec le compte N8N_EMAIL) :
  1. l'identifiant « Jeton Open WebUI » (Bearer, jeton JETON_MCP) ;
  2. la table de données « Congés », remplie avec n8n/conges.csv ;
  3. le workflow « Outils RH pour Open WebUI » (n8n/outils-rh.json : MCP Server Trigger et deux
     outils Data table), relié à l'identifiant et à la table, puis publié.
Côté Open WebUI (API, jeton administrateur OWUI_JETON) :
  4. la connexion MCP « n8n RH » (open-webui/connexion-rh.json : en-tête X-Utilisateur-Email) ;
  5. le modèle « Assistant congés » (open-webui/assistant-conges.json).

Usage :
  python installer.py              # installe (ce qui existe déjà sous le même nom est remplacé)
  python installer.py --retirer    # retire tout ce qui précède

Réglages : fichier .env (voir .env.example) ; les variables d'environnement l'emportent.
Aucune dépendance : Python 3.10 ou plus récent, bibliothèque standard seulement.
"""
import csv
import http.cookiejar
import json
import os
import pathlib
import secrets
import sys
import urllib.error
import urllib.request
import uuid

ICI = pathlib.Path(__file__).resolve().parent
CLES = ("N8N_URL", "N8N_EMAIL", "N8N_MOT_DE_PASSE", "N8N_INTERNE", "JETON_MCP", "OWUI_URL", "OWUI_JETON", "MODELE_BASE")
IDENTIFIANT = "Jeton Open WebUI"
TABLE = "Congés"
CONNEXION = "rh"


def reglages() -> dict:
    """Lit .env (clé=valeur), puis l'environnement, qui l'emporte."""
    r = {}
    env = ICI / ".env"
    if env.exists():
        for ligne in env.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#") and "=" in ligne:
                cle, valeur = ligne.split("=", 1)
                r[cle.strip()] = valeur.strip()
    for cle in CLES:
        if os.environ.get(cle):
            r[cle] = os.environ[cle]
    return r


R = reglages()


# ---------------------------------------------------------------- n8n : API de l'éditeur (session par cookie)

class N8n:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.navigateur = str(uuid.uuid4())  # n8n lie la session à cet identifiant
        self.ouvreur = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def appel(self, methode: str, chemin: str, corps=None, ignorer404=False):
        donnees = None if corps is None else json.dumps(corps).encode()
        req = urllib.request.Request(self.url + chemin, data=donnees, method=methode,
                                     headers={"Content-Type": "application/json", "browser-id": self.navigateur})
        try:
            with self.ouvreur.open(req, timeout=30) as rep:
                texte = rep.read().decode()
        except urllib.error.HTTPError as e:
            if ignorer404 and e.code == 404:
                return None
            sys.exit(f"n8n {methode} {chemin} : {e.code} {e.read().decode()[:300]}")
        if not texte:
            return None
        j = json.loads(texte)
        return j.get("data", j) if isinstance(j, dict) else j

    def connexion(self, email: str, mot_de_passe: str):
        self.appel("POST", "/rest/login", {"emailOrLdapLoginId": email, "password": mot_de_passe})
        projets = self.appel("GET", "/rest/projects/my-projects")
        self.projet = next(p["id"] for p in projets if p["type"] == "personal")


def retirer_n8n(n8n: N8n, nom_workflow: str):
    for w in n8n.appel("GET", "/rest/workflows") or []:
        if w["name"] == nom_workflow:
            n8n.appel("POST", f"/rest/workflows/{w['id']}/deactivate", ignorer404=True)
            n8n.appel("POST", f"/rest/workflows/{w['id']}/archive", ignorer404=True)
            n8n.appel("DELETE", f"/rest/workflows/{w['id']}", ignorer404=True)
            print(f"  n8n : workflow « {nom_workflow} » retiré")
    for c in n8n.appel("GET", "/rest/credentials") or []:
        if c["name"] == IDENTIFIANT:
            n8n.appel("DELETE", f"/rest/credentials/{c['id']}", ignorer404=True)
            print(f"  n8n : identifiant « {IDENTIFIANT} » retiré")
    tables = n8n.appel("GET", f"/rest/projects/{n8n.projet}/data-tables") or {}
    for t in tables.get("data", tables) if isinstance(tables, dict) else tables:
        if t["name"] == TABLE:
            n8n.appel("DELETE", f"/rest/projects/{n8n.projet}/data-tables/{t['id']}", ignorer404=True)
            print(f"  n8n : table « {TABLE} » retirée")


def installer_n8n(n8n: N8n, jeton: str) -> None:
    gabarit = (ICI / "n8n" / "outils-rh.json").read_text(encoding="utf-8")
    nom_workflow = json.loads(gabarit)["name"]
    retirer_n8n(n8n, nom_workflow)
    # 1. Identifiant Bearer : le jeton n'est écrit nulle part ailleurs que dans n8n.
    ident = n8n.appel("POST", "/rest/credentials", {"name": IDENTIFIANT, "type": "httpBearerAuth", "data": {"token": jeton}})
    # 2. Table « Congés » et ses lignes d'exemple.
    with open(ICI / "n8n" / "conges.csv", encoding="utf-8", newline="") as f:
        lignes = list(csv.DictReader(f))
    colonnes = list(lignes[0].keys())
    table = n8n.appel("POST", f"/rest/projects/{n8n.projet}/data-tables",
                      {"name": TABLE, "columns": [{"name": c, "type": "string"} for c in colonnes]})
    n8n.appel("POST", f"/rest/projects/{n8n.projet}/data-tables/{table['id']}/insert", {"data": lignes})
    # 3. Workflow relié à l'identifiant et à la table, puis publié (un serveur MCP ne répond qu'une fois publié).
    workflow = json.loads(gabarit.replace("${ID_IDENTIFIANT}", ident["id"]).replace("${ID_TABLE}", table["id"]))
    wf = n8n.appel("POST", "/rest/workflows", {k: workflow[k] for k in ("name", "nodes", "connections", "settings")})
    n8n.appel("POST", f"/rest/workflows/{wf['id']}/activate", {"versionId": wf["versionId"]})
    print(f"  n8n : identifiant, table ({len(lignes)} lignes) et workflow « {nom_workflow} » publié")


# ---------------------------------------------------------------- Open WebUI : API (jeton administrateur)

def owui(methode: str, chemin: str, corps=None, ignorer404=False):
    donnees = None if corps is None else json.dumps(corps).encode()
    req = urllib.request.Request(R["OWUI_URL"].rstrip("/") + chemin, data=donnees, method=methode,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {R['OWUI_JETON']}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as rep:
            texte = rep.read().decode()
    except urllib.error.HTTPError as e:
        if ignorer404 and e.code in (400, 401, 404):
            return None
        sys.exit(f"Open WebUI {methode} {chemin} : {e.code} {e.read().decode()[:300]}")
    return json.loads(texte) if texte else None


def remplir(texte: str, valeurs: dict) -> str:
    """Remplace les ${VARIABLE} d'un gabarit ; les {{USER_…}} restent pour Open WebUI."""
    for cle, valeur in valeurs.items():
        texte = texte.replace("${" + cle + "}", json.dumps(valeur)[1:-1])
    return texte


def retirer_owui():
    conf = owui("GET", "/api/v1/configs/tool_servers")
    reste = [c for c in conf["TOOL_SERVER_CONNECTIONS"] if (c.get("info") or {}).get("id") != CONNEXION]
    if len(reste) != len(conf["TOOL_SERVER_CONNECTIONS"]):
        owui("POST", "/api/v1/configs/tool_servers", {"TOOL_SERVER_CONNECTIONS": reste})
        print(f"  Open WebUI : connexion « {CONNEXION} » retirée")
    modele = json.loads((ICI / "open-webui" / "assistant-conges.json").read_text(encoding="utf-8"))
    if owui("POST", "/api/v1/models/model/delete", {"id": modele["id"]}, ignorer404=True) is not None:
        print(f"  Open WebUI : modèle « {modele['name']} » retiré")


def installer_owui(jeton: str):
    retirer_owui()
    valeurs = {"JETON_MCP": jeton, "MODELE_BASE": R.get("MODELE_BASE", "")}
    connexion = json.loads(remplir((ICI / "open-webui" / "connexion-rh.json").read_text(encoding="utf-8"), valeurs))
    if R.get("N8N_INTERNE"):
        connexion["url"] = R["N8N_INTERNE"].rstrip("/") + "/mcp/conges"
    conf = owui("GET", "/api/v1/configs/tool_servers")
    owui("POST", "/api/v1/configs/tool_servers", {"TOOL_SERVER_CONNECTIONS": conf["TOOL_SERVER_CONNECTIONS"] + [connexion]})
    modele = json.loads(remplir((ICI / "open-webui" / "assistant-conges.json").read_text(encoding="utf-8"), valeurs))
    owui("POST", "/api/v1/models/create", modele)
    print(f"  Open WebUI : connexion « {connexion['info']['name']} » ({connexion['url']}) et modèle « {modele['name']} »")
    print("  Redémarrez Open WebUI (ou rechargez la page) pour que l'éditeur de modèles voie la nouvelle connexion.")


def main():
    manque = [c for c in ("N8N_URL", "N8N_EMAIL", "N8N_MOT_DE_PASSE", "OWUI_URL", "OWUI_JETON") if not R.get(c)]
    if "--retirer" not in sys.argv and not R.get("MODELE_BASE"):
        manque.append("MODELE_BASE")
    if manque:
        sys.exit(f"Réglages manquants (.env) : {', '.join(manque)}")
    n8n = N8n(R["N8N_URL"])
    n8n.connexion(R["N8N_EMAIL"], R["N8N_MOT_DE_PASSE"])
    if "--retirer" in sys.argv:
        retirer_owui()
        retirer_n8n(n8n, json.loads((ICI / "n8n" / "outils-rh.json").read_text(encoding="utf-8"))["name"])
        return
    jeton = R.get("JETON_MCP") or secrets.token_hex(24)
    if not R.get("JETON_MCP"):
        print(f"  jeton tiré au hasard (à garder si vous configurez la connexion à la main) : {jeton}")
    installer_n8n(n8n, jeton)
    installer_owui(jeton)
    print("Terminé : choisissez « Assistant congés » dans Open WebUI et demandez « Quels congés ai-je déjà posés ? ».")


if __name__ == "__main__":
    main()
