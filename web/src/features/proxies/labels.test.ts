import { describe, expect, it } from "vitest"

import { checkedAgo, rotateOutcome, rotateWait, rotatedText } from "./labels"

/* Тексты строки прокси: когда проверяли и сколько ещё
   ждать смены IP. Время считаем от «сейчас», а не от часов машины. */

const NOW = 1_800_000_000_000 // мс

/* Отметки приходят от сервера числами; строка вместо числа — чужая (так когда-то
   отдавал стенд), и она не должна превращаться в «NaN» на экране. */
const garbage = (value: unknown) => value as number

describe("когда проверяли", () => {
  it("вердикта не было — так и говорим", () => {
    expect(checkedAgo(null, NOW)).toBe("ещё не проверялся")
  })

  it("полминуты назад — «только что»", () => {
    expect(checkedAgo(NOW / 1000 - 30, NOW)).toBe("только что")
  })

  it("две минуты назад", () => {
    expect(checkedAgo(NOW / 1000 - 120, NOW)).toBe("2 мин назад")
  })

  it("три часа назад", () => {
    expect(checkedAgo(NOW / 1000 - 3 * 3600, NOW)).toBe("3 ч назад")
  })

  it("два дня назад", () => {
    expect(checkedAgo(NOW / 1000 - 2 * 86400, NOW)).toBe("2 дн назад")
  })

  it("часы сервера убежали вперёд — врём не в минус", () => {
    expect(checkedAgo(NOW / 1000 + 60, NOW)).toBe("только что")
  })

  it("отметку не прочитать — говорим об этом, а не «NaN дн назад»", () => {
    expect(checkedAgo(garbage("2026-09-17T01:00:00Z"), NOW)).toBe("время проверки неизвестно")
    expect(checkedAgo(Number.NaN, NOW)).toBe("время проверки неизвестно")
    expect(checkedAgo(undefined, NOW)).toBe("ещё не проверялся")
  })
})

describe("сколько ждать смены IP", () => {
  it("ждать нечего — отсчёта нет", () => {
    expect(rotateWait(0)).toBeNull()
  })

  it("секунды", () => {
    expect(rotateWait(30)).toBe("смена через 30 с")
  })

  it("минуты", () => {
    expect(rotateWait(150)).toBe("смена через 3 мин")
  })
})

describe("итог смены IP", () => {
  it("адреса до и после", () => {
    expect(rotatedText("1.2.3.4", "5.6.7.8")).toBe("IP сменён: 1.2.3.4 → 5.6.7.8.")
  })

  it("адресов не назвали — не выдумываем", () => {
    expect(rotatedText(null, null)).toBe("IP сменён.")
  })

  it("адрес сменился — сервер сказал ok", () => {
    expect(rotateOutcome({ ok: true, ip_before: "1.2.3.4", ip_after: "5.6.7.8" })).toEqual({
      ok: true,
      text: "IP сменён: 1.2.3.4 → 5.6.7.8.",
    })
  })

  it("сервер сказал ok, а адрес тот же — говорим, что не сменился", () => {
    expect(
      rotateOutcome({ ok: true, ip_before: "1.2.3.4", ip_after: "1.2.3.4", reason: "IP не сменился" })
    ).toEqual({ ok: false, text: "IP не сменился: 1.2.3.4." })
  })

  it("ссылку дёрнуть не удалось — строчная причина сервера как в тосте", () => {
    expect(rotateOutcome({ ok: false, reason: "провайдер просит подождать" })).toEqual({
      ok: false,
      text: "Провайдер просит подождать.",
    })
    expect(rotateOutcome({ ok: false, reason: "ссылка смены IP не открылась" })).toEqual({
      ok: false,
      text: "Ссылка смены IP не открылась.",
    })
  })

  it("причина без точки — точка ставится", () => {
    expect(rotateOutcome({ ok: false, reason: "ссылка ротации не задана" })).toEqual({
      ok: false,
      text: "Ссылка ротации не задана.",
    })
  })

  it("причины нет — своя строка", () => {
    expect(rotateOutcome({ ok: false })).toEqual({ ok: false, text: "Не удалось сменить IP." })
  })
})
