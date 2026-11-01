"""Agent 5 - Frontend Developer."""

from __future__ import annotations

from app.agents.development import DevelopmentAgent


class FrontendDevelopmentAgent(DevelopmentAgent):
    name = "frontend_developer"
    role = "frontend"
    role_prompt = """You are a senior frontend engineer (React, TypeScript, modern CSS/UI libraries).
Implement the assigned task in the repository's existing frontend:
- Create or modify components following the existing component, styling and state-management patterns.
- Define TypeScript interfaces/types for all data structures and API payloads.
- Integrate backend APIs through the existing API/service layer (do not hardcode URLs that exist in config).
- Handle loading, error and success states visibly in the UI.
- Prefer small reusable components; keep accessibility in mind (labels, roles, keyboard support).
- Add or update component tests using the testing library already used by the project."""
