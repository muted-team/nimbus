import { t } from "@/lib/i18n"
import type { CampaignResult, CampaignStatus } from "@/api/types"
import { userMessage } from "@/api/client"
import { copyWithToast } from "@/lib/native"

import { REPORT_BLOCK, REPORT_WITH_REASON, reportLine, RESTORED_TEXT, TOAST, type ResultOutcome } from "./labels"

/* Отчёт кампании текстом в буфер: по блоку на исход, внутри — username. У
   «не пролито» и «забанено» рядом с именем — причина: по ней решают, что
   делать дальше (войти заново, сменить прокси, подождать капчу). */

/** Отчёт поднят с диска после перезапуска (modules/campaign.py отдаёт поле
    `restored`): это итог прошлого прохода, а не свежий. У стенда поле есть
    всегда (после T-138), у старого сервера может не быть — поэтому проверка
    строгая, только явное `true`. */
export const isRestoredReport = (st: CampaignStatus) => st.restored === true

export function reportText(st: CampaignStatus): string | null {
  // причина берётся из results по имени аккаунта: у старого ответа сервера и
  // стенда её может не быть — тогда остаётся одно имя
  const reason = new Map((st.results ?? []).map((r) => [r.account, r.reason]))
  // пустой блок в тексте не показываем: у четырёх исходов прочерки — шум.
  // Список берём через ?? — старый ответ сервера может не знать поля removed,
  // стенд отдаёт его всегда (после T-138)
  const blocks = (Object.keys(REPORT_BLOCK) as (keyof typeof REPORT_BLOCK)[])
    .map((key) => [key, st.report[key] ?? []] as const)
    .filter(([, list]) => list.length)
  if (!blocks.length) return null
  const block = (title: string, list: string[]) => `${title} (${list.length}):\n${list.join("\n")}`
  const body = blocks
    .map(([key, list]) => {
      // reportLine всегда даёт юзернейм с собакой; причину добавляет только у
      // исходов из REPORT_WITH_REASON — у прочих второй параметр не передаём
      const names = list.map((name) =>
        reportLine(name, REPORT_WITH_REASON.includes(key) ? reason.get(name) : undefined)
      )
      return block(REPORT_BLOCK[key], names)
    })
    .join("\n\n")
  // пометка первой строкой: у свежего законченного прохода её нет, а у
  // поднятого с диска человек иначе не отличит прошлый итог от текущего
  return isRestoredReport(st) ? `${t(RESTORED_TEXT)}\n\n${body}` : body
}

export async function copyReport(st: CampaignStatus): Promise<void> {
  const text = reportText(st)
  if (!text) return
  await copyWithToast(text, TOAST.copied)
}

/** Исход аккаунта: забанен, ни одного поста, целиком или частично. */
export function outcomeOf(r: CampaignResult, ppa: number): ResultOutcome {
  if (r.banned) return "banned"
  if (!r.posts_done) return "failed"
  return r.posts_done >= ppa ? "full" : "partial"
}

/** Причины неудач по числу аккаунтов, частые первыми. */
export function groupReasons(results: CampaignResult[], ppa: number): [string, number][] {
  const byReason = new Map<string, number>()
  for (const r of results) {
    if (outcomeOf(r, ppa) === "full" || !r.reason) continue
    const reason = userMessage(r.reason)
    byReason.set(reason, (byReason.get(reason) ?? 0) + 1)
  }
  return [...byReason.entries()].sort((a, b) => b[1] - a[1])
}
