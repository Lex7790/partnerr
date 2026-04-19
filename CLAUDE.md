# Agent IA de matching partenariats B2B

## Contexte projet
Agent qui aide les responsables marketing/growth de PME B2B françaises à trouver des partenaires commerciaux pertinents.

## Stack
- **Claude Managed Agents** pour le raisonnement, l'enrichissement web et la génération
- **Formulaire HTML simple** en input
- **Rapport Markdown/PDF** en output
- **Airtable** pour stocker les partenaires trouvés (via skill `crm`)

## Règles de qualification (à respecter impérativement)
1. **Taille similaire** — CA entre 50% et 200% de la boîte source, effectif comparable
2. **Même cible client** — mêmes clients finaux, pas forcément même secteur
3. **Secteur différent** selon thématique :
   - Bundle commercial / recommandation croisée → secteur obligatoirement différent
   - Co-contenu / webinaire → même secteur OK si non-concurrent direct
4. **Zéro concurrent direct** — détecter et exclure systématiquement

## Thématiques de collaboration
- Co-contenu
- Newsletter croisée
- Bundle commercial
- Webinaire
- Technologie

## Output attendu par partenaire
1. Nom de la boîte + raison du match
2. Contact identifié (nom + poste)
3. Message LinkedIn personnalisé prêt à envoyer

## Skills actifs pour ce projet
- `prospect` — recherche des entreprises candidates
- `icebreaker` — génération des messages d'approche
- `cold-email` — structure et ton des messages
- `crm` — stockage des résultats dans Airtable
- `claude-api` — code de l'intégration Managed Agents

## Objectif POC
Input texte → traitement agent → 5 partenaires qualifiés en output.
Pas d'interface complexe, pas de base de données. Brutal et fonctionnel.
