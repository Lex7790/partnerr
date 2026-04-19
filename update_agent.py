"""
Met à jour le system prompt de l'agent existant.
Lance avec : python3 update_agent.py
"""

import anthropic
import os
from dotenv import load_dotenv
from setup_agent import SYSTEM_PROMPT

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
agent_id = os.environ.get("AGENT_ID")

print(f"🔄 Mise à jour de l'agent {agent_id}...")

agent = client.beta.agents.retrieve(agent_id=agent_id)

client.beta.agents.update(
    agent_id=agent_id,
    version=agent.version,
    system=SYSTEM_PROMPT,
)

print("✅ System prompt mis à jour !")
print("   Relance le serveur pour que les changements soient pris en compte.")
