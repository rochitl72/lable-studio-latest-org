// Live collaboration client — one WebSocket per open image.
//
// The socket is a side-channel: annotations are still saved through the REST
// API (the source of truth). When we save, we ping the room; when the room
// pings us, we re-fetch. Presence and cursors ride the same socket.

import { getToken } from "./auth";

let socket = null;
let currentImageId = null;
let handlers = {};
let reconnectTimer = null;
let intentionalClose = false;

function wsUrl(imageId) {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = encodeURIComponent(getToken() || "");
  return `${proto}//${window.location.host}/ws/images/${imageId}?token=${token}`;
}

/** Open (or re-open) the room for an image. `on` = { onPresence, onRemoteChange, onCursor }. */
export function connectCollab(imageId, on = {}) {
  disconnectCollab();
  intentionalClose = false;
  currentImageId = imageId;
  handlers = on;
  _open();
}

function _open() {
  if (currentImageId == null) return;
  try {
    socket = new WebSocket(wsUrl(currentImageId));
  } catch {
    return;
  }

  socket.onopen = () => {
    // On every (re)connection, force the view to re-pull annotations from the
    // server. This is what makes a dropped-then-restored socket safe: any
    // changes made by others while we were offline are picked up immediately,
    // rather than silently missed until our next local edit.
    handlers.onRemoteChange?.({ type: "reconnect" });
  };

  socket.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg.type === "presence") handlers.onPresence?.(msg.users || []);
    else if (msg.type === "annotations_changed") handlers.onRemoteChange?.(msg);
    else if (msg.type === "cursor") handlers.onCursor?.(msg);
  };

  socket.onclose = () => {
    if (intentionalClose || currentImageId == null) return;
    // Transient drop — retry with a short backoff. The onopen handler above
    // re-fetches annotations once we're back, so nothing done offline is lost.
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(_open, 2000);
  };

  socket.onerror = () => {
    try {
      socket.close();
    } catch {
      /* ignore */
    }
  };
}

/** Tell the room an annotation changed so others re-fetch. */
export function notifyChange(action, annotationId) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({ type: "changed", action, annotation_id: annotationId }),
    );
  }
}

/** Broadcast this user's cursor position (image-normalised coords 0..1). */
export function sendCursor(x, y) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "cursor", x, y }));
  }
}

export function disconnectCollab() {
  intentionalClose = true;
  clearTimeout(reconnectTimer);
  currentImageId = null;
  handlers = {};
  if (socket) {
    try {
      socket.close();
    } catch {
      /* ignore */
    }
    socket = null;
  }
}
