"""
Outil d'administration Partnerr
Usage :
  python admin.py --email user@exemple.com     → voir toutes les recherches d'un email
  python admin.py --logs                        → voir les 20 dernières recherches
  python admin.py --credit user@exemple.com 2  → ajouter N crédits à un email
  python admin.py --set-plan user@exemple.com growth → changer le plan d'un email
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone

HISTORY_FILE = os.environ.get("HISTORY_FILE", "/data/history.json")
LOG_FILE     = os.environ.get("LOG_FILE",     "/data/logs.json")
USERS_FILE   = os.environ.get("USERS_FILE",   "/data/users.json")

PLAN_CREDITS = {"free": 1, "starter": 2, "growth": 3, "scale": 6}


def load_json(path):
    if not os.path.exists(path):
        return {} if path != LOG_FILE else []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def show_email(email):
    email = email.strip().lower()
    logs    = load_json(LOG_FILE)
    history = load_json(HISTORY_FILE)
    users   = load_json(USERS_FILE)

    print(f"\n{'='*55}")
    print(f"  Utilisateur : {email}")
    print(f"{'='*55}")

    # Plan et crédits
    user = users.get(email, {})
    plan    = user.get("plan", "free")
    credits = user.get("credits", PLAN_CREDITS.get(plan, 1))
    print(f"  Plan : {plan}  |  Crédits restants : {credits}")

    # Historique partenaires
    known = history.get(email, [])
    print(f"\n  Partenaires déjà proposés ({len(known)}) :")
    for p in known:
        print(f"    · {p}")

    # Recherches
    user_logs = [l for l in logs if l.get("email") == email]
    print(f"\n  Recherches ({len(user_logs)}) :")
    for l in user_logs:
        status = "✅" if l.get("status") == "success" else "❌"
        date   = l.get("date", "")[:16].replace("T", " ")
        co     = l.get("company", "?")
        n      = l.get("n_partners", 0)
        plan_l = l.get("plan", "?")
        print(f"    {status} {date}  {co}  ({n} partenaires, plan {plan_l})")
        if l.get("status") == "error":
            print(f"       Erreur : {l.get('error', '')}")
    print()


def show_logs(n=20):
    logs = load_json(LOG_FILE)
    recent = logs[-n:][::-1]
    print(f"\n{'='*55}")
    print(f"  {n} dernières recherches")
    print(f"{'='*55}")
    for l in recent:
        status = "✅" if l.get("status") == "success" else "❌"
        date   = l.get("date", "")[:16].replace("T", " ")
        email  = l.get("email", "?")
        co     = l.get("company", "?")
        n_p    = l.get("n_partners", 0)
        print(f"  {status} {date}  {email}  {co}  ({n_p} partenaires)")
    print()


def credit_user(email, amount):
    email = email.strip().lower()
    users = load_json(USERS_FILE)
    user  = users.get(email, {"plan": "free", "credits": 0})
    before = user.get("credits", 0)
    user["credits"] = before + amount
    users[email] = user
    save_json(USERS_FILE, users)
    print(f"\n  ✅ {email} : {before} → {user['credits']} crédits\n")


def set_plan(email, plan):
    email = email.strip().lower()
    if plan not in PLAN_CREDITS:
        print(f"  ❌ Plan invalide. Choisir parmi : {', '.join(PLAN_CREDITS)}")
        return
    users = load_json(USERS_FILE)
    user  = users.get(email, {})
    user["plan"]    = plan
    user["credits"] = PLAN_CREDITS[plan]
    users[email] = user
    save_json(USERS_FILE, users)
    print(f"\n  ✅ {email} → plan {plan}, {PLAN_CREDITS[plan]} crédits\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Admin Partnerr")
    parser.add_argument("--email",    help="Voir les infos d'un utilisateur")
    parser.add_argument("--logs",     action="store_true", help="20 dernières recherches")
    parser.add_argument("--credit",   nargs=2, metavar=("EMAIL", "N"), help="Ajouter N crédits")
    parser.add_argument("--set-plan", nargs=2, metavar=("EMAIL", "PLAN"), help="Changer le plan")
    args = parser.parse_args()

    if args.email:
        show_email(args.email)
    elif args.logs:
        show_logs()
    elif args.credit:
        credit_user(args.credit[0], int(args.credit[1]))
    elif args.set_plan:
        set_plan(args.set_plan[0], args.set_plan[1])
    else:
        parser.print_help()
