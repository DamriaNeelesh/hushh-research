"use client";

/**
 * App-level Location publisher for the voice-first area (scaffold).
 *
 * Owns the continuous watch -> coarsen -> encrypt -> publish loop and handles
 * the `publish_location_envelopes` client step and the `request_os_permission`
 * directive. Mounted once (AgentOwnerGate) while Live is on so publishing
 * survives navigation. The full implementation replaces this body.
 */

export function LocationPublisherBridge() {
  return null;
}
