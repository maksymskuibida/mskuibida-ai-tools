# What the mod UI API offers that our plugins do not use yet

Source: the `plugin-authoring` reference and the API types written by Claude Code 2.1.330
(`claude-code.d.ts`). Everything below is stated there; nothing here was run in the desktop app. "Used" means
used by one of this repository's mods today (`project-panel`, `question-forms`, `review-findings`, `model-fit`,
`unit-claim`).

## What we use

`$.ui.open` / `$.ui.panes` / `$.ui.close` and the `ui.close` event, `ui.render` on `Pane`, `AbovePrompt` and
`AskUserQuestion`, `ui.press`, `$.ui.resolve`, `$.ui.invalidate`, `$.ui.toast`, `$.ui.status`, `$.ui.ask`,
`Box`, `Text`, `Button`, `Link`, `Svg` (rings), `atom` / `read` / `update`.

## Not used yet

### Surfaces

| Surface | What it is | How we could use it |
| --- | --- | --- |
| `Pane` `placement` (`dock`, `inline`, `widget`) and `anchoredEdges` | Where the surface seated the pane. On the desktop app `widget` is the small form of a minimized pane; clicks may not reach it. The hook runs again when the seat changes. | project-panel 0.30.0 draws a glance (title and progress) as a widget; a full view docked. Other panes (a review board) could do the same. |
| `$.ui.open({ placement: 'widget' })` | Asks to start as a widget; ignored where there are none. | Start the panel minimized for people who want a glance, behind an option. |
| `$.ui.open({ rows, columns, backgroundColor, focus, closeOnEscape, holdToasts })` | Pane size, background paint, keyboard focus, dialog behaviour. | A short dialog pane (rows) instead of a long `AskUserQuestion` tree for choices that do not belong to a question. |
| `UiPane.isShown`, `isFocused` | Which pane shows (others are tabs) and whether it holds the keys. | project-panel 0.30.0 pauses polling unless the pane is placed **and** shown. |
| `$.ui.status(text)` | One pinned status line per plugin under the prompt, beside the engine's own notices; first 2000 characters; `undefined` clears. | project-panel 0.30.0 pins the plan title and progress while its pane is closed, as the fallback for the bar. model-fit already uses it for "checking". |
| `AbovePrompt` props `isCollapsed`, `isWorking`, `maxRows`, `bodyColumns`, `scroll` | The band is collapsible (ctrl+x ctrl+a); a collapsed band draws nothing; it scrolls past `maxRows`. | Yield when `isCollapsed`; size a table to `bodyColumns`; say less while `isWorking`. |
| `AbovePromptList` | Hides or orders all plugins' band rows. | Keep our bar under the engine's own rows, or hide a stale one. |
| `SessionMode` | The dim mode labels at the right of the prompt footer (terminal and desktop). A hook adds a label by rewriting `modes`. | A one-word mode ("panel off", "forms on") instead of a bar. |
| `PromptHint` | The hint line under the prompt; `hint` rewrites it, `tail` appends (terminal, desktop, mobile). | Append a short hint ("/panel to reopen"). |
| `Placed` and `$.ui.place({ id })` | A row of ours placed at the transcript's end, scrolling with the conversation. | A result card (review findings, gate verdict) kept in the flow. |
| `ToolUse` / `ToolResult` / `ToolGroup` / `CommandOutput` render sites | A tree on or under a tool call's row; mobile draws a card when the Box has `borderStyle` or `backgroundColor`. `CommandOutput` draws a slash command's `text` as a tree. | `/panel` could answer with a card instead of a line; aidlc tool calls could show their stage. |
| `UserMessage`, `AssistantMessage`, `AgentRow`, `Spinner`, `TurnDuration` | More transcript sites a `ui.render` hook can draw or decorate. | Mark a message that came from a gate answer; show the Unit on an agent row. |
| `ContextMenu` | Rows in the desktop right-click menu; `e.props` says the row, link, selection or code under the pointer. | "Open in panel" on a ticket id or stage link. |
| `Backdrop` and `$.theme.set` (`colors`, `backdrop`, `sound`, `style`, `overrideColorScheme`) | A whole look for the desktop and mobile apps; `make-colors.js` builds the colour table from a few anchors; `style` restyles message bubbles and type. | Not for these plugins (a theme belongs to the person); useful to know what the app's own tokens are. |
| `$.ui.notify` / `cancelNotify` | A host notification with a key. | A Unit finishing or a gate waiting while the window is in the background. |
| `$.ui.scroll`, `$.ui.focus`, `ui.focus`, `ui.pointer` | Scroll a pane or band, move the focus ring, hear it move. | Jump the panel to Needs attention when a gate opens. |

### Elements

| Element | What it offers | How we could use it |
| --- | --- | --- |
| `Progress` | A bar with `label` and `valueText`. | Stage and Unit progress in place of hand-drawn glyph bars. |
| `Markdown` | Markdown with pressable links (desktop, vscode, mobile draw it; the terminal refuses it inside `AskUserQuestion`). | Finding and gate summaries with real formatting. |
| `Code` (`format: 'diff'`, `startLine`, `language`, `path`) | Highlighted code or a diff; a bad diff falls back to plain code. | Show a finding's patch in the review board. |
| `Image`, `Raster`, `Shader` | Images by key, pixel buffers, a shader. | A mini burndown as a `Raster`; not needed for a panel. |
| `Input`, `Select` | Typed fields and option lists inside a tree, with values in their own room. | Filter the panel's items; pick the Unit to show. |
| `Client` | A surface module that draws with its own state (unmounts past tree limits). | A chart that animates; only where `Svg` is not enough. |
| `Box` `hover`, `position: 'absolute'`, `key` scopes | Hover styles, a card that appears over rows without moving them, hover `scope` across sites. | A hover card with an item's detail instead of expanding the row. |
| `Text` `hover`, `wrap` modes, `dimColor` | Hover text and truncation modes. | Already partly used. |
| `Button` `hotkey`, `action` | A digit or letter presses the Button while its site holds the keys; `action: 'app:...'` ties it to a keybinding chord. | `1`/`2`/`3` on a gate card's Approve, Request changes, Test first. |
| Theme tokens in props (`color="subtle"`, `backgroundColor="surface-1"`) | Named colours follow light and dark; a raw hex does not. | Prefer tokens over raw hex in `Svg` and `Box` for dark mode. |

### Events and calls

| Item | What it offers | How we could use it |
| --- | --- | --- |
| `ui.close` `origin.kind` (`plugin`, `person`, `unload`) | Who closed the pane; a hook answering without `next` keeps it open except on `unload`. | Already used; a hook could refuse a close while a gate is open. |
| `ui.open` hook | Can answer `{ value: { isPlaced: false, reason } }`; a test stand-in for a narrow terminal. | Tests for placement without a real surface. |
| `session.attach` and `$.session.surfaces()` | A surface joining later, and which are attached. | Already used for the desktop. |
| `$.clock.every` / `after`, `$.fs`, `$.process`, `$.model.complete` / `fork`, `$.store`, `$.state` | Timers, files, processes, model calls, cross-session store. | Already used except `$.store` (settings kept across sessions, e.g. the person's folds) and `$.model.fork` (a cached-prefix question). |
| `claude plugin test`, `mount`, `find`, `press` | Component tests without a surface. | Already used. |

## Where our code diverges from the reference

* `types/index.d.ts` of project-panel and model-fit hold each plugin's own contract (`PluginState`), not a copy of
  the API: the engine writes the API types to `.claude-plugin/types/` when a mod loads, and each `tsconfig.json`
  includes that folder. There is nothing to copy.
* A pane's "open" is not "on screen": `UiPane.isPlaced` is true while the pane is docked, inline **or** a widget,
  and `isShown` tells whether it is the one in front. Treat on screen as both.
* The band row for `AbovePrompt` can be collapsed by the person; a collapsed band draws nothing, and the status
  line (`$.ui.status`) is the surface that stays.
