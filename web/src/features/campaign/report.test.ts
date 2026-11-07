import { describe, expect, it } from "vitest"

import type { CampaignReport, CampaignResult, CampaignStatus } from "@/api/types"

import { REMOVED_TEXT, REPORT_BLOCK, RESTORED_TEXT, STEP_LABEL } from "./labels"
import { groupReasons, outcomeOf, reportText } from "./report"

/* Текст отчёта копируется в буфер и уезжает заказчику: под каждым исходом
   должен стоять свой блок с логинами, а аккаунты со снятыми постами — попасть
   в него отдельным блоком. У «не пролито» и «забанено» рядом с именем стоит
   причина: по пересланному тексту видно, что делать. */

const result = (account: string, reason?: string, posts_done = 0): CampaignResult => ({
  account,
  ok: posts_done > 0,
  posts_done,
  reason,
})

function rep(extra: Partial<CampaignReport> = {}): CampaignReport {
  return {
    published: [],
    failed: [],
    banned: [],
    removed: [],
    posts: 0,
    posts_removed: 0,
    ...extra,
  }
}

function status(report: CampaignReport, results: CampaignResult[] = []): CampaignStatus {
  return {
    status: "stopped",
    accounts_total: 0,
    accounts_done: 0,
    queued: [],
    posts_per_account: 6,
    threads: 1,
    workers: [],
    results,
    stop_reason: null,
    started_at: null,
    finished_at: null,
    repeat: false,
    media: "photo",
    round: 0,
    rounds_done: 0,
    restored: false,
    next_run_at: null,
    posts_total: 0,
    posts_done: 0,
    posts_failed: 0,
    report,
  }
}

/* Отчёт подняли с диска после перезапуска (campaign.py, поле restored): без
   пометки свежий законченный проход и прошлый по тексту не отличить. Сервер
   ставит поле и в дефолт, и при подъёме; у стенда его ещё нет (T-139). */
const restored = (st: CampaignStatus): CampaignStatus => ({ ...st, restored: true })

describe("отчёт кампании текстом", () => {
  it("каждый исход — своим блоком, снятые посты не теряются", () => {
    const text = reportText(
      status(
        rep({
          published: ["one", "two"],
          failed: ["three"],
          banned: ["four"],
          removed: ["five"],
          posts: 12,
          posts_removed: 3,
        })
      )
    )
    expect(text).toBe(
      [
        "Пролитые (2):",
        "@one",
        "@two",
        "",
        "Не пролитые (1):",
        "@three",
        "",
        "Забаненные (1):",
        "@four",
        "",
        `${REMOVED_TEXT} (1):`,
        "@five",
      ].join("\n")
    )
  })

  it("у «не пролито» и «забанено» рядом с именем — причина, у пролитых и снятых — нет", () => {
    const text = reportText(
      status(
        rep({
          published: ["one"],
          failed: ["three"],
          banned: ["four"],
          removed: ["five"],
        }),
        [
          result("one", "пролито: не должно попасть в текст", 6),
          result("three", "сессия не проверена: нет связи"),
          result("four", "аккаунт больше не работает"),
          result("five", "у постов тоже не должно быть причины", 3),
        ]
      )
    )
    expect(text).toBe(
      [
        "Пролитые (1):",
        "@one",
        "",
        "Не пролитые (1):",
        "@three — сессия не проверена: нет связи",
        "",
        "Забаненные (1):",
        "@four — аккаунт больше не работает",
        "",
        `${REMOVED_TEXT} (1):`,
        "@five",
      ].join("\n")
    )
  })

  it("имя без причины остаётся именем — но с собакой (старый ответ, стенд)", () => {
    expect(reportText(status(rep({ failed: ["three"] }), [result("three")]))).toBe(
      "Не пролитые (1):\n@three"
    )
  })

  it("пустые исходы в текст не идут", () => {
    expect(reportText(status(rep({ published: ["one"], posts: 6 })))).toBe("Пролитые (1):\n@one")
  })

  it("отчёт целиком пустой — копировать нечего", () => {
    expect(reportText(status(rep()))).toBeNull()
  })

  it("ответ без полей о снятых постах (старый сервер, стенд) отчёт не роняет", () => {
    // поля необязательные (см. CampaignReport), поэтому набор собирается без
    // приведения типов: ответ без них — законный ответ
    const old: CampaignReport = { published: ["one"], failed: [], banned: [], posts: 6 }
    expect(reportText(status(old))).toBe("Пролитые (1):\n@one")
    expect(REPORT_BLOCK.removed).toBe(REMOVED_TEXT)
  })

  it("шаг чтения уведомлений подписан по-русски", () => {
    expect(STEP_LABEL.notices).toBe("уведомления")
  })

  it("отчёт прошлого запуска помечен первой строкой", () => {
    expect(reportText(restored(status(rep({ published: ["one"], posts: 6 }))))).toBe(
      `${RESTORED_TEXT}\n\nПролитые (1):\n@one`
    )
  })

  it("у свежего прохода пометки прошлого запуска нет", () => {
    expect(reportText(status(rep({ published: ["one"], posts: 6 })))).not.toContain(RESTORED_TEXT)
  })
})

describe("итог по аккаунтам", () => {
  it("исход: забанен, ни одного поста, целиком, частично", () => {
    expect(outcomeOf({ ...result("a", undefined, 6), banned: true }, 6)).toBe("banned")
    expect(outcomeOf(result("a"), 6)).toBe("failed")
    expect(outcomeOf(result("a", undefined, 6), 6)).toBe("full")
    expect(outcomeOf(result("a", undefined, 4), 6)).toBe("partial")
  })

  it("причины неудач сгруппированы, частые первыми; у опубликованных целиком — не считаются", () => {
    const results = [
      result("a", "капча"),
      result("b", "пост отклонён", 4),
      result("c", "пост отклонён", 2),
      result("d", "лишнее", 6),
      result("e"),
    ]
    expect(groupReasons(results, 6)).toEqual([
      ["пост отклонён", 2],
      ["капча", 1],
    ])
  })
})
