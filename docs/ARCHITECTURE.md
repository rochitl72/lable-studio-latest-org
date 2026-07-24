# RBG Annotation Studio — Architecture Guide

A walkthrough of how the project is put together and how a request flows through
it, written so someone new to the codebase can find their way around.

---

## 1. The big picture

Three moving parts:

```
   Browser (React SPA)                FastAPI backend (Python)          PostgreSQL
 ┌──────────────────────┐   HTTPS   ┌───────────────────────────┐    ┌──────────┐
 │  components + stores  │◀────────▶│  api routers → services   │◀──▶│  tables  │
 │  (annotate, admin…)   │   REST    │  auth · RBAC · membership │    │          │
 │                       │◀────────▶│  WebSocket (live co-edit) │    └──────────┘
 └──────────────────────┘    WS     └───────────────────────────┘
                                              │ files on disk
                                              ▼
                                     STORAGE_DIR/project_{id}/{xx}/{uuid}.ext
```

- **Structured data** (users, projects, annotations, memberships, audit log,
  dataset versions) lives in **PostgreSQL**.
- **Image files** live on the **server's disk**, referenced by path in the DB.
- The **backend** is Python/FastAPI: it owns authentication, role-based access,
  project membership, and all persistence.
- The **frontend** is a React single-page app that talks to the backend over
  REST for everything, plus one WebSocket per open image for live collaboration.

In production the built frontend is served by the same FastAPI process (see
`backend/app/main.py`), so the whole thing runs on one port.

---

## 2. Backend layout (`backend/app/`)

The backend is organised in layers. A request flows top-to-bottom:

```
main.py                     app assembly: mounts routers, applies the auth guard
│
├── api/                    HTTP endpoints, grouped by domain
│   ├── auth/               login, logout, me, register, change-password (auth.py)
│   │                       admin user management (users.py)
│   ├── workspace/          the core annotation loop
│   │                       projects.py  — projects, labels, membership
│   │                       images.py    — upload / list / serve image files
│   │                       annotations.py — annotation CRUD (+ ownership rules)
│   ├── dataset/            everything about the dataset as an output
│   │                       versions.py  — snapshot/fork/freeze
│   │                       splits.py    — train/val/test assignment
│   │                       workflow.py  — image status + review decisions
│   │                       export.py    — COCO / YOLO / folder export
│   ├── collaboration/      real-time + presence
│   │                       ws.py        — WebSocket rooms (live co-editing)
│   │                       locks.py     — legacy soft-lock endpoints (unused by
│   │                                      the live-edit path; kept for reference)
│   └── admin/              admin-only monitoring
│                           dashboard.py — progress / velocity / quality metrics
│                           activity.py  — audit-log feed & search
│
├── core/                   cross-cutting configuration & security
│   ├── config.py           all settings (env-driven); fails loudly in production
│   └── security.py         password hashing, JWT, current_user, require_role gates
│
├── db/                     database plumbing
│   ├── database.py         async engine + session, create_all on startup
│   └── bootstrap.py        seeds the first admin on an empty database
│
├── models/                 SQLAlchemy ORM models (the schema, in one file)
│   └── models.py           User, Project, Image, Annotation, ProjectMember,
│                           ActivityLog, DatasetVersion, ImageLock, Role, Action
│
├── services/               reusable business logic (no HTTP here)
│   ├── membership.py       "may this user access this project?"
│   ├── activity.py         audit-log recorder (record() called on every mutation)
│   ├── metrics.py          IoU / inter-annotator agreement math
│   └── export/             dataset export formats (COCO, YOLO, overlays, RLE)
│
└── alembic/                database migrations (versions/*.py)
```

**Why grouped this way:** each `api/` subpackage is one domain you can reason
about in isolation. Endpoints depend *downward* only — on `core`, `db`,
`models`, and `services` — never sideways on each other (the one exception,
`auth.py` reusing `users.create_user_row`, is within the same subpackage).

---

## 3. How authentication & roles work

This is the part you'll touch most, so here it is end to end.

1. **Login** (`api/auth/auth.py` → `/api/auth/login`). The password is checked
   against the bcrypt hash in the `users` table (`core/security.authenticate`).
   On success the server issues a **JWT** carrying the user id and role, and
   also sets it as an httpOnly cookie (the cookie exists only so `<img>` tags
   can load protected image files, which can't send an Authorization header).

2. **Every protected request** carries `Authorization: Bearer <token>`. The
   `current_user` dependency in `core/security.py` decodes the token and then
   **re-reads the user from the database** — so revoking a role or deactivating
   an account takes effect immediately, not whenever the token expires.

3. **Role gates.** There are two roles: `user` and `admin` (`models.Role`).
   `require_admin` / `require_user` are FastAPI dependencies produced by
   `require_role()`. An endpoint that needs admin simply declares
   `user: User = Depends(require_admin)`. Everything the old "reviewer" role
   could do is now folded into `admin`; `user.can_review` means "is admin".

4. **Default-protected routing.** In `main.py`, every router is included with
   `dependencies=[Depends(current_user)]`, so a newly added endpoint is
   authenticated by default — you have to opt *out* deliberately. The WebSocket
   is the deliberate exception (it authenticates from a `?token=` query param
   inside the handler, because a WebSocket can't set headers).

5. **First-run safety.** On an empty database `db/bootstrap.py` seeds one admin
   from the `BOOTSTRAP_ADMIN_*` settings and flags it `must_change_password`, so
   the UI forces a password change on first sign-in. In `ENVIRONMENT=production`
   the app refuses to start if `SECRET_KEY` is unset or the default admin
   password is still in use (`core/config.py`).

---

## 4. How project membership gates access

Roles say *what* you can do; membership says *which projects* you can do it in.

- `project_members` (in `models.py`) maps users to projects.
- `services/membership.py` answers `is_member()` / `assert_member()`. **Admins
  always pass** — membership only constrains plain users.
- Project-scoped endpoints call `assert_member()` before doing anything, so a
  non-member gets `403` even with a valid token, and `list_projects` filters to
  the caller's memberships. An admin manages membership from the "Members" panel
  (`POST/DELETE /api/projects/{id}/members`).

---

## 5. How live co-editing works

The goal: several people annotate the **same image at the same time** and see
each other's shapes appear live.

- **Persistence stays REST.** When you draw a box it is saved through the normal
  `POST /api/annotations` endpoint — Postgres remains the single source of
  truth. (See `frontend/src/store/history.js`, the one place edits are saved.)
- **The WebSocket is a notification side-channel.** After a successful save the
  client sends a tiny `{type:"changed"}` message to the image's room
  (`api/collaboration/ws.py`). The server rebroadcasts it to everyone *else* in
  that room, who then re-fetch the image's annotations and redraw. Reconnect is
  therefore trivially safe: on reconnect the client just re-fetches.
- **Presence** (who else is here) rides the same socket and is ephemeral — it's
  never written to the database.
- Because editing is now collaborative, the old one-editor-per-image soft lock
  is **not enforced** on the annotation write path (the `locks.py` endpoints are
  left in place but unused by live editing).

Frontend side: `lib/collab.js` owns the socket (connect / notifyChange /
presence / auto-reconnect); `components/annotate/AnnotateView.jsx` connects on
image open and shows the presence bar.

---

## 6. Frontend layout (`frontend/src/`)

```
main.jsx                    routes (React Router); gates /admin/* to admins
App.jsx                     app shell: header, role-aware nav, password-change gate
styles.css                  all styling (dark theme via CSS variables)
│
├── lib/                    non-UI app plumbing
│   ├── auth.js             token + current-user cache; isAdmin(), login(), logout()
│   ├── collab.js           the live-collaboration WebSocket client
│   └── api/client.js       every REST call, one wrapper function per endpoint
│
├── store/                  Zustand state stores
│   ├── editor.js           in-memory editor state (viewport, tool, annotations…)
│   └── history.js          undo/redo commands — and where edits hit the API
│
├── utils/                  pure helpers (geometry, colours, RLE mask encoding)
│
└── components/             UI, grouped by feature
    ├── auth/               LoginPage, ChangePasswordModal
    ├── projects/           ProjectList (+ admin members panel), VersionsPanel
    ├── annotate/           the annotation workspace
    │   ├── AnnotateView.jsx    orchestrates the screen
    │   ├── canvas/            the Konva drawing surface + editable shapes
    │   └── (ReviewBar, ImageGallerySidebar, tool docks, magnifier…)
    ├── admin/              AdminDashboard, UserManagement, ActivityFeed,
    │                       ProjectMembersPanel
    └── common/             shared widgets (ApiStatusBanner, ToolTipButton)
```

**Data-flow rule of thumb:** components call `lib/api/client.js` for reads and
call through `store/history.js` for annotation writes (so undo/redo and live
sync both happen automatically). Role-dependent UI reads `isAdmin()` from
`lib/auth.js`; the backend enforces the same rule regardless, so hiding a button
is convenience, not security.

---

## 7. Running & deploying

- **Local dev:** `docker compose up -d` (Postgres), then `scripts/start-annoforge.sh`
  runs the backend (8000) and the Vite dev server (5173).
- **Production build:** `scripts/build.sh` compiles the frontend into
  `frontend/dist`, which the backend then serves — one process, one port.
- **Migrations:** `alembic upgrade head` applies schema changes. On an existing
  database this brings in the two-role conversion, `must_change_password`, and
  the `project_members` table.
- **Backups:** `scripts/backup.sh` dumps Postgres and archives the image volume
  (schedule it nightly with cron). See `.env.example` for all settings.

See `IMPLEMENTATION_PLAN.md` for the multi-user build plan and current status.
