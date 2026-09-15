"use client";

/**
 * Bottom-slot launcher for One Live Voice (scaffold).
 *
 * Keeps the launcher identity the shell and native tests rely on:
 * data-testid="one-voice-agent-bar" and the native control id. The full
 * control (pill states, mute/stop, docked panel) replaces this body.
 */

import { useVoiceSession } from "@/components/one-voice/voice-session-provider";

export function OneVoiceControl({ layout = "slot" }: { layout?: "fixed" | "slot" }) {
  const session = useVoiceSession();
  const active = session.state.phase !== "idle";
  return (
    <div
      data-testid="one-voice-agent-bar"
      data-agent-dock="one-agent-dock"
      data-layout={layout}
      className="pointer-events-auto mx-auto w-full"
      style={{ maxWidth: "var(--app-agent-bar-max-width)" }}
    >
      <button
        type="button"
        data-native-voice-control-id="one_voice_agent_bar_start"
        aria-label="Talk to One"
        onClick={() => (active ? session.stop("tap") : void session.start({ source: "agent_bar" }))}
        className="flex h-12 w-full items-center justify-center rounded-full bg-[var(--app-accent)] text-sm font-medium text-white"
      >
        {active ? "Stop" : "Talk to One"}
      </button>
    </div>
  );
}
