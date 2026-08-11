// state.js — минимальное состояние приложения в памяти вкладки.

export const state = {
  familyId: null,
  petName: null,
  petSex: null, // 'male' | 'female' — для согласования рода в текстах
  reminderMode: null,
  intervalHours: null,
  members: [], // [{id, tg_user_id, display_name}] — приходит из /api/auth при входе
};

export function memberByTgUserId(tgUserId) {
  return state.members.find((m) => m.tg_user_id === tgUserId);
}

export function displayNameFor(tgUserId) {
  return memberByTgUserId(tgUserId)?.display_name || "Кто-то";
}

export function avatarColorFor(tgUserId) {
  const idx = state.members.findIndex((m) => m.tg_user_id === tgUserId);
  return idx === 1 ? "var(--color-avatar-2)" : "var(--color-avatar-1)";
}

// Экран статистики оперирует family_members.id (member_id), а не tg_user_id —
// отдельный lookup, чтобы не путать эти два идентификатора.
export function avatarColorForMemberId(memberId) {
  const idx = state.members.findIndex((m) => m.id === memberId);
  return idx === 1 ? "var(--color-avatar-2)" : "var(--color-avatar-1)";
}
