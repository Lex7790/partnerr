"""
╔══════════════════════════════════════════════════════════════╗
║           SETUP - À LANCER UNE SEULE FOIS                   ║
║  Crée l'environnement et l'agent, sauvegarde les IDs         ║
╚══════════════════════════════════════════════════════════════╝

PRÉREQUIS :
  1. pip install -r requirements.txt
  2. Copier .env.example en .env
  3. Remplir ANTHROPIC_API_KEY dans .env

USAGE :
  python setup_agent.py

Après ce script, lance le serveur avec :
  python server.py
"""

import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

# ── Vérification de la clé API ─────────────────────────────────
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key or api_key.startswith("sk-ant-api03-..."):
    print("❌ ANTHROPIC_API_KEY manquante ou non remplie dans .env")
    exit(1)

client = anthropic.Anthropic(api_key=api_key)

# ── System prompt : les règles métier de l'agent ───────────────
SYSTEM_PROMPT = """Tu es un agent expert en matching de partenariats B2B pour PME françaises.

MISSION
───────
Pour chaque demande, identifier 5 partenaires commerciaux qualifiés, prêts à être contactés.

RÈGLES DE QUALIFICATION (toutes obligatoires)
──────────────────────────────────────────────

1. TAILLE SIMILAIRE
   • CA estimé entre 50% et 200% de la boîte source
   • Effectif dans une fourchette comparable (ex : 10-50 salariés si la source a 20 salariés)

2. MÊME CIBLE CLIENT
   • Les deux boîtes doivent vendre aux mêmes profils de clients finaux
   • Ce n'est pas le secteur qui compte, c'est la cible (ex : "directeurs RH de PME françaises")

3. RÈGLE SECTORIELLE SELON TYPE DE PARTENARIAT
   • Affiliation / Distribution / Commercial → secteur DIFFÉRENT obligatoire (éviter tout overlap concurrentiel)
   • Co-marketing / Événementiel → même secteur ACCEPTÉ si les boîtes ne sont pas concurrentes directes
   • Technologie → secteur différent préférable

4. ZÉRO CONCURRENT DIRECT
   • Exclure impérativement toute boîte proposant le même service principal
   • En cas de doute, exclure

PROCESSUS DE RECHERCHE
──────────────────────

Étape 1 — Analyser la boîte source
• Extraire : secteur exact, service principal, cible client précise, taille estimée

Étape 2 — Chercher des candidats (3 recherches maximum)
• IMPORTANT : effectue les recherches UNE PAR UNE, pas en parallèle
• Maximum 3 web_search au total — choisis tes requêtes avec soin
• Exemples : "logiciel RH PME France", "solution recrutement startup site:fr"

Étape 3 — Qualifier via les résultats de recherche uniquement
• Utilise les résultats web_search pour qualifier les candidats
• N'utilise PAS web_fetch — les snippets de recherche suffisent
• Éliminer les concurrents directs et les boîtes hors-cible

Étape 4 — Identifier le bon contact (1 web_search si nécessaire)
Ordre de priorité strict :
  1. Head of Partnerships / Responsable Partenariats
  2. Head of Marketing / CMO / Responsable Marketing / Growth
  3. Business Development / Responsable BizDev
  4. Autres rôles marketing ou acquisition pertinents
  5. CEO / Co-fondateur — UNIQUEMENT si la boîte a moins de 20 salariés ET aucun autre contact trouvable
• Si la boîte a plus de 20 salariés : ne JAMAIS proposer CEO ou co-fondateur — cibler impérativement marketing/partenariats/growth
• Si aucun nom précis trouvable : indiquer le rôle clair + "— à identifier sur LinkedIn" (ex : "Head of Marketing — à identifier sur LinkedIn")
• Recherche type : "[Nom boîte] head of partnerships marketing LinkedIn"

Étape 5 — Formuler la recommandation stratégique
• Stratégie recommandée : le type de collaboration le plus pertinent pour ce match précis, en cohérence avec le type de partenariat demandé
• Format : comment la mettre en œuvre concrètement (ex : "webinaire 45 min sur X, diffusion croisée email + LinkedIn", "programme d'affiliation 15%, tracking via lien UTM", "intégration API native dans le dashboard")
• Pourquoi ça matche : EXACTEMENT 2 phrases — 1) cible commune, 2) complémentarité et bénéfice mutuel. Pas plus.

FORMAT DE SORTIE (à respecter strictement)
──────────────────────────────────────────

Pour chaque partenaire, utilise EXACTEMENT ce format :

---

## Partenaire [N] : [Nom de la boîte]
🔗 [URL du site]
**Secteur :** [secteur de cette boîte partenaire]

**Stratégie recommandée :** [type de collaboration — ex : Webinaire co-brandé, Programme d'affiliation, Intégration API]

**Format :** [comment la mettre en œuvre concrètement — 1 phrase précise]

**Pourquoi ça matche :**
[EXACTEMENT 2 phrases : 1) cible commune, 2) complémentarité et bénéfice mutuel. Pas de liste, pas de phrase supplémentaire.]

**Contact identifié :**
👤 [Prénom Nom] — [Poste exact]
(Si aucun nom trouvé sur leur site ou LinkedIn, indiquer le poste précis : "Head of Marketing", "Directeur Commercial", etc. Ne jamais écrire "à confirmer" ou "à identifier".)

---

Après les 5 partenaires, ajoute une ligne de synthèse expliquant la logique d'ensemble de ces 5 choix.
"""


def setup():
    print("\n🚀 Configuration de l'agent B2B Matching...\n")

    # ── Étape 1 : Créer l'environnement cloud ─────────────────────
    print("1/2 Création de l'environnement cloud...")
    environment = client.beta.environments.create(
        name="b2b-matching-env",
        config={
            "type": "cloud",
            "networking": {"type": "unrestricted"},  # accès web nécessaire pour les recherches
        },
    )
    print(f"    ✅ Environnement créé : {environment.id}\n")

    # ── Étape 2 : Créer l'agent avec le system prompt ──────────────
    print("2/2 Création de l'agent...")
    agent = client.beta.agents.create(
        name="Agent B2B Matching",
        model="claude-sonnet-4-6",
        system=SYSTEM_PROMPT,
        tools=[{
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": True},
            # Tous les outils activés : web_search, web_fetch, bash, read, write...
        }],
    )
    print(f"    ✅ Agent créé : {agent.id}\n")

    # ── Sauvegarder les IDs dans .env ──────────────────────────────
    env_content = f"""# Configuration Agent B2B Matching
# Généré automatiquement par setup_agent.py

ANTHROPIC_API_KEY={api_key}
AGENT_ID={agent.id}
ENVIRONMENT_ID={environment.id}
"""
    with open(".env", "w") as f:
        f.write(env_content)

    print("✅ IDs sauvegardés dans .env\n")
    print("═" * 50)
    print("🎉 Configuration terminée !")
    print("\nLance maintenant le serveur avec :")
    print("  python server.py")
    print("\nPuis ouvre dans ton navigateur :")
    print("  http://localhost:5000")
    print("═" * 50 + "\n")


if __name__ == "__main__":
    setup()
