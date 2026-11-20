# RunSummarizer — project conventions

## Logging

- `logging.getLogger(__name__)` under `app.*`, so a logger's name says where its lines
  come from; `%`-style arguments, not f-strings (ruff's `G` and `LOG` rules check
  this).
- Levels: DEBUG for timings and ignored events, INFO for state changes (an item
  imported, an account linked, a token refreshed), WARNING for expected failures (a
  provider paused, an item blocked or retried), ERROR for bugs and unhandled errors.
- No tokens, secrets, authorization codes or raw provider-response bodies in a log
  line — ids only. A request or webhook path goes through `redact_path` first.

## Comments

Comments describe the code, not the history or reasoning behind it.

- **Do** annotate what a value means when it isn't obvious from the code: value
  domains (`# 'strava' | 'garmin'`), formats (`# sha256 hex`), units, enum
  mappings (`# RunType id`), non-obvious mechanics.
- **Don't** put architectural rationale, trade-off deliberation, or migration
  history inline, and don't reference planning docs, decision IDs, or phase
  numbers (a comment that points at something outside the repo goes stale the
  moment that thing is gone).

## Commit messages

A conventional-commit subject (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)
that states, in one short line, what the commit introduces.

- **Do** keep it to that line. A commit spanning several changes may list them
  underneath, one short line each.
- **Don't** explain the reasoning: no rationale, trade-offs, alternatives
  considered, or migration history in the body, and no references to planning
  docs, decision IDs, or phase numbers.
