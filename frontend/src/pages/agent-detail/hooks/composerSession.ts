import { request } from "../../../api/request";

interface CreatedChatSession {
  id: string;
  agent_id: string;
  user_id: string;
  source_channel: "web";
  title: string;
  created_at: string;
}

// The native history list omits empty chats. A newly returned POST receipt can
// hydrate one, after the native owner endpoint rechecks current tenant/user scope.
export async function resolveCreatedChatSession(
  state: unknown,
  agentId: string,
  userId: string,
  sessionId: string,
): Promise<CreatedChatSession | undefined> {
  if (!state || typeof state !== "object") return;
  const value = (state as { createdChatSession?: unknown }).createdChatSession;
  if (!value || typeof value !== "object") return;
  const v = value as Partial<CreatedChatSession>;
  if (
    v.id !== sessionId ||
    v.agent_id !== agentId ||
    v.user_id !== userId ||
    v.source_channel !== "web" ||
    typeof v.title !== "string" ||
    v.title.length > 200 ||
    typeof v.created_at !== "string" ||
    !Number.isFinite(Date.parse(v.created_at))
  )
    return;
  await request(`/agents/${agentId}/sessions/${sessionId}/runtime-state`);
  return {
    id: sessionId,
    agent_id: agentId,
    user_id: userId,
    source_channel: "web",
    title: v.title,
    created_at: v.created_at,
  };
}
