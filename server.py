"""
Serveur Flask — Agent B2B Matching
Lance avec : python3 server.py
Puis ouvre : http://127.0.0.1:5000
"""

import anthropic
import os
import re
import json
import fcntl
import threading
import stripe
from flask import Flask, request, Response, stream_with_context, redirect, jsonify
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

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICES = {
    "starter": os.environ.get("STRIPE_PRICE_STARTER", ""),
    "growth":  os.environ.get("STRIPE_PRICE_GROWTH",  ""),
    "scale":   os.environ.get("STRIPE_PRICE_SCALE",   ""),
}
PLAN_CREDITS = {
    "starter": {"plan": "starter", "credits": 2},
    "growth":  {"plan": "growth",  "credits": 3},
    "scale":   {"plan": "scale",   "credits": 6},
}

_users_lock = threading.Lock()


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


def atomic_decrement_credits(email):
    """Lit, vérifie et décrémente les crédits de façon atomique (thread-safe + multi-process)."""
    lock_path = USERS_FILE + ".lock"
    with _users_lock:
        with open(lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                users = load_users()
                user_data = users.get(email, {})
                plan = user_data.get("plan", "free")
                credits = user_data.get("credits", 0)
                if credits <= 0:
                    return None, 0
                users[email]["credits"] = credits - 1
                save_users(users)
                return plan, credits
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)


def send_welcome_email(email, prenom=""):
    if not RESEND_API_KEY:
        print("[EMAIL] Clé RESEND_API_KEY manquante", flush=True)
        return
    salutation = f"Bonjour {prenom} !" if prenom else "Bienvenue sur Partnerr !"
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": "Partnerr <hello@usepartnerr.com>",
            "to": [email],
            "subject": "Bienvenue sur Partnerr 👋",
            "html": f"""
            <div style="font-family:'Helvetica Neue',Helvetica,Arial,sans-serif; background:#0B0718; padding:48px 24px;">
              <div style="max-width:480px; margin:0 auto;">
                <div style="margin-bottom:36px;">
                  <span style="font-size:20px; font-weight:800; color:#ffffff;">Partnerr<span style="color:#7B56F5;">.</span></span>
                </div>
                <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:16px; padding:36px 32px;">
                  <p style="font-size:12px; font-weight:700; letter-spacing:0.1em; text-transform:uppercase; color:#7B56F5; margin:0 0 12px;">Votre accès est prêt</p>
                  <h1 style="font-size:24px; font-weight:800; color:#ffffff; margin:0 0 16px; line-height:1.3;">{salutation}</h1>
                  <p style="font-size:15px; color:rgba(255,255,255,0.75); line-height:1.7; margin:0 0 12px;">
                    Vous avez <strong style="color:#ffffff;">1 recherche gratuite</strong> disponible maintenant.
                  </p>
                  <p style="font-size:15px; color:rgba(255,255,255,0.75); line-height:1.7; margin:0 0 28px;">
                    Décrivez votre activité. En quelques minutes, Partnerr vous dit quelles entreprises cibler, comment les approcher et pourquoi ça peut convertir.
                  </p>
                  <a href="https://usepartnerr.com/app" style="display:inline-block; padding:14px 28px; background:#5E35E0; color:#ffffff; border-radius:10px; text-decoration:none; font-size:15px; font-weight:700;">
                    Trouver mes partenaires maintenant →
                  </a>
                </div>
                <p style="margin-top:28px; font-size:13px; color:rgba(255,255,255,0.35); text-align:center; line-height:1.6;">
                  Une question ? <a href="mailto:contact@usepartnerr.com" style="color:rgba(255,255,255,0.5); text-decoration:none;">contact@usepartnerr.com</a>
                </p>
              </div>
            </div>
            """
        })
        print(f"[EMAIL] Envoi réussi à {email}", flush=True)
    except Exception as e:
        print(f"[EMAIL] Erreur : {e}", flush=True)


@app.route("/register", methods=["POST"])
def register():
    email = request.form.get("email", "").strip().lower()
    prenom = request.form.get("prenom", "").strip()
    if not email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return redirect("/")
    users = load_users()
    is_new = email not in users
    if is_new:
        users[email] = {"plan": "free", "credits": 1, "prenom": prenom}
        save_users(users)
        send_welcome_email(email, prenom)
    return redirect(f"/app?email={email}")


@app.route("/favicon.svg")
def favicon():
    from flask import send_file
    return send_file("favicon.svg", mimetype="image/svg+xml")


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


@app.route("/check-email", methods=["POST"])
def check_email():
    email = request.form.get("email", "").strip().lower()
    if not email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({"known": False})
    users = load_users()
    history = load_history()
    if email not in users:
        return jsonify({"known": False})
    searches = len(history.get(email, []))
    return jsonify({"known": True, "searches": searches})


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
    exclude_manual  = request.form.get("exclude_manual", "").strip()

    if not company_name or not theme or not user_email:
        return "Veuillez remplir tous les champs obligatoires.", 400

    # Vérification + décrémentation atomique (protège contre les requêtes simultanées)
    plan, credits = atomic_decrement_credits(user_email)
    if plan is None:
        return "Vous n'avez plus de recherches disponibles. Passez à un plan supérieur pour continuer.", 403

    # Nombre de partenaires selon le plan réel
    if plan == "free":
        n_partners = 2
    elif plan == "starter":
        n_partners = 3
    else:  # growth, scale
        n_partners = 5

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
            print(f"[DEDUP] Recherche pour email={user_email!r} — exclus: {excluded}", flush=True)

            user_message = f"""Boîte à analyser : {company_name}
Secteur : {sectors_str}
Clients cibles : {clients_str}
Taille : {size}
Secteurs partenaires recherchés : {partners_str}
Zone géographique cible : {geo}
Thématique : {theme}{context_line}{excluded_line}

{f"⛔ INTERDIT : Ne propose JAMAIS les boîtes suivantes, même si elles semblent pertinentes : {', '.join(excluded)}. Propose UNIQUEMENT des boîtes que tu n'as jamais proposées à cet utilisateur." if excluded else ""}

Lance une recherche web sur "{company_name}" pour enrichir ton analyse, puis trouve {n_partners} partenaires B2B qualifiés selon les règles. Oriente tes recherches vers les secteurs partenaires indiqués. Les partenaires proposés doivent être basés ou actifs en priorité dans la zone géographique suivante : {geo}.

⚠️ QUALITÉ OBLIGATOIRE : Pour chaque partenaire proposé, vérifie qu'il existe une présence en ligne cohérente et récente (site web fonctionnel, activité visible, actualités récentes). Si l'activité d'une entreprise est incertaine, douteuse ou introuvable en ligne, ne la propose pas et choisis une alternative active et vérifiable.

FORMAT OBLIGATOIRE — respecte exactement cette structure pour chaque partenaire :

## Partenaire [N] : [Nom de l'entreprise]
🔗 [URL du site]
**Secteur :** [secteur]
**Contact recommandé :** [Rôle exact, ex : Head of Partnerships (LinkedIn)]
**Traction :** [MAXIMUM 6 MOTS AU TOTAL. Mots-clés uniquement, séparés par " • ". Zéro verbe, zéro phrase, zéro explication. Exemple exact : "50k clients • partenaires actifs". Si rien : "Données non visibles".]

**Opportunité :** [1 phrase, très courte, orientée levier business. Pas de contexte, pas d'historique, pas de description d'entreprise. Aller droit au but. Exemple : "Accélérer la digitalisation des chantiers via un partenaire IT déjà implanté chez les grands comptes."]

**Pourquoi ça matche :** [1 phrase maximum — uniquement la complémentarité principale. Supprimer tout détail secondaire, chiffre long ou description d'entreprise. Exemple : "Même cible grands comptes + expertise terrain sur la transformation digitale."]

**Action recommandée :**
1. [Recommandé] [Premier angle — court et concret. Cet angle est à lancer en priorité.]
2. [Deuxième angle — différent du premier.]
3. [Troisième angle.]

**Partenariats :** [Choisir UN seul parmi : 🤝 Actifs (uniquement si preuve claire : page partenaires, programme partenaire, cas client public, co-marketing visible, intégrations listées) / 👀 Non visibles (aucune preuve trouvée) / ❓ Inconnu (données insuffisantes)]

---

Ne mentionne jamais d'outil, de plateforme ou de technologie qui génère ces résultats. Présente chaque partenaire comme une opportunité business directement exploitable.

STRUCTURE OBLIGATOIRE : Commence DIRECTEMENT par ## Partenaire 1. Pas de phrase d'introduction, pas de résumé, pas de conclusion, pas d'étape numérotée, pas de contexte avant les partenaires. Rien avant ## Partenaire 1.

STYLE D'ÉCRITURE OBLIGATOIRE : N'utilise jamais de tiret long (—). Reformule les phrases pour qu'elles soient fluides et naturelles avec des virgules ou des points. Exemple à éviter : "Shine cible les PME — le segment clé de Boxtal". À écrire à la place : "Shine cible les PME, soit le segment clé de Boxtal." ou "Shine cible les PME. C'est précisément le segment clé de Boxtal." """

            def save_results():
                from datetime import datetime, timezone
                # Regex flexible : ##/# Partenaire N : / — / – nom
                names = re.findall(r'#{1,3}\s*Partenaire\s+\d+\s*[:\-–—]\s*(.+)', accumulated_text, re.IGNORECASE)
                names = [re.split(r'[✓✗\n|·—\*]', n)[0].strip() for n in names if n.strip()]
                names = [n for n in names if n]
                print(f"[DEDUP] save_results() — email={user_email!r} — noms extraits: {names}", flush=True)
                print(f"[DEDUP] Début accumulated_text: {accumulated_text[:300]!r}", flush=True)
                if names and user_email:
                    save_history(user_email, names)
                    print(f"[DEDUP] Sauvegardé dans history.json pour {user_email}", flush=True)
                else:
                    print(f"[DEDUP] RIEN sauvegardé — names={names!r} user_email={user_email!r}", flush=True)
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
                    if re.search(re.escape(name), accumulated_text, re.IGNORECASE):
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
            print(f"[ERROR] {str(e)}", flush=True)
            append_log({"date": __import__('datetime').datetime.utcnow().isoformat(), "email": user_email, "company": company_name, "plan": plan, "status": "error", "error": str(e)})
            yield f"data: {json.dumps({'error': 'Une erreur inattendue est survenue. Réessaie dans quelques instants.'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    plan = request.form.get("plan", "").strip().lower()
    email = request.form.get("email", "").strip().lower()
    price_id = STRIPE_PRICES.get(plan)
    if not price_id:
        return "Plan invalide.", 400
    base_url = request.host_url.rstrip("/")
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="payment",
        customer_email=email if email else None,
        metadata={"plan": plan, "email": email},
        success_url=f"{base_url}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/#pricing",
    )
    return redirect(session.url, code=303)


@app.route("/webhook", methods=["POST"])
def webhook():
    if not STRIPE_WEBHOOK_SECRET:
        return "Webhook secret non configuré.", 500
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return "Signature invalide.", 400

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        email = (session_data.get("customer_email") or
                 session_data.get("metadata", {}).get("email", "")).strip().lower()
        plan = session_data.get("metadata", {}).get("plan", "starter")
        if email and plan in PLAN_CREDITS:
            users = load_users()
            existing = users.get(email, {})
            users[email] = {
                "plan": PLAN_CREDITS[plan]["plan"],
                "credits": existing.get("credits", 0) + PLAN_CREDITS[plan]["credits"],
            }
            save_users(users)
    return jsonify({"status": "ok"})


@app.route("/my-history", methods=["POST"])
def my_history():
    email = request.form.get("email", "").strip().lower()
    if not email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({"searches": []})
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
    user_logs = [
        l for l in logs
        if l.get("email") == email and l.get("status") == "success" and l.get("partners")
    ]
    user_logs.sort(key=lambda x: x.get("date", ""), reverse=True)
    return jsonify({"searches": user_logs[:20]})




@app.route("/success")
def success():
    with open("success.html", encoding="utf-8") as f:
        return f.read()


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
