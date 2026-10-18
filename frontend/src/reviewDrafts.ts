import type { HumanReview } from "./api";
const KEY = "cashier-guard-review-drafts";
type Draft = {
  decision: HumanReview["decision"];
  comment: string;
  expires: number;
};
function read(): Record<string, Draft> {
  try {
    const all = JSON.parse(sessionStorage.getItem(KEY) ?? "{}");
    if (!all || typeof all !== "object" || Array.isArray(all)) return {};
    const live = Object.fromEntries(
      Object.entries(all)
        .filter(
          ([, v]) =>
            v &&
            typeof (v as Draft).comment === "string" &&
            ["unreviewed", "confirmed", "rejected"].includes(
              (v as Draft).decision,
            ) &&
            (v as Draft).expires > Date.now(),
        )
        .slice(-50),
    ) as Record<string, Draft>;
    sessionStorage.setItem(KEY, JSON.stringify(live));
    return live;
  } catch {
    return {};
  }
}
export function readDraft(id: string) {
  return read()[id];
}
export function writeDraft(
  id: string,
  value: Omit<Draft, "expires"> | null,
  expiresAt?: string | null,
) {
  try {
    const all = read();
    delete all[id];
    if (value)
      all[id] = {
        ...value,
        expires: Math.min(
          Date.now() + 86400000,
          expiresAt ? Date.parse(expiresAt) : Infinity,
        ),
      };
    sessionStorage.setItem(
      KEY,
      JSON.stringify(Object.fromEntries(Object.entries(all).slice(-50))),
    );
  } catch {
    /* Keep the mounted form's draft when tab storage is unavailable. */
  }
}

export function pruneDrafts() {
  read();
}
