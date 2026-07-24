// config.js — resolves where the backend API/WebSocket live.
//
// Two deployment shapes are supported:
//
//   1. Same-origin (default): the frontend is served by something (nginx,
//      Vite dev proxy, ...) that reverse-proxies /api and /ws to the backend
//      on the SAME host:port the browser loaded the page from. In this mode
//      leave VITE_API_BASE_URL unset — every URL below stays relative
//      ("/api/...", same-origin WebSocket) and just works.
//
//   2. Separate origin: the frontend is a static build served on its own
//      (e.g. a plain nginx/S3/CDN with no reverse proxy) and must call a
//      backend running on a different host or port. Set VITE_API_BASE_URL
//      to that backend's base URL — e.g. "http://192.168.1.50:8000" or
//      "https://api.example.com" — at BUILD time (see frontend/.env.example).
//      Vite bakes VITE_-prefixed vars into the compiled bundle, so this must
//      be set before `npm run build` / `docker build`, not at container
//      start.
//
// Input:   the VITE_API_BASE_URL build-time environment variable (or none).
// Process: normalises it (strips a trailing slash) and derives the matching
//          ws:// / wss:// origin from the same value.
// Output:  API_BASE (REST calls always prefix this) and wsOrigin() (used by
//          the live-collaboration socket).
const RAW = (import.meta.env.VITE_API_BASE_URL || "").trim().replace(/\/+$/, "");

/** "" for same-origin, or the absolute backend origin, e.g. "http://host:8000". */
export const API_ORIGIN = RAW;

/** REST base every client.js call is prefixed with. Always ends in /api. */
export const API_BASE = `${RAW}/api`;

/** WebSocket origin, kept in lockstep with API_ORIGIN so they can never drift. */
export function wsOrigin() {
  if (RAW) {
    // http:// -> ws://, https:// -> wss://
    return RAW.replace(/^http/, "ws");
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}
