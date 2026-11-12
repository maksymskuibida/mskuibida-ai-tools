"""A synthetic bakery project for the map tests: Units Generation documents, components, a Unit Progress table and
receipts. Nothing here is a real project's data."""

import os

UNIT_OF_WORK = """# Units of Work

## Units

| Unit ID | Dir | Unit | Kind | Points | Wave |
|---|---|---|---|---|---|
| U1 | u1-core | Core: orders, loaves and the baker's list | service | 5 | 1 |
| U2 | u2-pickup-slots | Pick-up slots a customer can choose | service | 3 | 2 |
| U3 | u3-order-page | The page where a customer orders | ui | 5 | 3 |
| U4 | u4-baker-list | The baker's morning list | ui | 3 | 2 |

## Unit details

### U1 — u1-core

- **What it delivers:** Orders, loaves and the one list the baker prints. Everything else builds on it.
- **Kind:** service · **Points:** 5 · **Wave:** 1
"""

DEPENDENCY = """# Unit Dependencies

## Dependency DAG

```yaml
units:
  - name: u1-core
    kind: service
    depends_on: []
  - name: u2-pickup-slots
    kind: service
    depends_on: [u1-core]
  - name: u3-order-page
    kind: ui
    depends_on: [u1-core, u2-pickup-slots]
  - name: u4-baker-list
    kind: ui
    depends_on: [u1-core]
```

## Edges in words

| Unit | Needs | Why |
|---|---|---|
| U3 u3-order-page | U2 u2-pickup-slots | the page offers the slots the service lists |
"""

STORY_MAP = """# Story map

## Story to Unit

| Story | Unit ID | Dir |
|---|---|---|
| US1.1 | U1, U3 | u1-core, u3-order-page |
| US1.2 | U2 | u2-pickup-slots |
| US2.1 | U4 | u4-baker-list |
"""

STORIES = """# Stories

### US1.1 Order loaves for tomorrow
### US1.2 Choose a pick-up slot
### US2.1 See the morning list
### US3.1 Get a reminder
"""

COMPONENTS = """# Components

## Component catalogue

```yaml
components:
  - name: OrderService
    summary: Takes an order and keeps the loaves count for the day.
    behaviour: >
      Creates an order for a customer, checks the loaves left and stores it.
    responsibilities:
      - Create and cancel orders
      - Count loaves left
    depends_on:
      - component: SlotCalendar
        interaction: asks which slots are free
    dependents:
      - component: BakerList
        interaction: reads the orders of a day
    entities:
      - name: Order
      - name: Loaf
  - name: SlotCalendar
    summary: Knows which pick-up slots are open.
    behaviour: Lists the slots of a day.
    responsibilities: [Open and close slots]
    depends_on: []
    entities:
      - name: Slot
  - name: BakerList
    summary: Builds the baker's morning list.
    behaviour: One list, sorted by slot.
    responsibilities:
      - Group orders by slot
    depends_on: []
    entities:
      - name: Order
```
"""

STATE = """# AI-DLC State Tracking

## Current Status
- **Current Stage**: functional-design

## Unit Progress
<!-- Derived -->
| unit | owner | functional-design | code-generation | gate | merged |
| --- | --- | --- | --- | --- | --- |
| u1-core | max | [x] | [x] | [x] | [x] |
| u2-pickup-slots | max | [x] | [ ] | [ ] | [ ] |
| u3-order-page | | [ ] | [ ] | [ ] | [ ] |
| u4-baker-list | | [ ] | [ ] | [ ] | [ ] |
"""

AUDIT = """# Audit

## Unit Completed
**Timestamp**: 2026-01-02T09:00:00Z
**Event**: UNIT_COMPLETED
**Stage**: code-generation
**Unit**: u4-baker-list

---
"""

POINTS = "unit,points,source\nu1-core,5,human\nu2-pickup-slots,3,ai\nu3-order-page,8,human\nu4-baker-list,3,ai\n"


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_project(tmp, units=True, components=True, state=STATE, audit=AUDIT, points=True, intent="260101-bakery-preorder"):
    """A project folder with an active intent. Returns (project dir, intent root)."""
    project = os.path.join(tmp, "project")
    space = os.path.join(project, "aidlc", "spaces", "default", "intents")
    root = os.path.join(space, intent)
    put(os.path.join(project, "aidlc", "active-space"), "default\n")
    put(os.path.join(space, "active-intent"), intent + "\n")
    put(os.path.join(root, "aidlc-state.md"), state)
    if audit is not None:
        put(os.path.join(root, "audit", "session-a.md"), audit)
    if units:
        base = os.path.join(root, "inception", "units-generation")
        put(os.path.join(base, "unit-of-work.md"), UNIT_OF_WORK)
        put(os.path.join(base, "unit-of-work-dependency.md"), DEPENDENCY)
        put(os.path.join(base, "unit-of-work-story-map.md"), STORY_MAP)
        put(os.path.join(root, "inception", "user-stories", "stories.md"), STORIES)
        if points:
            put(os.path.join(root, "unit-points.csv"), POINTS)
    if components:
        put(os.path.join(root, "inception", "domain-design", "components.md"), COMPONENTS)
    return project, root
