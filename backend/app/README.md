# Backend source map (`backend/app/`)

Layered FastAPI app. Requests flow: **api → services → models → db**, with
`core` (config + security) available to all layers. Endpoints never import each
other across domains.

| Folder | What lives here |
|---|---|
| `main.py` | App assembly. Mounts every router and applies the `current_user` guard by default, so new endpoints are authenticated unless they opt out. |
| `api/auth/` | `auth.py` (login, logout, `/me`, register, change-password) and `users.py` (admin user management). |
| `api/workspace/` | The core annotation loop: `projects.py` (projects, labels, **membership**), `images.py` (upload/list/serve files), `annotations.py` (annotation CRUD + ownership rules). |
| `api/dataset/` | The dataset as an output: `versions.py` (snapshots), `splits.py` (train/val/test), `workflow.py` (image status + admin review decisions), `export.py` (COCO/YOLO/folder). |
| `api/collaboration/` | `ws.py` (live-co-editing WebSocket rooms + presence) and `locks.py` (legacy soft-lock endpoints, unused by the live path). |
| `api/admin/` | `dashboard.py` (progress/velocity/quality metrics) and `activity.py` (audit-log feed). Admin-only. |
| `core/` | `config.py` (all env settings; fails loudly in production) and `security.py` (bcrypt, JWT, `current_user`, `require_role`). |
| `db/` | `database.py` (async engine/session) and `bootstrap.py` (seeds the first admin). |
| `models/` | `models.py` — the whole schema (User, Project, Image, Annotation, ProjectMember, ActivityLog, DatasetVersion, ImageLock) plus the `Role` and `Action` constants. |
| `services/` | Reusable logic with no HTTP: `membership.py` (access checks), `activity.py` (audit recorder), `metrics.py` (IoU), and `export/` (format writers). |

For the full narrative — auth, roles, membership, and live co-editing end to
end — see `../../ARCHITECTURE.md`.
