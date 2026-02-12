---
version: "1.0"
type: memory
mutable: true
priority: 90
tags:
  - persistence
  - context
---
# Agent Memory

## User Facts

<slot id="user_facts" hint="Persistent player facts such as identity, builds, goals, and recurring preferences">
  <value>(not set)</value>
</slot>

## Session Summaries

<slot id="session_summaries" hint="Condensed summaries of completed conversations and decisions made">
  <value>(not set)</value>
</slot>

## Active Context

<slot id="active_context" hint="Current threads that should influence immediate follow-up recommendations">
  <value>(not set)</value>
</slot>

---
*Last updated: Never*
