# aidlc-ids: every id on every page is a link with a tooltip

The plugins' pages (approval gates, unit approvals, question forms, story points, and the review-findings board in
the question forms) show the ids of an AI-DLC project's documents: US1.1, AC1.1.2, FR1.4, NFR3, BR1.2, Q4, U31, C2,
E7, ADR-009, R-01 and the rest. On every page, every id is a link with a tooltip saying what it is, wherever it
appears: in prose, in a table, in a reference list, in a note.

- **Tooltip**: the kind, the id, its title and the start of its text, and the document it is written in, in plain
  words. It shows on hover and on keyboard focus.
- **The id is shown in the page**: the link jumps there, opening a closed section, and flashes it.
- **The id is not in the page**: still a link (dotted). A click shows a toast: it isn't in this page, and its tooltip
  says what it is.
- **An id no document defines**: a dashed link. Its tooltip and toast say it isn't defined in the project's documents.

## The pieces

| File | What it does | Where its copies go |
|---|---|---|
| `aidlc_ids.py` | `sync` reads the intent's Markdown and keeps the checkout's id map: each id's definitions (a heading, a bold lead, a table's first cell), rereading only the documents that changed. `refs` gives a page the ids its text mentions, one definition each. | `plugins/<plugin>/scripts/aidlc_ids.py` |
| `aidlc-ids.js` | The page side: `AidlcIds.observe(root, getIds, { toast })` turns every id in `root`'s text into a link, again after each render. | each page, between `/* aidlc-ids.js:begin */` and `:end */` |
| `aidlc-ids.css` | The links' look, from the page's own `--accent`, `--muted` and `--tip-bg` tokens. | each page, between `/* aidlc-ids.css:begin */` and `:end */` |

The map is the project's own and stays out of the project: `~/.claude/plugins/data/aidlc-ids/maps/<checkout>/<space>--<intent>.json`,
one per checkout, since a worktree's branch may hold other documents. Every plugin's copy reads and writes that one
folder (`AIDLC_IDS_DIR` moves it). The `aidlc-ids` plugin adds `/aidlc-ids:sync`, which syncs it without a model turn.

`scripts/sync-shared.py` writes the copies. `scripts/sync-shared.py --check` fails CI when a copy differs. Edit the
files here, never a plugin's copy, then run `scripts/sync-shared.py`.

## Which definition a page gets

The same id is defined in several places: every stage has its own Q1 and R-01, and every Unit its own BR1.1. `refs`
takes `--near`, the documents the page shows, and picks for each id:

1. a definition in one of those documents;
2. for intent-wide kinds (U, US, AC, FR, NFR, ADR, C, E), Inception's definition;
3. a heading over a bold lead over a table row;
4. the nearest folder.

It never picks a definition inside another Unit's folder (`construction/<other unit>/`), and never a Q or R from
another stage's folder. An id with no usable definition is left out of the map, and the page shows it as not defined.

## Wiring a plugin

1. `python3 scripts/sync-shared.py --add-page <the page>`, and `--add-python plugins/<plugin>/scripts` if the plugin
   writes the page's data.
2. **Writer.** Before building the page, run `aidlc_ids.py sync` (fast when nothing changed). Where the plugin (its
   script, or the agent following its skill) writes the page's data, run `aidlc_ids.py refs --text-file <all the text the page shows> --near <each document it shows>`. Store the map as
   `ids` in the page's data: `{"FR1.4": {"kind", "title", "text", "doc", "line"}}`. Document the field in the page's
   data contract.
3. **Page.**
   - Call `AidlcIds.observe(<the page's root>, () => <the ids map>, { toast: <the page's toast> })` once.
   - Put `data-aidlc-id="<id>"` on the element that shows an id's own definition (a requirement row, a story card, a
     question, a finding), so links to it are live.
   - Make sure the page's tooltip reads `data-tip` on hover and on focus.
   - Remove the page's own id matching once the shared one covers it, so ids are found one way everywhere.
4. Plain words stay the rule: write what something is, not its id, in a sentence. An id that does appear, in
   any text, becomes a link by itself.
