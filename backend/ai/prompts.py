"""
Audience-adaptive documentation prompts.

This module defines prompts for generating documentation tailored to different
audiences and purposes. The key insight: documentation should adapt to WHO is
reading it and WHY they're reading it.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


class AudienceType(str, Enum):
    """Types of documentation audiences."""
    TRADITIONAL = "traditional"  # Classic wiki-style docs
    NEW_ENGINEER = "new_engineer"  # New team member onboarding
    ONCALL = "oncall"  # On-call engineer debugging
    ARCHITECT = "architect"  # System architect reviewing design
    CONTRIBUTOR = "contributor"  # External contributor wanting to add code
    CUSTOM = "custom"  # Custom purpose described by user


@dataclass
class AudienceContext:
    """Context about the documentation reader."""
    audience_type: AudienceType
    role: Optional[str] = None  # e.g., "AI engineer", "backend developer"
    team: Optional[str] = None  # e.g., "inference team"
    purpose: Optional[str] = None  # e.g., "understand the ETL pipeline"
    custom_context: Optional[str] = None  # Free-form description


# =============================================================================
# System Prompts for Different Audiences
# =============================================================================

SYSTEM_PROMPTS = {
    AudienceType.TRADITIONAL: """You are a technical documentation expert creating clear,
comprehensive wiki-style documentation. Write documentation that:
- Is well-structured with clear headings and sections
- Covers all aspects: overview, components, usage, APIs, configuration
- Uses consistent formatting and terminology
- Is reference-complete and can stand alone
- Follows standard documentation conventions""",

    AudienceType.NEW_ENGINEER: """You are an expert mentor helping a new team member
understand a codebase. Write documentation that:
- Starts with the BIG PICTURE before diving into details
- Uses a top-down approach: system → subsystems → components → details
- Explains the "why" behind architectural decisions
- Highlights what's most important to understand first
- Uses analogies and examples to clarify complex concepts
- Points out common gotchas and non-obvious behaviors
- Suggests a learning path through the codebase""",

    AudienceType.ONCALL: """You are helping an on-call engineer understand a system
for incident response. Write documentation that:
- Gets to the point FAST - what does this do?
- Shows the critical paths and failure modes
- Highlights dependencies and what can go wrong
- Includes troubleshooting steps and common issues
- Points to relevant logs, metrics, and alerts
- Shows how data flows through the system
- Identifies the "blast radius" of failures""",

    AudienceType.ARCHITECT: """You are documenting a system for architectural review.
Write documentation that:
- Focuses on system design and trade-offs
- Explains key architectural decisions and alternatives considered
- Shows component boundaries and interfaces
- Identifies scaling bottlenecks and limitations
- Discusses consistency, availability, and partition tolerance trade-offs
- Highlights technical debt and areas for improvement
- Maps to broader system architecture""",

    AudienceType.CONTRIBUTOR: """You are helping an external contributor understand how
to add features or fix bugs. Write documentation that:
- Shows how the code is organized and why
- Explains the development workflow and conventions
- Highlights extension points and plugin architecture
- Points to test patterns and how to add tests
- Identifies code owners and review processes
- Shows example PRs and common contribution patterns
- Lists prerequisites and setup instructions""",

    AudienceType.CUSTOM: """You are adapting documentation to a specific reader's needs.
Tailor your explanation based on their stated purpose and background.
Be concise but complete for their specific use case."""
}


# =============================================================================
# Document Generation Prompts
# =============================================================================

def get_traditional_prompt(
    context_summary: str,
    doc_type: str,
    repo_name: str,
) -> str:
    """Generate prompt for traditional wiki-style documentation."""
    return f"""Generate comprehensive documentation for this codebase.

Code locations found:
{context_summary}

Create a well-structured markdown document with:
# Title (appropriate for {doc_type})

## Overview
A clear, concise summary of what this code does and why it exists.

## Architecture
How the components fit together, with references like [1], [2] to specific files.

## Key Components
The main classes, functions, and modules with their purposes.

## Usage
How to use this code - API examples, configuration, etc.

## Dependencies
What this code depends on and what depends on it.

## Configuration
Any environment variables, config files, or settings.

Use [n] notation to reference specific code locations.
Repository: {repo_name}"""


def get_birds_eye_prompt(
    context_summary: str,
    role: str,
    team: str,
    repo_name: str,
) -> str:
    """Generate prompt for top-down birds-eye view documentation."""
    return f"""You're explaining this codebase to a {role} who just joined the {team}.
They need to understand how the whole system works, starting from the highest level.

Code locations found:
{context_summary}

Create documentation with this structure:

# Welcome to {repo_name}

## The Big Picture
Start with a one-paragraph summary a smart person could understand in 30 seconds.
What problem does this solve? What's the main idea?

## How It All Fits Together
A conceptual map of the system. Don't go into implementation details yet.
Use simple diagrams or bullet points showing the main components and data flow.

## Key Concepts You'll See Everywhere
The 3-5 most important concepts/patterns in this codebase that, once understood,
make everything else click.

## The Main Flows
Walk through 1-2 common user journeys or data flows end-to-end.
Reference specific files [n] but focus on the "story" not the code.

## Where to Go Next
Based on the {role} role, suggest which areas to explore first.

## Quick Reference
A cheat sheet of the most important files/classes and what they do.

Keep it engaging and accessible. This is their first day!
Use [n] notation to reference specific code locations."""


def get_oncall_prompt(
    context_summary: str,
    system_component: str,
    repo_name: str,
) -> str:
    """Generate prompt for on-call/incident-focused documentation."""
    return f"""You're creating documentation for an on-call engineer who needs to
understand the {system_component} system FAST because something might be broken.

Code locations found:
{context_summary}

Create documentation with this structure:

# {system_component} - On-Call Guide

## TL;DR (30-second overview)
What is this? What's the single most important thing to know?

## Critical Path
The main flow of data/requests. What MUST work for this to function?
Reference specific files [n].

## Common Failure Modes
What breaks most often? What are the symptoms?

## Dependencies
What external services/systems does this depend on?
What breaks if THIS breaks?

## Troubleshooting Steps
1. First, check...
2. If that's fine, look at...
3. Common fixes...

## Key Metrics & Logs
Where to look, what to grep for, what's normal vs concerning.

## Escalation
When to page someone else, who owns what.

Be direct and actionable. No fluff. Time is critical.
Use [n] notation to reference specific code locations.
Repository: {repo_name}"""


def get_custom_purpose_prompt(
    context_summary: str,
    user_context: str,
    repo_name: str,
) -> str:
    """Generate prompt for custom user-specified purpose."""
    return f"""Generate documentation tailored to this specific reader:

Reader's context: "{user_context}"

Code locations found:
{context_summary}

Create documentation that directly addresses their needs:
1. Start with what's most relevant to their stated purpose
2. Explain concepts they'd need based on their role/background
3. Skip details that aren't relevant to their use case
4. Provide actionable information they can use immediately
5. Suggest related areas they might want to explore

Be adaptive - if they're debugging, be concise and actionable.
If they're learning, be more explanatory. If they're evaluating,
focus on architecture and trade-offs.

Use [n] notation to reference specific code locations.
Repository: {repo_name}"""


# =============================================================================
# Style Presets for Documentation Generation
# =============================================================================

STYLE_PRESETS = {
    "concise": {
        "name": "Concise & Scannable",
        "description": "Brief bullet points, minimal prose. Easy to scan quickly.",
        "prompt_modifier": """Format for quick scanning:
- Use bullet points over paragraphs
- Keep explanations to 1-2 sentences max
- Bold key terms
- Use tables for comparisons
- No unnecessary context or history"""
    },
    "narrative": {
        "name": "Narrative & Educational",
        "description": "Story-like flow, explains the 'why', good for learning.",
        "prompt_modifier": """Write in an educational, narrative style:
- Explain the reasoning and history behind decisions
- Use analogies and real-world comparisons
- Build concepts progressively
- Include "why this matters" for each section
- Connect ideas to form a coherent story"""
    },
    "reference": {
        "name": "Reference Manual",
        "description": "Comprehensive, structured, API-complete. Good for looking things up.",
        "prompt_modifier": """Write as a complete reference manual:
- Exhaustively document all functions, classes, and methods
- Include full type signatures and parameters
- Document all edge cases and return values
- Use consistent formatting throughout
- Organized for lookup, not reading"""
    },
    "tutorial": {
        "name": "Tutorial & Examples",
        "description": "Step-by-step guides with lots of code examples.",
        "prompt_modifier": """Write as a hands-on tutorial:
- Start with "what you'll build/learn"
- Provide step-by-step instructions
- Include code examples for every concept
- Add "try it yourself" exercises
- Show expected outputs and common errors"""
    }
}


def get_style_modifier(style: str) -> str:
    """Get the prompt modifier for a documentation style."""
    if style in STYLE_PRESETS:
        return STYLE_PRESETS[style]["prompt_modifier"]
    return ""


def build_generation_prompt(
    audience: AudienceContext,
    context_summary: str,
    repo_name: str,
    doc_type: str = "overview",
    style: str = "narrative",
) -> tuple[str, str]:
    """
    Build system prompt and user prompt for documentation generation.

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    # Get base system prompt for audience
    system_prompt = SYSTEM_PROMPTS.get(
        audience.audience_type,
        SYSTEM_PROMPTS[AudienceType.TRADITIONAL]
    )

    # Add style modifier
    style_modifier = get_style_modifier(style)
    if style_modifier:
        system_prompt = f"{system_prompt}\n\n{style_modifier}"

    # Build user prompt based on audience type
    if audience.audience_type == AudienceType.TRADITIONAL:
        user_prompt = get_traditional_prompt(context_summary, doc_type, repo_name)

    elif audience.audience_type == AudienceType.NEW_ENGINEER:
        role = audience.role or "engineer"
        team = audience.team or "the team"
        user_prompt = get_birds_eye_prompt(context_summary, role, team, repo_name)

    elif audience.audience_type == AudienceType.ONCALL:
        component = audience.purpose or "this system"
        user_prompt = get_oncall_prompt(context_summary, component, repo_name)

    elif audience.audience_type == AudienceType.CUSTOM:
        user_prompt = get_custom_purpose_prompt(
            context_summary,
            audience.custom_context or audience.purpose or "understand this code",
            repo_name
        )

    else:
        # Default to traditional
        user_prompt = get_traditional_prompt(context_summary, doc_type, repo_name)

    return system_prompt, user_prompt


# =============================================================================
# Prompt Templates for Specific Documentation Tasks
# =============================================================================

def get_component_deep_dive_prompt(
    component_name: str,
    context_summary: str,
    parent_doc_summary: str,
) -> str:
    """Generate prompt for diving deeper into a specific component."""
    return f"""The reader was viewing high-level documentation and wants to dive deeper
into the "{component_name}" component.

High-level context they've already seen:
{parent_doc_summary}

Code locations for this component:
{context_summary}

Generate detailed documentation for {component_name} that:
1. Connects to what they already know from the overview
2. Goes deeper into implementation details
3. Explains the internal structure and key functions
4. Shows how to extend or modify this component
5. Lists gotchas and edge cases

Don't repeat the overview - assume they've read it. Go deeper.
Use [n] notation to reference specific code locations."""


def get_cross_reference_prompt(
    from_component: str,
    to_component: str,
    context_summary: str,
) -> str:
    """Generate prompt explaining how two components interact."""
    return f"""Explain how "{from_component}" and "{to_component}" work together.

Code locations:
{context_summary}

Create documentation showing:
1. The interface between these components
2. Data that flows between them
3. Who calls whom and when
4. Error handling across the boundary
5. Common patterns for their interaction

Focus on the relationship, not each component in isolation.
Use [n] notation to reference specific code locations."""
