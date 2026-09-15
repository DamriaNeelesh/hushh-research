"use client";

/** Voice-first Location setup (scaffold; replaced by the full flow). */

export type LocationSetupFlowProps = {
  mode: "setup";
  onSetupReadinessChange?: (ready: boolean) => void;
  onSetupComplete?: () => void | Promise<void>;
  onSetupSkip?: () => void | Promise<void>;
};

export function LocationSetupFlow(_props: LocationSetupFlowProps) {
  return <p className="text-sm text-muted-foreground">Location setup is loading.</p>;
}
