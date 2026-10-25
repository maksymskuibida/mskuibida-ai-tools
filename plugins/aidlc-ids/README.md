# aidlc-ids

Every id an AI-DLC project's documents define (US1.1, AC1.1.2, FR1.4, NFR3, BR1.2, Q4, U31, C2, E7, ADR-009, R-01 and
the rest) becomes, on the plugins' pages, a link with a tooltip saying what it is. This plugin keeps the map those
pages read: for each id, its kind, its title, the start of its text and the document that defines it.

```
/aidlc-ids:sync            build the map, or bring it up to date (only changed documents are read again)
/aidlc-ids:sync --force    build it from scratch
```

The command runs without a model turn, so it costs no tokens. Agents run the same script before they build a page:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc_ids.py" sync
```

The map is kept outside the project, in `~/.claude/plugins/data/aidlc-ids/maps/<checkout>/<space>--<intent>.json`:
one per checkout, as a worktree's branch may hold other documents. `AIDLC_IDS_DIR` moves the folder. Nothing of a
project is in the plugin.

The plugins that draw pages (approval-gates, question-forms, story-points, review-findings) carry their own copy of
the script, so they work without this plugin; the map they read and write is the same file. How a page uses it, and
which of several definitions of an id it gets (every stage has its own Q1, every Unit its own BR1.1), is in
[`shared/aidlc-ids/README.md`](../../shared/aidlc-ids/README.md).

## Install

```bash
claude plugin marketplace add maksymskuibida/mskuibida-ai-tools
claude plugin install aidlc-ids@mskuibida-tooling
```

## Tests

```bash
python3 -m unittest scripts/tests/test_sync_shared.py
claude plugin test plugins/aidlc-ids
```
