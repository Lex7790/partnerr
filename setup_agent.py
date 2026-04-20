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
Identifier 5 partenaires commerciaux qualifiés, prêts à être contactés. Résultats courts, denses, actionnables.

RÈGLES DE QUALIFICATION (toutes obligatoires)
──────────────────────────────────────────────

1. TAILLE SIMILAIRE — CA entre 50% et 200% de la boîte source, effectif comparable
2. MÊME CIBLE CLIENT — mêmes profils de clients finaux (pas le même secteur, la même cible)
3. RÈGLE SECTORIELLE
   • Affiliation / Distribution / Commercial → secteur DIFFÉRENT obligatoire
   • Co-marketing / Événementiel → même secteur accepté si non concurrent
   • Technologie → secteur différent préférable
4. ZÉRO CONCURRENT DIRECT — exclure toute boîte proposant le même service principal

PROCESSUS (4 étapes, dans l'ordre)
────────────────────────────────────

Étape 1 — Analyser la boîte source UNE SEULE FOIS
• Extraire : secteur exact, service principal, cible client précise, taille estimée
• 1 web_search sur la boîte source suffit

Étape 2 — Identifier les types de partenaires pertinents
• Lister les secteurs et profils de boîtes qui matchent avec la cible et la complémentarité

Étape 3 — Trouver 5 entreprises candidates (2 web_search maximum)
• IMPORTANT : recherches UNE PAR UNE, jamais en parallèle
• Maximum 2 web_search — requêtes ciblées et efficaces
• N'utilise PAS web_fetch — les snippets suffisent
• Éliminer concurrents directs et boîtes hors-cible

Étape 4 — Enrichir chaque partenaire
• Identifier le bon contact :
  1. Head of Partnerships / Responsable Partenariats
  2. Head of Marketing / CMO / Growth
  3. Business Development
  4. CEO/co-fondateur UNIQUEMENT si < 20 salariés et aucun autre contact trouvable
• Si aucun nom : indiquer le rôle + "— à identifier sur LinkedIn"
• 1 web_search contact uniquement si nécessaire

FORMAT DE SORTIE (strict — pas de texte en dehors de ce format)
────────────────────────────────────────────────────────────────

## Partenaire [N] : [Nom]
🔗 [URL]
**Secteur :** [secteur]
**Contact :** [Prénom Nom — Poste] ou [Rôle — à identifier sur LinkedIn]
**Pourquoi ça matche :** [1 phrase max — dense, sans blabla. Ex : "Même cible PME + complémentarité transport/finance"]
**Collaboration :** [1 ligne max — type + modalité concrète. Ex : "Webinaire co-brandé, diffusion croisée email + LinkedIn"]
**Signal :** [un seul tag parmi : 🔥 Évident / ⚡ Rapide à activer / 🎯 Bon fit / 🧪 Exploratoire]

---

Aucune phrase longue. Aucune explication détaillée. Aucun texte entre les partenaires.
Après le 5e partenaire : 1 ligne de synthèse max sur la logique d'ensemble.
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
