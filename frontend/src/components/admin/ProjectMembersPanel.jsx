// ProjectMembersPanel.jsx — admin panel controlling who may work on a project.
// Lists current members and lets an admin bulk-add existing users (checkbox
// multi-select) or remove them. Each change calls the /members API, which
// inserts/deletes rows in the project_members table (the access boundary).

import { useEffect, useState } from "react";
import { listMembers, addMember, removeMember, listUsers } from "../../lib/api/client";

/**
 * Admin-only modal: manage which users belong to a project. Admins bypass
 * membership, so this is about granting plain users access.
 *
 * Assignment is bulk: the admin ticks any number of candidate users and adds
 * them all in one action, which covers "hand this project to my team of five"
 * without needing a separate named-team concept. Each tick fires the existing
 * one-user-at-a-time `POST /api/projects/{id}/members` endpoint — there's no
 * dedicated bulk API, we just fire the calls in parallel from the client.
 */
export default function ProjectMembersPanel({ project, onClose }) {
  const [members, setMembers] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [checked, setChecked] = useState(new Set());
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);

  const load = () =>
    Promise.all([listMembers(project.id), listUsers()])
      .then(([m, u]) => {
        setMembers(m);
        setAllUsers(u);
      })
      .catch((e) => setError(e.message));

  useEffect(() => { load(); }, [project.id]);

  const memberIds = new Set(members.map((m) => m.user_id));
  // Only plain, active users are assignable — admins already see every
  // project, so listing them here as "candidates" would be meaningless.
  const candidates = allUsers.filter(
    (u) => u.is_active && u.role !== "admin" && !memberIds.has(u.id),
  );

  const toggle = (userId) => {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(userId) ? next.delete(userId) : next.add(userId);
      return next;
    });
  };

  const addSelected = async () => {
    if (checked.size === 0) return;
    setError("");
    setAdding(true);
    try {
      // Fire all the adds together; each is independent so one failing
      // (e.g. a race with someone else editing membership) doesn't block
      // the rest.
      const results = await Promise.allSettled(
        [...checked].map((id) => addMember(project.id, id)),
      );
      const failed = results.filter((r) => r.status === "rejected");
      if (failed.length) {
        setError(`${failed.length} of ${checked.size} could not be added.`);
      }
      setChecked(new Set());
      load();
    } finally {
      setAdding(false);
    }
  };

  const remove = async (userId) => {
    setError("");
    try {
      await removeMember(project.id, userId);
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h2 className="modal-title">Members — {project.name}</h2>
        <p className="modal-note">
          Admins can see every project. Select one or more users below and add
          them all at once — handy for handing a project to a whole team.
        </p>

        <div className="bulk-add-list">
          {candidates.length === 0 && (
            <p className="muted">No unassigned users available.</p>
          )}
          {candidates.map((u) => (
            <label key={u.id} className="bulk-add-row">
              <input
                type="checkbox"
                checked={checked.has(u.id)}
                onChange={() => toggle(u.id)}
              />
              <span>{u.full_name ? `${u.full_name} (${u.username})` : u.username}</span>
            </label>
          ))}
        </div>
        <div className="modal-actions" style={{ justifyContent: "space-between" }}>
          <span className="muted">{checked.size} selected</span>
          <button
            className="btn-primary"
            onClick={addSelected}
            disabled={checked.size === 0 || adding}
          >
            {adding ? "Adding…" : `Add ${checked.size || ""} to project`}
          </button>
        </div>

        {error && <div className="form-error">{error}</div>}

        <h3 className="modal-subheading">Current members</h3>
        <ul className="member-list">
          {members.length === 0 && <li className="muted">No members yet.</li>}
          {members.map((m) => (
            <li key={m.user_id} className="member-item">
              <span>
                {m.full_name || m.username}
                <span className={`role-chip role-${m.role}`}>{m.role}</span>
              </span>
              <button className="btn-text danger" onClick={() => remove(m.user_id)}>
                Remove
              </button>
            </li>
          ))}
        </ul>

        <div className="modal-actions">
          <button className="btn-primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
