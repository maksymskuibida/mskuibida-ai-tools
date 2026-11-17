# session-titles changelog

## 0.4.0

Every title starts with a short handle of its intent: `<handle>: <title>`, e.g. `rvdesk: u19-pr-actions — Code Generation`.

- The handle (at most 8 characters of `a-z0-9-`) is made once per intent by a Haiku agent at low effort from the intent's
  name and description, and cached in `<state folder>/intent-handles.json` by the intent's uuid, so every session of the
  intent shares it. Edit a value there to change a handle.
- An invalid reply or no answer gives a short form of the folder name (marked a fallback) and is retried after 10 minutes.
- The "changed" checks, the declined-rename memory and the mid-turn desktop rename all compare the prefixed title, so a
  session started earlier gets the prefix once and is not renamed in a loop. `AIDLC_SESSION_TITLES_HANDLE_CMD` overrides the command.

## 0.3.1

A session's title now follows the stage the checkout is on when it moves backward or sideways, not only forward.

- Cause: what the hook had already asked for, been declined, or blocked the turn for was remembered as one title and never
  forgotten, and a rename done mid-turn did not replace the title the harness was last given. A title the session came back to
  (`aidlc engine jump`, `jump reopen`, a redone stage, Request Changes, a Unit switch, a resumed session whose state changed)
  was taken for already handled, so the later stage's title stayed.
- Now: the title is derived from the stage the checkout is on now; when it differs from the previous one, the asked, declined and
  blocked memories are reset, and a rename the assistant makes also counts as the title in force for the next prompt.
- Unchanged: a title the person set by hand is still protected (a declined rename stays declined while the stage stays), the per-Unit
  and phase formats, the state folder and `CHECKOUT_SOURCE`.
