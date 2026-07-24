# Frontend source map (`frontend/src/`)

React single-page app. Components render UI; all backend access goes through
`lib/`; annotation edits go through `store/history.js` so undo/redo and live
sync happen automatically.

| Path | What lives here |
|---|---|
| `main.jsx` | Routes (React Router). Gates `/admin/*` to admins. |
| `App.jsx` | App shell — header, role-aware nav, forced password-change modal. |
| `lib/auth.js` | Session: JWT storage, cached current user, `isAdmin()`, `login()`, `logout()`. |
| `lib/collab.js` | The live-collaboration WebSocket client (connect, notifyChange, presence, auto-reconnect). |
| `lib/api/client.js` | Every REST call — one small wrapper function per backend endpoint. |
| `store/editor.js` | In-memory editor state (viewport, active tool, annotations, selection, drafts). |
| `store/history.js` | Undo/redo command stack — **and the single place annotations are saved to the API** (also pings the collab socket). |
| `utils/` | Pure helpers: `geometry.js`, `colors.js`, `rle.js` (mask encoding). |
| `components/auth/` | `LoginPage`, `ChangePasswordModal`. |
| `components/projects/` | `ProjectList` (project browser + admin members panel), `VersionsPanel`. |
| `components/annotate/` | The annotation workspace: `AnnotateView` (orchestrator), `canvas/` (Konva drawing surface + editable shapes), review bar, gallery sidebar, tool docks, magnifier. |
| `components/admin/` | `AdminDashboard`, `UserManagement`, `ActivityFeed`, `ProjectMembersPanel`. |
| `components/common/` | Shared widgets (`ApiStatusBanner`, `ToolTipButton`). |

Role-dependent UI reads `isAdmin()`; the backend enforces the same rules, so a
hidden button is convenience, not security. Full walkthrough in
`../../ARCHITECTURE.md`.
