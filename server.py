"""
Serveur Flask — Agent B2B Matching
Lance avec : python3 server.py
Puis ouvre : http://127.0.0.1:5000
"""

import anthropic
import os
import re
import json
from flask import Flask, request, Response, stream_with_context
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
AGENT_ID = os.environ.get("AGENT_ID")
ENV_ID = os.environ.get("ENVIRONMENT_ID")
HISTORY_FILE = "history.json"


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(email, new_companies):
    history = load_history()
    existing = history.get(email, [])
    merged = list(set(existing + new_companies))
    history[email] = merged
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


@app.route("/")
def landing():
    with open("landing.html", encoding="utf-8") as f:
        return f.read()


@app.route("/app")
def index():
    with open("index.html", encoding="utf-8") as f:
        return f.read()


@app.route("/legal")
def legal():
    with open("legal.html", encoding="utf-8") as f:
        return f.read()


@app.route("/match", methods=["POST"])
def match():
    user_email      = request.form.get("user_email", "").strip().lower()
    company_name    = request.form.get("company_name", "").strip()
    theme           = request.form.get("theme", "").strip()
    sectors         = request.form.getlist("sector")
    sector_other    = request.form.get("sector_other", "").strip()
    clients         = request.form.getlist("clients")
    size            = request.form.get("size", "").strip()
    partner_sectors = request.form.getlist("partner_sectors")
    ps_other        = request.form.get("partner_sectors_other", "").strip()
    context         = request.form.get("context", "").strip()

    if not company_name or not theme or not user_email:
        return "Veuillez remplir tous les champs obligatoires.", 400

    if not AGENT_ID or AGENT_ID == "agent_...":
        return "Configuration manquante. Lance d'abord : python3 setup_agent.py", 500

    # Construire les listes lisibles
    if "Autre" in sectors and sector_other:
        sectors = [s for s in sectors if s != "Autre"] + [sector_other]
    if "Autre" in partner_sectors and ps_other:
        partner_sectors = [s for s in partner_sectors if s != "Autre"] + [ps_other]

    sectors_str  = ", ".join(sectors)  if sectors         else "Non précisé"
    clients_str  = ", ".join(clients)  if clients         else "Non précisé"
    partners_str = ", ".join(partner_sectors) if partner_sectors else "Non précisé"

    def generate():
        try:
            session = client.beta.sessions.create(
                agent=AGENT_ID,
                environment_id=ENV_ID,
                title=f"Matching B2B : {company_name[:60]}",
            )

            context_line = f"\nContexte : {context}" if context else ""

            history = load_history()
            excluded = history.get(user_email, [])
            excluded_line = (
                f"\nBoîtes déjà proposées à EXCLURE IMPÉRATIVEMENT (propose uniquement des nouvelles boîtes) : {', '.join(excluded)}"
                if excluded else ""
            )

            user_message = f"""Boîte à analyser : {company_name}
Secteur : {sectors_str}
Clients cibles : {clients_str}
Taille : {size}
Secteurs partenaires recherchés : {partners_str}
Thématique : {theme}{context_line}{excluded_line}

{f"⛔ INTERDIT : Ne propose JAMAIS les boîtes suivantes, même si elles semblent pertinentes : {', '.join(excluded)}. Propose UNIQUEMENT des boîtes que tu n'as jamais proposées à cet utilisateur." if excluded else ""}

Lance une recherche web sur "{company_name}" pour enrichir ton analyse, puis trouve 5 partenaires B2B qualifiés selon les règles. Oriente tes recherches vers les secteurs partenaires indiqués."""

            def save_results():
                names = re.findall(r'## Partenaire \d+\s*:\s*(.+)', accumulated_text)
                names = [n.strip() for n in names if n.strip()]
                if names and user_email:
                    save_history(user_email, names)

            def find_duplicates():
                found = []
                for name in excluded:
                    if re.search(r'## Partenaire \d+\s*:\s*' + re.escape(name), accumulated_text, re.IGNORECASE):
                        found.append(name)
                return found

            # Texte accumulé pour savoir si le résultat est complet
            accumulated_text = ""
            # Compteur de relances pour éviter une boucle infinie
            continuations = 0
            # Compteur de corrections de doublons (max 1)
            dedup_attempts = 0

            # Pattern stream-first : ouvrir AVANT d'envoyer
            with client.beta.sessions.events.stream(session_id=session.id) as stream:

                client.beta.sessions.events.send(
                    session_id=session.id,
                    events=[{
                        "type": "user.message",
                        "content": [{"type": "text", "text": user_message}]
                    }]
                )

                for event in stream:

                    # Erreur de session → on affiche et on arrête
                    if event.type == "session.error":
                        err = getattr(event, "error", None)
                        print(f"[SESSION.ERROR] {err}", flush=True)
                        continue  # l'agent va passer en idle, on laisse la logique de relance gérer

                    # Événements de monitoring qu'on ignore
                    if event.type in ("session.status_running", "span.model_request_start", "span.model_request_end"):
                        continue

                    # Texte produit par l'agent
                    if event.type == "agent.message":
                        for block in event.content:
                            if block.type == "text":
                                accumulated_text += block.text
                                yield f"data: {json.dumps({'text': block.text})}\n\n"

                    # Outil utilisé → message de statut
                    elif event.type == "agent.tool_use":
                        tool_name = getattr(event, "name", "outil")
                        labels = {
                            "web_search": "🔍 Recherche web...",
                            "web_fetch":  "📄 Lecture d'une page...",
                            "bash":       "⚙️ Traitement...",
                        }
                        status = labels.get(tool_name, f"🔧 {tool_name}...")
                        yield f"data: {json.dumps({'status': status})}\n\n"

                    # Session terminée définitivement
                    elif event.type == "session.status_terminated":
                        dups = find_duplicates() if dedup_attempts < 1 else []
                        if dups:
                            dup_list = ', '.join(dups)
                            warning = f"\n\n---\n\n⚠️ **{dup_list} {'ont' if len(dups) > 1 else 'a'} déjà été proposé{'s' if len(dups) > 1 else ''} lors d'une recherche précédente.** Relance la recherche pour obtenir des remplaçants."
                            yield f"data: {json.dumps({'text': warning})}\n\n"
                        save_results()
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        break

                    # Agent en pause entre deux phases
                    elif event.type == "session.status_idle":
                        stop_reason = getattr(event, "stop_reason", None)
                        stop_type = getattr(stop_reason, "type", "") if stop_reason else ""

                        if stop_type == "requires_action":
                            continue

                        # Rate limit → on arrête immédiatement sans spammer
                        if stop_type == "retries_exhausted":
                            yield f"data: {json.dumps({'error': '⏳ Limite API atteinte. Attends 5 minutes et relance la recherche.'})}\n\n"
                            break

                        result_complet = (
                            "Partenaire 5" in accumulated_text
                            or "partenaire 5" in accumulated_text.lower()
                        )

                        if result_complet or continuations >= 4:
                            dups = find_duplicates() if dedup_attempts < 1 else []
                            if dups:
                                dedup_attempts += 1
                                dup_list = ', '.join(dups)
                                yield f"data: {json.dumps({'status': f'🔄 Remplacement de {len(dups)} doublon(s)...'})}\n\n"
                                continue_msg = f"⛔ Tu as proposé des partenaires déjà connus de cet utilisateur : {dup_list}. Ces boîtes sont INTERDITES. Remplace-les par {len(dups)} nouveau(x) partenaire(s) différent(s) que tu n'as jamais mentionné(s). Garde les autres partenaires tels quels et présente le tout au complet."
                                client.beta.sessions.events.send(
                                    session_id=session.id,
                                    events=[{"type": "user.message", "content": [{"type": "text", "text": continue_msg}]}]
                                )
                            else:
                                save_results()
                                yield f"data: {json.dumps({'done': True})}\n\n"
                                break
                        else:
                            continuations += 1
                            yield f"data: {json.dumps({'status': f'💬 Relance ({continuations}/4)...'})}\n\n"
                            continue_msg = "Continue et présente les 5 partenaires complets en suivant exactement le format demandé."
                            client.beta.sessions.events.send(
                                session_id=session.id,
                                events=[{
                                    "type": "user.message",
                                    "content": [{"type": "text", "text": continue_msg}]
                                }]
                            )

        except anthropic.APIConnectionError:
            msg = "Connexion impossible à l'API Anthropic."
            yield f"data: {json.dumps({'error': msg})}\n\n"
        except anthropic.AuthenticationError:
            msg = "Clé API invalide. Vérifie ANTHROPIC_API_KEY dans .env"
            yield f"data: {json.dumps({'error': msg})}\n\n"
        except Exception as e:
            msg = f"Erreur : {str(e)}"
            yield f"data: {json.dumps({'error': msg})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY manquante dans .env")
        exit(1)
    if not AGENT_ID or AGENT_ID == "agent_...":
        print("❌ AGENT_ID manquant. Lance d'abord : python3 setup_agent.py")
        exit(1)

    print("\n🚀 Serveur démarré !")
    print("   Ouvre dans ton navigateur : http://127.0.0.1:5001\n")
    app.run(debug=False, threaded=True, port=5001)
