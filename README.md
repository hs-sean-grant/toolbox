# toolbox

A personal collection of small, self-contained, **company-agnostic** tools —
things that are useful anywhere and are deliberately kept separate from any
employer's work. Each tool lives in its own folder, ships with its own README,
and stands alone (clone the folder, follow its README, done).

Nothing here is tied to a specific company, codebase, or internal system.

## Tools

| Tool | What it does |
|------|--------------|
| [`cursor-usage/`](cursor-usage/) | Containerized dashboard + poller for your **personal Cursor usage** — period utilization, burn-rate, and a "how hot is today" heat gauge. Runs locally with your own `WorkosCursorSessionToken`; also exposes a documented `usage.json` you can pull into your own dashboard/agent. |

## Conventions

- **One folder per tool.** Self-contained; no cross-tool dependencies.
- **Secrets stay out of git.** Tools take credentials at runtime (env / mounted
  files), never baked into images or committed. Each tool's `.gitignore`
  excludes local `.env`, data dirs, and generated artifacts.
- **Prefer zero/standard dependencies** where practical, so a tool is easy to
  run and easy to read.

## License

[MIT](LICENSE) — use freely.
