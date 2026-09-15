"use client";

/**
 * One Live Voice session owner (scaffold).
 *
 * This is the SECOND microphone owner in the app, active only when the
 * server says Live is on (see AgentOwnerGate). The full implementation
 * (transport, audio, reducer, directives) replaces the bodies below; the
 * context shape is the contract screens and the control build against.
 */

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { INITIAL_VOICE_SESSION_STATE, type VoiceSessionController } from "@/lib/one-voice/session-types";

const VoiceSessionContext = createContext<VoiceSessionController | null>(null);

export function VoiceSessionProvider({
  children,
  enabled,
}: {
  children: ReactNode;
  enabled: boolean;
}) {
  const controller = useMemo<VoiceSessionController>(
    () => ({
      enabled,
      state: INITIAL_VOICE_SESSION_STATE,
      start: async () => undefined,
      stop: () => undefined,
      setMuted: () => undefined,
      interrupt: () => undefined,
      sendText: () => undefined,
      confirmPending: async () => undefined,
      cancelPending: () => undefined,
      chooseCandidate: () => undefined,
      reportClientStep: () => undefined,
    }),
    [enabled],
  );
  return <VoiceSessionContext.Provider value={controller}>{children}</VoiceSessionContext.Provider>;
}

export function useVoiceSession(): VoiceSessionController {
  const value = useContext(VoiceSessionContext);
  if (!value) throw new Error("VoiceSessionProvider is required.");
  return value;
}

export function useOptionalVoiceSession(): VoiceSessionController | null {
  return useContext(VoiceSessionContext);
}
