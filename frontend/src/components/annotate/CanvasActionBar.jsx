// CanvasActionBar.jsx — floating action buttons overlaid on the canvas.
// Compact undo/redo/delete/save/mark-done controls that follow the selection.

import { Check, Undo2, Redo2, Trash2, Save } from "lucide-react";

export default function CanvasActionBar({
  canUndo,
  canRedo,
  hasSelection,
  readOnly,
  draftLabel,
  onSaveDraft,
  onUndo,
  onRedo,
  onDelete,
  onMarkImageDone,
  imageDone,
}) {
  return (
    <div className="canvas-action-bar">
      {draftLabel && !readOnly && (
        <button
          type="button"
          className="action-btn action-save"
          onClick={onSaveDraft}
        >
          <Save size={16} />
          <span>{draftLabel}</span>
        </button>
      )}
      <button
        type="button"
        className="action-btn"
        onClick={onUndo}
        disabled={!canUndo || readOnly}
        title="Undo (⌘Z)"
      >
        <Undo2 size={16} />
        <span>Undo</span>
      </button>
      <button
        type="button"
        className="action-btn"
        onClick={onRedo}
        disabled={!canRedo || readOnly}
        title="Redo (⌘⇧Z)"
      >
        <Redo2 size={16} />
        <span>Redo</span>
      </button>
      <button
        type="button"
        className="action-btn action-danger"
        onClick={onDelete}
        disabled={!hasSelection || readOnly}
        title="Delete selected shape or discard unsaved Smart Select (Del)"
      >
        <Trash2 size={16} />
        <span>Delete</span>
      </button>
      <div className="action-bar-spacer" />
      <button
        type="button"
        className={`action-btn action-done ${imageDone ? "is-done" : ""}`}
        onClick={onMarkImageDone}
        disabled={readOnly}
        title="Save progress — mark this image as annotated"
      >
        <Check size={16} />
        <span>{imageDone ? "Image saved" : "Mark image done"}</span>
      </button>
    </div>
  );
}
