#!/usr/bin/env python3
"""
Migration HubSpot — synchronise tous les contacts existants.
À lancer UNE FOIS depuis le Render Shell :
    python3 sync_hubspot_migration.py
"""
import json, os, time, urllib.request, urllib.error

HUBSPOT_TOKEN    = os.environ.get("HUBSPOT_TOKEN", "")
USERS_FILE       = os.environ.get("USERS_FILE",       "/data/users.json")
RESEAU_FILE      = os.environ.get("RESEAU_FILE",      "/data/reseau.json")
PACK_CONTEXT_FILE = os.environ.get("PACK_CONTEXT_FILE", "/data/pack_context.json")


def hubspot_upsert(email, properties):
    if not HUBSPOT_TOKEN or not email:
        return False
    try:
        payload = json.dumps({"properties": {**properties, "email": email}}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            data=payload,
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=8)
        print(f"  ✓ Créé       : {email}")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 409:
            try:
                search_payload = json.dumps({
                    "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
                    "properties": ["email"]
                }).encode("utf-8")
                search_req = urllib.request.Request(
                    "https://api.hubapi.com/crm/v3/objects/contacts/search",
                    data=search_payload,
                    headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
                    method="POST"
                )
                result = json.loads(urllib.request.urlopen(search_req, timeout=8).read())
                if result.get("results"):
                    contact_id = result["results"][0]["id"]
                    patch_payload = json.dumps({"properties": properties}).encode("utf-8")
                    patch_req = urllib.request.Request(
                        f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}",
                        data=patch_payload,
                        headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
                        method="PATCH"
                    )
                    urllib.request.urlopen(patch_req, timeout=8)
                    print(f"  ↻ Mis à jour : {email}")
                    return True
            except Exception as e2:
                print(f"  ✗ Erreur PATCH {email} : {e2}")
                return False
        print(f"  ✗ HTTP {e.code} pour {email}")
        return False
    except Exception as e:
        print(f"  ✗ Erreur {email} : {e}")
        return False


if not HUBSPOT_TOKEN:
    print("❌ HUBSPOT_TOKEN manquant.")
    exit(1)

total = 0

# ── 1. Utilisateurs de l'outil ──────────────────────────────
print("\n📦 UTILISATEURS OUTIL (users.json)")
if os.path.exists(USERS_FILE):
    users = json.load(open(USERS_FILE))
    for email, data in users.items():
        ok = hubspot_upsert(email, {
            "firstname": data.get("prenom", ""),
            "hs_lead_status": "NEW",
            "lifecyclestage": "lead"
        })
        if ok:
            total += 1
        time.sleep(0.12)
    print(f"  → {len(users)} traités")
else:
    print("  (fichier introuvable)")

# ── 2. Membres du réseau ─────────────────────────────────────
print("\n🌐 RÉSEAU PARTNERR (reseau.json)")
if os.path.exists(RESEAU_FILE):
    members = json.load(open(RESEAU_FILE))
    for m in members:
        email = m.get("email", "").strip().lower()
        if not email:
            continue
        ok = hubspot_upsert(email, {
            "jobtitle": m.get("role", m.get("poste", "")),
            "website": m.get("website", m.get("site", "")),
            "description": m.get("description", ""),
            "hs_lead_status": "NEW",
            "lifecyclestage": "lead"
        })
        if ok:
            total += 1
        time.sleep(0.12)
    print(f"  → {len(members)} traités")
else:
    print("  (fichier introuvable)")

# ── 3. Acheteurs de packs ────────────────────────────────────
print("\n💼 ACHETEURS PACKS (pack_context.json)")
if os.path.exists(PACK_CONTEXT_FILE):
    contexts = json.load(open(PACK_CONTEXT_FILE))
    for c in contexts:
        email = c.get("email", "").strip().lower()
        if not email:
            continue
        desc = f"Activité : {c.get('activite','')}\nCible : {c.get('cible','')}\nOffre : {c.get('offre','')}\nPartenariats : {c.get('partenariats','')}"
        ok = hubspot_upsert(email, {
            "jobtitle": c.get("poste", c.get("role", "")),
            "website": c.get("site", c.get("website", "")),
            "description": desc,
            "hs_lead_status": "NEW",
            "lifecyclestage": "lead"
        })
        if ok:
            total += 1
        time.sleep(0.12)
    print(f"  → {len(contexts)} traités")
else:
    print("  (fichier introuvable)")

print(f"\n✅ Migration terminée — {total} contacts synchronisés dans HubSpot.")
