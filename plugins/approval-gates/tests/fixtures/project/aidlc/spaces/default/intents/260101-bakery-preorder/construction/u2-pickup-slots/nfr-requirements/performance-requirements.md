# Performance Requirements — U2 Pick-up slots (`u2-pickup-slots`)

## Targets

| ID | Requirement | Measure (pass/fail) | Source |
|---|---|---|---|
| NFR1.1 | The slot list opens at once | Within 200 ms at the 95th percentile of 20 openings | NFR3 |

## Assumptions & Open Questions

- [assumption] Twelve slots a day is the most the list will hold, so it is never paged (NFR1.1).
