/**
 * Pure reducer: (VoiceSessionState, VoiceSessionEvent) -> VoiceSessionState.
 *
 * Scaffold: the full implementation (every server frame, turn fences,
 * pending-action lifecycle, idle deadline) replaces this body. It must stay
 * pure and must never derive UI success from transcript text.
 */

import { NOT_SUCCESS_STATUSES } from "@/lib/one-voice/protocol";
import type { VoiceSessionEvent, VoiceSessionState } from "@/lib/one-voice/session-types";

export function isSuccessStatus(status: string | null | undefined): boolean {
  return Boolean(status) && !NOT_SUCCESS_STATUSES.has(String(status));
}

export function reduceVoiceSession(
  state: VoiceSessionState,
  event: VoiceSessionEvent,
): VoiceSessionState {
  switch (event.type) {
    case "reset":
      return { ...state, phase: "idle" };
    case "connecting":
      return { ...state, phase: "connecting", conversationId: event.conversationId, error: null };
    case "closed":
      return { ...state, phase: "idle" };
    default:
      return state;
  }
}
