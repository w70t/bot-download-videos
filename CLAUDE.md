# CLAUDE.md

Rules and context for Claude (or any AI assistant) working in this repository. Follow strictly.

> Owner note: parts marked [FILL IN] are placeholders. First task for Claude in a new project: inspect the real repository files, fill these sections in accurately, and give me the updated file to commit. Do not invent anything — only write what the actual code shows.

## 1. Project overview
[FILL IN: one short paragraph — what this app is, who it is for, and its current stage.]

## 2. Tech stack
- Frontend: [FILL IN]
- Backend: [FILL IN]
- Database: [FILL IN]
- Auth: [FILL IN]
- Infrastructure / other: [FILL IN — Docker, CI, hosting, etc.]

## 3. Project structure
[FILL IN: key folders and files, and what each one is responsible for.]

## 4. Commands
- Install dependencies: [FILL IN]
- Run in development: [FILL IN]
- Run tests: [FILL IN]
- Build for production: [FILL IN]

## 5. Non-negotiable rules
1. Real functionality only. No placeholder buttons, no fake or mock data presented as real, no fake API calls, no TODO-stub "features." If something cannot be real yet (missing keys or services), state exactly what is missing, build the real code path anyway, and add a clearly labeled safe fallback.
2. Inspect before editing. Read the actual files first. Never assume a file, route, endpoint, table, column, package, or environment variable exists — verify it or ask the owner.
3. Never restart from scratch or rewrite the architecture without the owner's explicit approval.
4. Small incremental changes. One feature or fix at a time. Everything that already works must keep working. Never delete previous work without asking.
5. Honest verification. Never claim tests passed or a build succeeded without actually running it. If not run, say "Not run" and provide the exact commands.
6. Security. No secrets in code — use environment variables, keep .env in .gitignore, keep .env.example updated with placeholder values. Validate all input server-side, use parameterized queries, hash passwords properly.
7. Complete features only. Every feature includes the full real data flow (UI → API → database → UI), client and server validation, loading/empty/error/success states, and server-side permission checks where relevant.
8. Premium UI. Modern, clean, consistent spacing and typography, proper icon sets, subtle animations. Full RTL support and modern Arabic fonts on Arabic screens. No default or amateur-looking UI, no emoji-heavy design.

## 6. Definition of done
A task is done only when: the code path is fully real end to end, errors and edge cases are handled, nothing that previously worked is broken, no secrets were exposed, and the final report honestly states what was and was not verified.

## 7. End-of-task report format
Every task ends with: Implemented / Files changed / Tests-build result / How to run / Limitations.

## 8. Current status
- Working now: [FILL IN]
- In progress: [FILL IN]
- Next planned: [FILL IN]

Keep sections 1–4 and 8 updated as the project evolves.
