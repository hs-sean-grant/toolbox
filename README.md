# toolbox

A personal collection of small, self-contained, **company-agnostic** tools —
things that are useful anywhere and are deliberately kept separate from any
employer's work. Each tool lives in its own folder, ships with its own README,
and stands alone (clone the folder, follow its README, done).

Nothing here is tied to a specific company, codebase, or internal system.

## Tools

Together, `cursor-usage` + `cursor-usage-bridge` are one **completely token-less**
solution for personal Cursor usage: the bridge fetches from your browser session,
the server transforms + serves a documented `usage.json`. No token is ever stored.

| Tool | What it does |
|------|--------------|
| [`cursor-usage/`](cursor-usage/) | **Token-less** ingest server + dashboard for **personal Cursor usage**. Accepts `POST /ingest`, exposes a documented `usage.json` for your own dashboards/agents. Runs bare or in Docker. |
| [`cursor-usage-bridge/`](cursor-usage-bridge/) | The **token-less** feeder — Chrome extension + bookmarklet that fetches usage from your logged-in cursor.com session and POSTs it to `cursor-usage`'s `/ingest` (or any compatible ingest endpoint). |

## Conventions

- **One folder per tool.** Self-contained; no cross-tool dependencies.
- **Secrets stay out of git.** Tools take credentials at runtime (env / mounted
  files), never baked into images or committed. Each tool's `.gitignore`
  excludes local `.env`, data dirs, and generated artifacts.
- **Prefer zero/standard dependencies** where practical, so a tool is easy to
  run and easy to read.

## License

[MIT](LICENSE) — use freely.
