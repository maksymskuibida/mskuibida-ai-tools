# Functional Specification — U2 Pick-up slots (`u2-pickup-slots`)

## Slot Rules

| ID | Rule | Source |
|---|---|---|
| SR1 | **Slots.** The day runs from 07:00 to 10:00 in slots of 15 minutes. | FR2.1 |
| SR2 | **Full slots.** A slot with eight orders is shown full and cannot be picked. | FR2.2; Q2 |
| SR3 | **Moving an order.** A customer may move an order to another free slot until 21:00 the evening before. | Q1 |

## Workflows

### WF1 Picking a slot

1. The customer opens the slot list and picks a free slot (SR1, SR2).

## Assumptions & Open Questions

- [assumption] The bakery's clock is the server's clock; a customer in another time zone sees the bakery's times (SR1).
- [assumption] Eight orders per slot is the same every day; a busier Saturday comes later (SR2).
