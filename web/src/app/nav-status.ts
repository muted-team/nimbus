import { t } from "@/lib/i18n"
import { useEffect } from "react"

import { isCampaignLive, useCampaignStatus } from "@/api/campaign"
import { unseenErrors, useLogs } from "@/api/logs"
import { fmtInt } from "@/lib/format"

import { PRODUCT } from "./brand"
import type { SectionId } from "./sections"

export interface NavBadge {
  text: string
  tone: "live" | "bad"
  spin?: boolean
}

/** Отметки на пунктах меню: ход публикации и новые ошибки в логах. */
export function useNavBadges(): Partial<Record<SectionId, NavBadge>> {
  const { data: st } = useCampaignStatus()
  const errors = useLogs((s) => unseenErrors(s.events, s.seenSeq))
  const badges: Partial<Record<SectionId, NavBadge>> = {}
  if (st && isCampaignLive(st)) {
    badges.camp =
      st.status === "waiting"
        ? { text: t("ждёт"), tone: "live" }
        : { text: `${fmtInt(st.posts_done)}/${fmtInt(st.posts_total)}`, tone: "live", spin: true }
  }
  if (errors) badges.logs = { text: String(errors), tone: "bad" }
  return badges
}

const APP_TITLE = PRODUCT

/** Заголовок окна с ходом публикации — видно на панели задач. */
export function useDocumentTitle() {
  const { data: st } = useCampaignStatus()
  const live = isCampaignLive(st)
  const text =
    st && live && st.status !== "waiting" ? `${fmtInt(st.posts_done)}/${fmtInt(st.posts_total)} · ${APP_TITLE}` : APP_TITLE
  useEffect(() => {
    document.title = text
  }, [text])
}
