"""
agents.py — Load agent definitions (JSON metadata + Markdown system prompt).
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Agent:
    id: str
    name: str
    role: str
    config: Dict
    system_prompt: Optional[str] = None
    allowed_intents_emit: List[str] = field(default_factory=list)

    @property
    def has_prompt(self) -> bool:
        return self.system_prompt is not None and len(self.system_prompt.strip()) > 0


def load_agents(agents_dir: str = "agents") -> Dict[str, Agent]:
    """
    Walk agents/, load each *.json plus its sibling *.system_prompt.md if present.
    Returns dict mapping agent_id -> Agent.
    """
    agents_path = Path(agents_dir)
    if not agents_path.exists():
        raise FileNotFoundError(f"Agents directory not found: {agents_dir}")

    agents: Dict[str, Agent] = {}
    for json_file in sorted(agents_path.glob("*.json")):
        with json_file.open("r", encoding="utf-8") as f:
            config = json.load(f)
        agent_id = config["id"]

        # Look for sibling system prompt: ceo_agent.json -> ceo_agent.system_prompt.md
        prompt_file = json_file.with_suffix("").with_suffix(".system_prompt.md")
        # Path.with_suffix only operates on final suffix; build manually:
        prompt_file = agents_path / (json_file.stem + ".system_prompt.md")
        system_prompt = None
        if prompt_file.exists():
            with prompt_file.open("r", encoding="utf-8") as f:
                system_prompt = f.read()

        agents[agent_id] = Agent(
            id=agent_id,
            name=config.get("name", agent_id),
            role=config.get("role", ""),
            config=config,
            system_prompt=system_prompt,
        )
    return agents


def list_loaded(agents: Dict[str, Agent]) -> str:
    lines = []
    for aid, a in sorted(agents.items()):
        marker = "✓ prompt" if a.has_prompt else "○ no prompt"
        lines.append(f"  {marker}  {aid}  ({a.name})")
    return "\n".join(lines)
