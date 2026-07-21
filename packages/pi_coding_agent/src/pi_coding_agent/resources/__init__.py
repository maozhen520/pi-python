"""Declarative resource discovery: skills, prompts, settings, trust, context."""

from pi_coding_agent.resources.context import load_project_context
from pi_coding_agent.resources.loader import LoadedResources, load_resources
from pi_coding_agent.resources.prompts import PromptTemplate, expand_prompt_template
from pi_coding_agent.resources.settings import (
    load_settings,
    load_trust,
    resolve_project_trust,
    save_trust,
)
from pi_coding_agent.resources.skills import Skill

__all__ = [
    "LoadedResources",
    "PromptTemplate",
    "Skill",
    "expand_prompt_template",
    "load_project_context",
    "load_resources",
    "load_settings",
    "load_trust",
    "resolve_project_trust",
    "save_trust",
]
