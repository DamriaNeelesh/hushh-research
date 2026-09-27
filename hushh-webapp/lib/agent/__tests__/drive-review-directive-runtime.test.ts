import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getDriveReviewDirectiveFromToolResult,
  runDriveReviewDirective,
} from "@/lib/agent/drive-review-directive-runtime";
import { ApiService } from "@/lib/services/api-service";

vi.mock("@/lib/services/api-service", () => ({
  ApiService: { apiFetch: vi.fn() },
}));

const reviewed = {
  type: "drive.execute_review",
  directiveId: `dir_${"a".repeat(32)}`,
  conversationId: "thread-1",
  action: "share",
  arguments: { fileId: "file_1", email: "chris@example.invalid", role: "writer", notify: true, message: "" },
  summary: "Share “Budget” with chris@example.invalid as Editor",
  confirmLabel: "Share",
};

describe("Drive review directive", () => {
  beforeEach(() => vi.mocked(ApiService.apiFetch).mockReset());

  it("sends exactly the reviewed Drive call after an explicit confirmation", async () => {
    vi.mocked(ApiService.apiFetch).mockResolvedValue(new Response("{}", { status: 200 }));
    const event = getDriveReviewDirectiveFromToolResult(
      JSON.stringify({ directive: { kind: "action", delegateAgentId: "agent_documents", payload: reviewed } }),
    );
    expect(event?.message).toBe(reviewed.summary);

    const result = await runDriveReviewDirective(event!.directive, "HCT:test", "user-1");

    expect(result.detail).toBe("Shared in Google Drive.");
    const [path, init] = vi.mocked(ApiService.apiFetch).mock.calls[0]!;
    expect(path).toBe("/api/one/drive/reviewed-actions/execute");
    expect(JSON.parse(String(init?.body))).toEqual({
      user_id: "user-1",
      conversation_id: "thread-1",
      directive_id: reviewed.directiveId,
      action: "share",
      arguments: reviewed.arguments,
      confirmed: true,
    });
  });

  it("refuses anything that is not a server-issued Drive review", async () => {
    for (const payload of [
      { ...reviewed, type: "calendar.execute_proposal" },
      { ...reviewed, directiveId: "dir_forged" },
      { ...reviewed, action: "delete" },
    ]) {
      expect(
        getDriveReviewDirectiveFromToolResult({
          directive: { delegateAgentId: "agent_documents", payload },
        }),
      ).toBeNull();
      await expect(
        runDriveReviewDirective({ kind: "action", payload }, "HCT:test", "user-1"),
      ).rejects.toThrow("Drive confirmation is invalid");
    }
    expect(ApiService.apiFetch).not.toHaveBeenCalled();
  });
});
