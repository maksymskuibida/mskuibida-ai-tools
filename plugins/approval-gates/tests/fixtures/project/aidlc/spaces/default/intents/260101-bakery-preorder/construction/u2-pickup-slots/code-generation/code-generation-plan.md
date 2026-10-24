# Code Generation Plan — U2 Pick-up slots (`u2-pickup-slots`)

## Summary

- Builds: the slot list with full slots marked, and moving an order to another slot.
- Touches: `bakery-web/` only.

## Steps

### Step 1: Project structure
- [ ] Create branch `unit/u2-pickup-slots` and the folder `src/slots/`.

### Step 2: Business logic — implement (slot rules)
- [ ] `src/slots/rules.ts`: the day's slots and which are full (SR1, SR2).
- [ ] `src/slots/move.ts`: moving an order until 21:00 the evening before (SR3).

### Step 3: Frontend behaviour — implement the slot list
- [ ] `src/slots/SlotList.tsx` and `src/text/en.json`: the list, full slots marked, and the text row R-02 of Functional Design asked for (SR2).

### Step 4: Frontend behaviour — write and run the slot list's tests
- [ ] `src/slots/SlotList.test.tsx`: a full slot cannot be picked; the list opens within 200 ms (NFR1.1).

## Story Traceability

- US1.1: Steps 2 and 3.

## Assumptions & Open Questions

- [assumption] The web app's router already has a page for one order, so moving an order needs no new address.
