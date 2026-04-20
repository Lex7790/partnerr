"""
Serveur Flask — Agent B2B Matching
Lance avec : python3 server.py
Puis ouvre : http://127.0.0.1:5000
"""

import anthropic
import os
import re
import json
from flask import Flask, request, Response, stream_with_context, redirect
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
AGENT_ID = os.environ.get("AGENT_ID")
ENV_ID = os.environ.get("ENVIRONMENT_ID")
HISTORY_FILE  = os.environ.get("HISTORY_FILE",  "/data/history.json")
LOG_FILE      = os.environ.get("LOG_FILE",      "/data/logs.json")
USERS_FILE    = os.environ.get("USERS_FILE",    "/data/users.json")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def append_log(entry):
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
    logs.append(entry)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def save_history(email, new_companies):
    history = load_history()
    existing = history.get(email, [])
    merged = list(set(existing + new_companies))
    history[email] = merged
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def send_welcome_email(email):
    if not RESEND_API_KEY:
        return
    try:
        import urllib.request
        payload = json.dumps({
            "from": "Partnerr <onboarding@resend.dev>",
            "to": [email],
            "subject": "Bienvenue sur Partnerr 👋",
            "html": f"""
            <div style="font-family:sans-serif; max-width:480px; margin:0 auto; padding:32px; color:#0B0718;">
              <h2 style="font-size:22px; margin-bottom:16px;">Bienvenue sur Partnerr !</h2>
              <p style="color:#4B4565; line-height:1.6; margin-bottom:24px;">
                Votre compte est créé. Vous disposez d'<strong>1 recherche gratuite</strong> pour trouver vos premiers partenaires B2B qualifiés.
              </p>
              <a href="https://partnerr.onrender.com/app" style="display:inline-block; padding:12px 24px; background:#5E35E0; color:white; border-radius:8px; text-decoration:none; font-weight:600;">
                Lancer ma première recherche →
              </a>
              <p style="margin-top:32px; font-size:13px; color:#8B87A3;">
                Des questions ? Répondez à cet email ou écrivez-nous à contact@partnerr.fr
              </p>
            </div>
            """
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"}
        )
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"[EMAIL] Erreur envoi : {e}", flush=True)


@app.route("/register", methods=["POST"])
def register():
    email = request.form.get("email", "").strip().lower()
    if not email or "@" not in email:
        return redirect("/")
    users = load_users()
    is_new = email not in users
    if is_new:
        users[email] = {"plan": "free", "credits": 1}
        save_users(users)
        send_welcome_email(email)
    return redirect(f"/app?email={email}")


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
    geo             = request.form.get("geo", "France").strip()
    plan            = request.form.get("plan", "free").strip().lower()
    exclude_manual  = request.form.get("exclude_manual", "").strip()

    # Nombre de partenaires selon le plan
    n_partners = 3 if plan in ("free", "starter") else 5

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
            excluded_history = history.get(user_email, [])
            excluded_manual  = [e.strip() for e in exclude_manual.split(",") if e.strip()]
            excluded = list(set(excluded_history + excluded_manual))
            excluded_line = (
                f"\nBoîtes déjà proposées à EXCLURE IMPÉRATIVEMENT (propose uniquement des nouvelles boîtes) : {', '.join(excluded)}"
                if excluded else ""
            )

            user_message = f"""Boîte à analyser : {company_name}
Secteur : {sectors_str}
Clients cibles : {clients_str}
Taille : {size}
Secteurs partenaires recherchés : {partners_str}
Zone géographique cible : {geo}
Thématique : {theme}{context_line}{excluded_line}

{f"⛔ INTERDIT : Ne propose JAMAIS les boîtes suivantes, même si elles semblent pertinentes : {', '.join(excluded)}. Propose UNIQUEMENT des boîtes que tu n'as jamais proposées à cet utilisateur." if excluded else ""}

Lance une recherche web sur "{company_name}" pour enrichir ton analyse, puis trouve {n_partners} partenaires B2B qualifiés selon les règles. Oriente tes recherches vers les secteurs partenaires indiqués. Les partenaires proposés doivent être basés ou actifs en priorité dans la zone géographique suivante : {geo}.

⚠️ QUALITÉ OBLIGATOIRE : Pour chaque partenaire proposé, vérifie qu'il existe une présence en ligne cohérente et récente (site web fonctionnel, activité visible, actualités récentes). Si l'activité d'une entreprise est incertaine, douteuse ou introuvable en ligne, ne la propose pas et choisis une alternative active et vérifiable."""

            def save_results():
                from datetime import datetime, timezone
                names = re.findall(r'## Partenaire \d+\s*:\s*(.+)', accumulated_text)
                names = [n.strip() for n in names if n.strip()]
                if names and user_email:
                    save_history(user_email, names)
                append_log({
                    "date":      datetime.now(timezone.utc).isoformat(),
                    "email":     user_email,
                    "company":   company_name,
                    "plan":      plan,
                    "n_partners": len(names),
                    "partners":  names,
                    "status":    "success"
                })

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
                            f"Partenaire {n_partners}" in accumulated_text
                            or f"partenaire {n_partners}" in accumulated_text.lower()
                        )

                        if result_complet or continuations >= 4:
                            dups = find_duplicates() if dedup_attempts < 1 else []
                            if dups:
                                dedup_attempts += 1
                                dup_list = ', '.join(dups)
                                yield f"data: {json.dumps({'status': f'🔄 Remplacement de {len(dups)} doublon(s)...'})}\n\n"
                                continue_msg = f"⛔ Tu as proposé des partenaires déjà connus de cet utilisateur : {dup_list}. Ces boîtes sont INTERDITES. Remplace-les par {len(dups)} nouveau(x) partenaire(s) différent(s) que tu n'as jamais mentionné(s). Garde les autres partenaires tels quels et présente les {n_partners} au complet."
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
                            continue_msg = f"Continue et présente les {n_partners} partenaires complets en suivant exactement le format demandé."
                            client.beta.sessions.events.send(
                                session_id=session.id,
                                events=[{
                                    "type": "user.message",
                                    "content": [{"type": "text", "text": continue_msg}]
                                }]
                            )

        except anthropic.APIConnectionError:
            msg = "Connexion impossible à l'API Anthropic."
            append_log({"date": __import__('datetime').datetime.utcnow().isoformat(), "email": user_email, "company": company_name, "plan": plan, "status": "error", "error": msg})
            yield f"data: {json.dumps({'error': msg})}\n\n"
        except anthropic.AuthenticationError:
            msg = "Clé API invalide. Vérifie ANTHROPIC_API_KEY dans .env"
            append_log({"date": __import__('datetime').datetime.utcnow().isoformat(), "email": user_email, "company": company_name, "plan": plan, "status": "error", "error": msg})
            yield f"data: {json.dumps({'error': msg})}\n\n"
        except Exception as e:
            msg = f"Erreur : {str(e)}"
            append_log({"date": __import__('datetime').datetime.utcnow().isoformat(), "email": user_email, "company": company_name, "plan": plan, "status": "error", "error": msg})
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
