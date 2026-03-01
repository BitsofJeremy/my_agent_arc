# ARC Comprehensive Documentation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create complete user guide (`docs/guide.md`) and rewrite `README.md` as a clean project landing page.

**Architecture:** Two documents — a thorough 15-section guide covering everything from install to troubleshooting, and a concise README that links to it. Both derived from reading actual source code to ensure accuracy.

**Tech Stack:** Markdown documentation, no code changes.

---

### Task 1: Create `docs/guide.md` — Complete User Guide

**Files:**
- Create: `docs/guide.md`

**Content:** 15 sections covering: overview, quick start, config reference, Telegram setup, admin dashboard, agentic loop internals, context management, memory/RAG, built-in tools, MCP skill servers, self-authoring skills, personality customisation, triggers/scheduling, Linux deployment, and troubleshooting.

**Step 1:** Write the complete guide document from the codebase analysis already performed.

**Step 2:** Verify all env var names match `.env.example` and `config.py`.

**Step 3:** Verify all file paths match actual project structure.

---

### Task 2: Rewrite `README.md` — Project Landing Page

**Files:**
- Modify: `README.md`

**Content:** Brief tagline, architecture diagram, feature bullets, minimal quick start (5-6 steps), link to `docs/guide.md`, project tree, Built With section, Roadmap, License.

**Step 1:** Rewrite README with concise landing page format.

**Step 2:** Ensure architecture diagram matches existing one.

**Step 3:** Verify all links work (relative path to docs/guide.md).

---

### Task 3: Commit

```bash
git add docs/guide.md README.md
git commit -m "docs: add comprehensive user guide and rewrite README"
```
