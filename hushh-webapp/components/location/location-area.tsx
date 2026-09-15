"use client";

/**
 * Voice-first Location area (scaffold). Reads `?view=` / `?action=` and mounts
 * one screen. The full router and screens replace this body; the URL grammar
 * is the existing one so breadcrumbs and back targets keep working.
 */

import { AppPageContentRegion, AppPageShell } from "@/components/app-ui/app-page-shell";
import { PageHeader } from "@/components/app-ui/page-sections";

export type LocationAreaProps = {
  mode?: "workspace" | "setup";
};

export function LocationArea(_props: LocationAreaProps = {}) {
  return (
    <AppPageShell>
      <PageHeader title="Location" />
      <AppPageContentRegion>
        <p className="text-sm text-muted-foreground">Location is loading.</p>
      </AppPageContentRegion>
    </AppPageShell>
  );
}
