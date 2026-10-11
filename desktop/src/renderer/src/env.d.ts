import type { BackendRequest, BackendResponse } from "../../shared/backendRoutes";

declare global {
  interface Window {
    /** Provided by the preload script. Every call is validated again by the Electron main process. */
    mathengine: {
      request: (request: BackendRequest) => Promise<BackendResponse>;
    };
  }
}

export {};
