# Code Summary — U2 Pick-up slots (`u2-pickup-slots`)

The slot list and moving an order, on branch `unit/u2-pickup-slots` in bakery-web, not pushed yet.

## Files Created and Changed

| Area | Files | What they do |
|---|---|---|
| Slot rules | `src/slots/rules.ts`, `move.ts` (+ tests) | The day's slots, full slots, and moving an order |
| Slot list | `src/slots/SlotList.tsx` (+ test) | The list a customer picks from |

## Deviations From the Plan

- **Moving closes at 20:00:** the baker asked for an hour more to plan the dough.

## Not Verified Here

- The 500 ms target on a real phone.
