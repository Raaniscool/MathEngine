/**
 * The single IPC channel between the preload script and the Electron main process.
 * It lives in its own file so the sandboxed preload bundle does not pull in the route allowlist.
 */
export const IPC_CHANNEL = "mathengine:request";
