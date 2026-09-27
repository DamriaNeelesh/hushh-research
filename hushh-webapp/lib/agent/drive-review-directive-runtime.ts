import type { SpecialistDirective } from "@/lib/agent/specialist-directive-runtime";
import type { SpecialistDirectiveEvent } from "@/lib/services/agent-chat-client";
import { ApiService } from "@/lib/services/api-service";

export const DRIVE_REVIEW_DELEGATE = "agent_documents";
export const DRIVE_REVIEW_TYPE = "drive.execute_review";

type DriveReviewAction = "share" | "trash";

type DriveReviewPayload = {
  type: typeof DRIVE_REVIEW_TYPE;
  directiveId: string;
  conversationId: string;
  action: DriveReviewAction;
  arguments: Record<string, unknown>;
  summary: string;
  confirmLabel: string;
};

function reviewPayload(value: unknown): DriveReviewPayload | null {
  if (!value || typeof value !== "object") return null;
  const payload = value as Record<string, unknown>;
  if (
    payload.type !== DRIVE_REVIEW_TYPE ||
    typeof payload.directiveId !== "string" ||
    !/^dir_[0-9a-f]{32}$/.test(payload.directiveId) ||
    typeof payload.conversationId !== "string" ||
    !payload.conversationId ||
    (payload.action !== "share" && payload.action !== "trash") ||
    !payload.arguments ||
    typeof payload.arguments !== "object" ||
    Array.isArray(payload.arguments) ||
    typeof payload.summary !== "string" ||
    typeof payload.confirmLabel !== "string"
  ) {
    return null;
  }
  return payload as DriveReviewPayload;
}

/** The Drive share/trash review card for a proposal tool result, if it is one. */
export function getDriveReviewDirectiveFromToolResult(
  rawResult: unknown,
): SpecialistDirectiveEvent | null {
  let parsed: unknown = rawResult;
  if (typeof rawResult === "string") {
    try {
      parsed = JSON.parse(rawResult);
    } catch {
      return null;
    }
  }
  if (!parsed || typeof parsed !== "object") return null;
  const directive = (parsed as Record<string, unknown>).directive as
    | Record<string, unknown>
    | undefined;
  if (!directive || directive.delegateAgentId !== DRIVE_REVIEW_DELEGATE) return null;
  const payload = reviewPayload(directive.payload);
  if (!payload) return null;
  return {
    delegateAgentId: DRIVE_REVIEW_DELEGATE,
    directive: { kind: "action", payload },
    message: payload.summary,
    stateChanged: true,
  };
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as {
    detail?: { message?: string } | string;
  } | null;
  const detail = body?.detail;
  return (typeof detail === "string" ? detail : detail?.message) || fallback;
}

/**
 * Execute exactly the Drive call the owner reviewed. The server rebuilds the
 * terms from these arguments and its current Drive connection and matches them
 * against the one-use review it issued; anything changed is refused.
 */
export async function runDriveReviewDirective(
  directive: SpecialistDirective,
  vaultOwnerToken: string,
  userId: string,
): Promise<{ detail: string }> {
  const payload = reviewPayload(directive.payload);
  if (!payload) throw new Error("Drive confirmation is invalid.");
  const response = await ApiService.apiFetch("/api/one/drive/reviewed-actions/execute", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${vaultOwnerToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      user_id: userId,
      conversation_id: payload.conversationId,
      directive_id: payload.directiveId,
      action: payload.action,
      arguments: payload.arguments,
      confirmed: true,
    }),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Unable to apply the Drive change."));
  }
  return {
    detail: payload.action === "share" ? "Shared in Google Drive." : "Moved to trash in Google Drive.",
  };
}
