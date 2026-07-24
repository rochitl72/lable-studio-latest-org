# RBG Annotation Studio — Data Flow & Storage Reference

Where every action goes, what it writes, and what it triggers — for **users**
and **admins** separately. Read this alongside the two diagrams in
`diagrams/backend_flow.mermaid` and `diagrams/db_er.mermaid`.

---

## 1. The two stores of truth

| What | Where it lives | Notes |
|---|---|---|
| Accounts, roles, memberships, projects, labels, versions, **image metadata**, **annotations**, audit log, locks | **PostgreSQL** | Everything structured and queryable. |
| The actual **image files** and **export bundles** | **Server disk** (`STORAGE_DIR`, `EXPORT_DIR`) | The DB only stores the *path*; the bytes live on disk at `storage/project_{id}/{xx}/{uuid}.ext`. |
| Live presence, cursors, "someone changed this" pings | **Nowhere (ephemeral)** | Carried over the WebSocket only; never persisted. |

So a single "save an annotation" writes a row to Postgres; an "upload images"
writes rows to Postgres **and** files to disk; a "who's online" is memory-only.

---

## 2. How a request is gated (every request passes through this)

1. **Authentication** — `core/security.current_user` decodes the JWT, then
   **re-reads the user from `users`** so a demotion/deactivation applies
   instantly. WebSocket connections authenticate from a `?token=` query param
   instead of a header.
2. **Role gate** — endpoints that need admin declare `require_admin`. Under two
   roles, `user.can_review` simply means "is admin".
3. **Membership gate** — project-scoped endpoints call
   `services/membership.assert_member`. A plain user must be in
   `project_members`; **admins bypass this** and can reach every project.
4. **The work** — the router reads/writes Postgres (and disk for files).
5. **Audit** — almost every mutation calls `services/activity.record`, appending
   one row to `activity_log` **in the same transaction** as the change.

---

## 3. Client-side path for an annotation (bbox · polygon · keypoint · mask)

Drawing tools never call the API directly. They funnel through one choke point:

```
canvas tool → history store command → REST /api/annotations → Postgres
                                    → editor store (instant on-screen update)
                                    → collab.js notify → WebSocket → other viewers refetch
```

- **bbox / polygon / keypoint** are created in `AnnotationCanvas` and edited by
  the `Editable*` components; each edit is a `makeUpdateGeometryCmd`.
- **mask (brush)** is painted in `BrushOverlay`; on mouse-up it becomes
  `makeCreateCmd` (new mask) or `makeUpdateGeometryCmd` / `makeDeleteCmd`
  (growing, erasing, or clearing the selected mask).
- Every command records an **undo** snapshot, so `⌘Z` reverses it, and calls
  `notifyChange` so collaborators re-pull. Geometry is stored in the
  `annotations.geometry` JSON column — coordinates for vector shapes, RLE for
  masks.

---

## 4. USER actions — end to end

A "user" is a plain annotator. They only see projects they're a member of.

| Action | Endpoint (method) | Gate | Postgres change | Disk | Audit / live |
|---|---|---|---|---|---|
| Log in | `/api/auth/login` (POST) | password | `UPDATE users.last_login_at` | — | `login`; issues JWT + cookie |
| Change own password | `/api/auth/change-password` (POST) | signed-in | `UPDATE users.password_hash`, clears `must_change_password` | — | `user.update` |
| See "My progress" | `/api/users/me/stats` (GET) | signed-in | reads only | — | — |
| List my projects | `/api/projects` (GET) | member filter | reads `project_members` | — | — |
| Open a project's images | `/api/projects/{id}/images` (GET) | member | reads (auto-creates a `dataset_versions` row if none) | — | — |
| View an image | `/api/projects/{id}/images/{iid}/file` (GET) | member (cookie ok) | reads | reads file | — |
| List annotations | `/api/images/{iid}/annotations` (GET) | member | reads | — | — |
| **Draw** a bbox/polygon/keypoint/mask | `/api/annotations` (POST) | member; blocked if image `approved` | `INSERT annotations` (`created_by`,`updated_by`); may `UPDATE images.status → in_progress` | — | `annotation.create`; WS ping |
| **Edit** an annotation | `/api/annotations/{id}` (PATCH) | member; own only (admin any); not approved | `UPDATE annotations.geometry/label_id/updated_by` | — | `annotation.update` (before/after); WS ping |
| **Delete** an annotation | `/api/annotations/{id}` (DELETE) | member; own only; not approved | `DELETE annotations` | — | `annotation.delete`; WS ping |
| Mark image In progress / Done | `/api/images/status` (PATCH) | member; non-review status only | `UPDATE images.status` | — | `image.status_change` |
| Live co-edit / presence | `/ws/images/{iid}` (WS) | token + membership | none (ephemeral) | — | presence + change broadcast |
| View **own** activity | `/api/activity?user_id=self` (GET) | self only | reads `activity_log` | — | — |

What a user **cannot** do (returns 403): create projects, upload/delete images,
create labels/versions, split or export datasets, approve/reject, manage users,
touch a project they aren't a member of, or view team dashboards.

---

## 5. ADMIN actions — end to end

An "admin" can do everything a user can, plus the following. Admins bypass
membership entirely.

| Action | Endpoint (method) | Postgres change | Disk | Audit |
|---|---|---|---|---|
| Create a user | `/api/users` (POST) | `INSERT users` | — | `user.create` |
| Change role / deactivate / reset password | `/api/users/{id}` (PATCH / DELETE) | `UPDATE users` (last-admin guard) | — | `user.update` / `user.deactivate` |
| Create a project | `/api/projects` (POST) | `INSERT projects` + `INSERT dataset_versions (v1)` + `UPDATE projects.active_version_id` | — | `project.create` |
| Delete a project | `/api/projects/{id}` (DELETE) | `DELETE projects` (cascades images, labels, versions, annotations) | orphaned files remain unless pruned | `project.delete` |
| Add / remove a label class | `/api/projects/{id}/labels` (POST / DELETE) | `INSERT` / `DELETE labels` (cascades annotations of that label) | — | `label.create` |
| **Upload images** | `/api/projects/{id}/images/upload` (POST) | `INSERT images` (+ version if none) | **writes files** to `storage/project_{id}/{xx}/{uuid}.ext` | `image.upload` |
| Delete an image | `/api/projects/{id}/images/{iid}` (DELETE) | `DELETE images` | `unlink` file | `image.delete` |
| **Assign users to a project** | `/api/projects/{id}/members` (POST / DELETE) | `INSERT` / `DELETE project_members` | — | `project.member_add` / `member_remove` |
| Approve / reject / needs-review | `/api/images/status` or `/api/images/bulk-status` | `UPDATE images.status, reviewed_by, reviewed_at, review_note` | — | `review.approve` / `reject` / `request` |
| Assign images to an annotator | `/api/dashboard/assign` (POST) | `UPDATE images.assigned_to, assigned_at` | — | `image.assign` |
| Create a dataset version (snapshot) | `/api/projects/{id}/versions` (POST) | `INSERT dataset_versions` + copies images & annotations + `UPDATE active_version_id` | — | — |
| Activate a version | `/api/projects/{id}/versions/{vid}/activate` (POST) | `UPDATE projects.active_version_id` | — | — |
| Split / auto-split train·val·test | `/api/images/split`, `/api/projects/auto-split` | `UPDATE images.split` | — | — |
| Export COCO / YOLO / to Downloads | `/api/projects/{id}/export/*` | reads only | **writes** export bundle to disk / `EXPORT_DIR` | `export` (folder export) |
| Team dashboard (progress, velocity, quality, review queue) | `/api/dashboard/*` (GET) | reads `images`, `annotations`, `activity_log` | — | — |
| Activity feed + CSV | `/api/activity`, `/api/activity/export.csv` | reads `activity_log` | — | — |

---

## 6. The live-collaboration path (why it's separate)

Persistence is **always REST → Postgres**. The WebSocket is only a notifier:

1. A user saves an annotation via REST (Postgres is updated).
2. Their browser sends `{type:"changed"}` to the image's room over the socket.
3. The server (`api/collaboration/ws.py`) rebroadcasts to everyone **else** in
   that room.
4. Those clients re-fetch the image's annotations from REST and redraw.

Presence ("3 people here") and cursors ride the same socket and are never
stored. On reconnect a client re-pulls annotations, so nothing done offline is
missed. (The old `image_locks` table still exists but is **not enforced** on the
write path — true co-editing replaced one-editor-per-image locking.)

---

## 7. Cascade & ownership rules (what deletes take with them)

- Delete a **project** → its images, labels, dataset_versions, and (through
  images) annotations are all removed (`ON DELETE CASCADE`). Membership rows go
  too. Image files on disk are **not** auto-deleted.
- Delete an **image** → its annotations and any lock go; the file is unlinked.
- Delete a **label** → annotations using it cascade away.
- Delete a **user** → the app *deactivates* instead of hard-deleting, so their
  authored annotations keep a valid `created_by`. If a user row were removed,
  `created_by`/`assigned_to`/`reviewed_by` are set null (`ON DELETE SET NULL`).
- A plain user may only edit/delete annotations where `created_by` is
  themselves; an admin may edit/delete anyone's.

---

## 8. Quick "where is it stored?" cheat-sheet

- **My password / role / login time** → `users`.
- **Which projects I can see** → `project_members` (admins: all).
- **A box/polygon/mask I drew** → `annotations` (geometry JSON), file unchanged.
- **The image itself** → disk (`storage/...`); only its path + status in `images`.
- **"Who did what, when"** → `activity_log` (one row per mutation).
- **Train/val/test split, review status, assignment** → columns on `images`.
- **A frozen dataset snapshot** → `dataset_versions` (+ copied image/annotation rows).
- **Who's online right now** → nowhere; it's live-only over the WebSocket.
