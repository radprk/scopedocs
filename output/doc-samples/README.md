# Documentation Style Samples

Radha, here are 4 different documentation styles for you to review and compare. Each style serves a different purpose and audience.

## Quick Comparison

| Style | Best For | Personality |
|-------|----------|-------------|
| [Traditional Wiki](01-traditional-wiki.md) | Reference lookup, completeness | Formal, structured |
| [New Engineer Bird's Eye](02-new-engineer-birdsview.md) | Onboarding, learning | Friendly, conceptual |
| [On-Call Guide](03-oncall-guide.md) | Incidents, debugging | Direct, actionable |
| [Tutorial & Examples](04-tutorial-examples.md) | Hands-on learning | Step-by-step, practical |

## The Samples

### 1. Traditional Wiki Style
**File:** [01-traditional-wiki.md](01-traditional-wiki.md)

Classic reference documentation with:
- Comprehensive API reference tables
- Complete configuration docs
- File structure breakdowns
- Architecture diagrams

**Best for:** Engineers who know what they're looking for and need to look it up.

---

### 2. New Engineer Bird's Eye View
**File:** [02-new-engineer-birdsview.md](02-new-engineer-birdsview.md)

Top-down onboarding documentation with:
- "30-second summary" opening
- Conceptual explanations before implementation details
- "Key concepts that make everything click" section
- Suggested learning path
- Friendly, encouraging tone

**Best for:** First day on the job, understanding the big picture.

---

### 3. On-Call / Incident Response Guide
**File:** [03-oncall-guide.md](03-oncall-guide.md)

Quick-reference incident documentation with:
- TL;DR at the top
- Common failure modes and fixes
- Dependency graphs
- Copy-paste troubleshooting commands
- Escalation paths

**Best for:** 3am incidents, production debugging, time-sensitive situations.

---

### 4. Tutorial with Examples
**File:** [04-tutorial-examples.md](04-tutorial-examples.md)

Hands-on learning documentation with:
- Clear "what you'll build" objectives
- Step-by-step instructions
- Code examples for every concept
- "Try it yourself" sections
- Troubleshooting guide

**Best for:** Getting started, learning by doing.

---

## How This Works in ScopeDocs

When a user accesses documentation in ScopeDocs:

1. **They choose their context:**
   - "I'm new here" → Bird's Eye View
   - "Something broke" → On-Call Guide
   - "Show me traditional docs" → Wiki Style
   - "I want to describe my purpose" → Custom (we'll tailor it)

2. **They optionally describe more:**
   - "I'm an AI engineer on the inference team..."
   - "I need to understand the ETL pipeline..."

3. **We generate documentation tailored to them** using audience-specific prompts.

## Your Feedback Needed

After reviewing these samples, consider:

1. Which style resonates most with you?
2. What elements from multiple styles should we combine?
3. Are there missing sections or formats you'd want?
4. Should we adjust the tone of any style?

The prompts in `backend/ai/prompts.py` control all of this and can be tuned based on your feedback!

---

## Try It Live

Start the server and go to http://localhost:8000/docs to generate adaptive documentation for any indexed repository.

```bash
cd backend
uvicorn server:app --reload --port 8000
# Open http://localhost:8000/docs
```
