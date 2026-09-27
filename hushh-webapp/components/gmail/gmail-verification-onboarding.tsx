"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy, KycAgentIcon, ShieldCheck } from "@/components/icons";
import { toast } from "sonner";
import Link from "next/link";
import { ROUTES } from "@/lib/navigation/routes";

import { SurfaceInset } from "@/components/app-ui/surfaces";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/lib/morphy-ux/button";
import { PkmDomainResourceService } from "@/lib/pkm/pkm-domain-resource";
import {
  hasCompletedKycIdentityIntake,
  KycIdentityProfilePkmService,
} from "@/lib/services/kyc-identity-profile-pkm-service";
import { copyToClipboard } from "@/lib/utils/clipboard";

const EXTERNAL_AGENT_PROMPT =
  "Summarize my personal and KYC details by field concisely for KYC.";

export function GmailVerificationOnboarding({
  userId,
  vaultKey,
  vaultOwnerToken,
  onRequestVaultUnlock,
  deferred,
  onDeferredChange,
  details,
  onDetailsChange,
  children,
}: {
  userId: string | null;
  vaultKey: string | null;
  vaultOwnerToken: string | null;
  onRequestVaultUnlock: () => void;
  deferred: boolean;
  onDeferredChange: (deferred: boolean) => void;
  details: string;
  onDetailsChange: (details: string) => void;
  children: ReactNode;
}) {
  const [profileReady, setProfileReady] = useState(false);
  const [profileStatus, setProfileStatus] = useState<"unknown" | "saved" | "failed">("unknown");
  const [checking, setChecking] = useState(true);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const saveStartedRef = useRef(false);

  useEffect(() => {
    setChecking(true);
    setProfileReady(false);
    setProfileStatus("unknown");
    if (!userId || !vaultKey || !vaultOwnerToken) {
      setChecking(false);
      return;
    }

    let cancelled = false;
    void PkmDomainResourceService.getStaleFirst({
      userId,
      domain: "identity",
      vaultKey,
      vaultOwnerToken,
      // This is a one-time onboarding gate, not a list that can safely show
      // stale information. Refresh before deciding whether to ask again so a
      // completed background import never reopens this form on a later visit.
      forceRefresh: true,
      backgroundRefresh: false,
    })
      .then((snapshot) => {
        const profile = snapshot?.data?.identity_profile;
        if (!cancelled && hasCompletedKycIdentityIntake(profile)) {
          setProfileReady(true);
          setProfileStatus("saved");
        }
      })
      .catch(() => {
        // An unreadable snapshot is not evidence that setup is incomplete.
        if (!cancelled) setProfileReady(true);
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });

    return () => {
      cancelled = true;
    };
  }, [userId, vaultKey, vaultOwnerToken]);

  const copyPrompt = async () => {
    if (!(await copyToClipboard(EXTERNAL_AGENT_PROMPT))) {
      toast.error("Couldn't copy the prompt. Try again.");
      return;
    }
    setCopied(true);
    toast.success("Prompt copied.");
    window.setTimeout(() => setCopied(false), 2_000);
  };

  const save = () => {
    const aboutMe = details.trim();
    if (
      !userId ||
      !vaultKey ||
      !vaultOwnerToken ||
      !aboutMe ||
      saveStartedRef.current
    ) {
      return;
    }

    saveStartedRef.current = true;
    setSaving(true);
    const saveTask = KycIdentityProfilePkmService.saveProfile({
      userId,
      vaultKey,
      vaultOwnerToken,
      profile: { aboutMe },
    });

    // The person has explicitly approved this import. Continue into the KYC
    // workspace immediately while the encrypted PKM write completes without
    // holding their navigation hostage.
    setProfileReady(true);
    onDetailsChange("");
    toast.info("Saving your KYC details privately in the background…");
    void saveTask
      .then((result) => {
        if (!result.success) {
          setProfileStatus("failed");
          console.error("[PKM_INGEST] kyc_background_save_failed", {
            source: "kyc_identity_onboarding",
            error_code: "save_incomplete",
          });
          toast.error(
            result.message || "We couldn't save your KYC details to Memory. Nothing new was added.",
          );
          return;
        }
        setProfileStatus("saved");
        toast.success(result.message || "KYC details saved privately.");
      })
      .catch(() => {
        setProfileStatus("failed");
        console.error("[PKM_INGEST] kyc_background_save_failed", {
          source: "kyc_identity_onboarding",
          error_code: "background_task_rejected",
        });
        toast.error("We couldn't save your KYC details to Memory. Nothing new was added.");
      })
      .finally(() => setSaving(false));
  };

  if (checking) {
    return (
      <SurfaceInset
        aria-busy="true"
        aria-live="polite"
        aria-label="Checking KYC setup"
        className="space-y-4 px-4 py-4 text-sm sm:px-5 sm:py-5"
      >
        <div className="space-y-1">
          <p className="font-semibold text-foreground">KYC requests</p>
          <p className="text-sm leading-6 text-muted-foreground">
            Getting your KYC workspace ready.
          </p>
        </div>
        <div aria-hidden="true" className="space-y-3">
          <div className="flex items-center justify-between gap-3 rounded-[var(--app-card-radius-sm)] border border-border/60 bg-background/60 px-3.5 py-3">
            <div className="space-y-2">
              <Skeleton className="h-4 w-36" />
              <Skeleton className="h-3 w-52 max-w-full" />
            </div>
            <Skeleton className="h-10 w-24 shrink-0" />
          </div>
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </SurfaceInset>
    );
  }
  if (profileReady || deferred) return (
    <>
      <div className="flex items-center justify-between gap-3 border-y border-[color:var(--app-separator)] py-4">
        <div className="space-y-1">
          <h2 className="text-[17px] font-semibold text-foreground">KYC profile</h2>
          <p aria-live="polite" className={profileStatus === "saved" && !saving
            ? "flex items-center gap-1.5 text-sm text-[color:var(--app-success-deep)] dark:text-[color:var(--app-success-bright)]"
            : "text-sm text-muted-foreground"}>
            {profileStatus === "saved" && !saving ? <Check aria-hidden="true" className="size-4" /> : null}
            {saving ? "Saving…" : profileStatus === "saved" ? "Saved" : profileStatus === "failed" ? "Not saved" : deferred ? "Skipped for now" : "Review in Memory"}
          </p>
        </div>
        <Button asChild variant="none" effect="fade" className="min-h-11 shrink-0 px-2 text-sm font-normal !text-[color:var(--app-accent)]">
          <Link href={ROUTES.PKM}>Edit in Memory</Link>
        </Button>
      </div>
      {children}
    </>
  );

  if (!vaultKey || !vaultOwnerToken) {
    return (
      <SurfaceInset className="space-y-3 px-4 py-5 sm:px-5">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-primary/10 p-2 text-primary">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div className="space-y-1">
            <h2 className="text-base font-semibold text-foreground">
              Set up KYC
            </h2>
            <p className="text-xs text-muted-foreground">
              Open your private vault before importing details for future KYC
              replies.
            </p>
          </div>
        </div>
        <Button type="button" onClick={onRequestVaultUnlock} className="w-full justify-center h-10 font-semibold rounded-full">
          Open private vault
        </Button>
      </SurfaceInset>
    );
  }

  return (
    <section className="mx-auto w-full max-w-md space-y-4 border-t border-[color:var(--app-separator)] pt-6">
      <div className="flex flex-col items-center text-center">
        <div aria-hidden="true" className="mb-4 flex size-16 items-center justify-center rounded-[20px] bg-[color:var(--app-accent-tint)] text-[color:var(--app-accent)]">
          <KycAgentIcon color="currentColor" className="size-9" />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight text-foreground">
          Build your KYC profile
        </h2>
        <p className="mt-2 max-w-xs text-[15px] leading-[22px] text-muted-foreground">
          For faster KYC replies.
        </p>
      </div>
      <Textarea
        value={details}
        onChange={(event) => onDetailsChange(event.target.value)}
        placeholder="Paste your profile details here…"
        className="min-h-32 resize-y border-[color:var(--app-separator)] bg-[color:var(--app-primary-surface)] text-base shadow-none"
        aria-label="KYC details"
        disabled={saving}
      />
      <div className="flex items-start gap-2.5">
        <Copy aria-hidden="true" className="mt-2.5 size-5 shrink-0 text-[color:var(--app-accent)]" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2">
            <Button
              type="button"
              variant="none"
              effect="fade"
              onClick={() => void copyPrompt()}
              aria-label="Copy prompt to clipboard"
              className="min-h-11 px-0 text-[15px] font-medium !text-[color:var(--app-accent)]"
            >
              {copied ? "Copied" : "Copy AI prompt"}
            </Button>
            <span className="text-xs text-muted-foreground">· Optional</span>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            Use in your AI app. Then paste the reply here.
          </p>
        </div>
      </div>
      <div className="flex flex-col items-center gap-1">
        <Button
          type="button"
          size="prominent"
          onClick={save}
          disabled={saving || !details.trim()}
          className="w-full justify-center"
        >
          {saving ? "Saving…" : "Save profile"}
        </Button>
        <Button
          type="button"
          variant="none"
          effect="fade"
          onClick={() => onDeferredChange(true)}
          disabled={saving}
          className="min-h-11 px-4 text-[15px] font-normal !text-[color:var(--app-accent)]"
        >
          Skip for now
        </Button>
      </div>
    </section>
  );
}
