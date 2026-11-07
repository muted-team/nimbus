import { getLanguage, t } from "@/lib/i18n"
/* Форматирование чисел, дат и длительностей для интерфейса. Правила владельца:
   дробная часть — ровно два знака, целое — без запятой; лишнее округляется по
   третьему знаку, а шум плавающей точки гасится через toFixed(6). */

const NBSP_THIN = " "

/** 5117.5599999 -> "5 117,56"; 44000 -> "44 000"; 1.005 -> "1,01". */
export function fmtDec(n: number): string {
  const [intPart, frac] = Math.abs(n).toFixed(6).split(".")
  let whole = Number(intPart)
  let cents = Number(frac.slice(0, 2)) + (Number(frac.charAt(2)) >= 5 ? 1 : 0)
  if (cents === 100) {
    whole += 1
    cents = 0
  }
  let s = String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, NBSP_THIN)
  if (cents) s += (getLanguage() === "en" ? "." : ",") + String(cents).padStart(2, "0")
  return (n < 0 && (whole || cents) ? "−" : "") + s
}

/** Со знаком: сразу видно, в какую сторону увело. */
export function fmtSigned(n: number): string {
  return (n > 0 ? "+" : "") + fmtDec(n)
}

/** Целое с разрядами: 12500 -> "12 500". */
export function fmtInt(n: number | null | undefined): string {
  if (n == null) return "—"
  return fmtDec(Math.round(n))
}

const UNITS: [string, number][] = [
  ["B", 1e9],
  ["M", 1e6],
  ["K", 1e3],
]

/** Число в выбранной ступени: до сотни — с десятой долей, дальше — целым. */
function inUnit(abs: number, size: number): string {
  const v = abs / size
  return (v >= 100 ? String(Math.round(v)) : String(Math.round(v * 10) / 10)).replace(".", getLanguage() === "en" ? "." : ",")
}

/** Компактно для статистики: 1234 -> "1,2K", 2600000 -> "2,6M". */
export function fmtCompact(n: number | null | undefined): string {
  if (n == null) return "—"
  const sign = n < 0 ? "−" : ""
  const abs = Math.abs(n)
  for (let i = 0; i < UNITS.length; i++) {
    const [suffix, size] = UNITS[i]
    if (abs < size) continue
    // 999 950 округлилось бы до «1000K» — это уже миллион, ступенью выше
    if (inUnit(abs, size) === "1000" && i > 0) {
      return sign + inUnit(abs, UNITS[i - 1][1]) + UNITS[i - 1][0]
    }
    return sign + inUnit(abs, size) + suffix
  }
  return sign + String(Math.round(abs))
}

/** Вес файла: до мегабайта — целые КБ, дальше — МБ с копейками. */
export function fmtSize(bytes: number): string {
  if (bytes < 1024 * 1024) return t("{0} КБ", [Math.max(1, Math.round(bytes / 1024))])
  return t("{0} МБ", [fmtDec(bytes / (1024 * 1024))])
}

const pad = (n: number) => String(n).padStart(2, "0")

/** Часы:минуты:секунды по unix-времени в секундах. */
export function fmtClock(tsSeconds: number): string {
  const d = new Date(tsSeconds * 1000)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** ISO-время: сегодня — только часы, иначе дата и часы. */
export function fmtDateTime(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  return sameDay ? hm : `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${hm}`
}

/** «4 ч 30 мин» / «45 мин 10 с» / «30 с» — сколько осталось до iso. */
export function fmtUntil(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—"
  const ms = new Date(iso).getTime() - now
  if (Number.isNaN(ms) || ms <= 0) return t("скоро")
  const sec = Math.round(ms / 1000)
  if (sec >= 3600) {
    // минуты округляем от общего числа: иначе 1 ч 59,5 мин давало «1 ч 60 мин»
    const min = Math.round(sec / 60)
    const h = Math.floor(min / 60)
    const m = min % 60
    return m ? t("{0} ч {1} мин", [h, m]) : t("{0} ч", [h])
  }
  if (sec >= 60) {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return s ? t("{0} мин {1} с", [m, s]) : t("{0} мин", [m])
  }
  return t("{0} с", [sec])
}

/** Длительность на глаз: «2 ч 15 мин», «12 мин», «40 с». Для оценок вроде
    «осталось ≈»: секунды при минутах — шум, они меняются каждый тик. */
export function fmtSpan(ms: number): string {
  const sec = Math.max(0, Math.round(ms / 1000))
  if (sec < 60) return t("{0} с", [sec])
  const min = Math.round(sec / 60)
  if (min < 60) return t("{0} мин", [min])
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? t("{0} ч {1} мин", [h, m]) : t("{0} ч", [h])
}

/** «5 мин назад» / «3 ч назад» / «2 дн назад» / «12.09» — когда это было, одна
    запись на все экраны. Метка из будущего (часы разъехались) — «только что». */
export function fmtAgo(tsSeconds: number | null | undefined, now = Date.now()): string {
  if (!tsSeconds) return "—"
  const sec = Math.round((now - tsSeconds * 1000) / 1000)
  if (sec < 60) return t("только что")
  if (sec < 3600) return t("{0} мин назад", [Math.floor(sec / 60)])
  if (sec < 86400) return t("{0} ч назад", [Math.floor(sec / 3600)])
  if (sec < 7 * 86400) return t("{0} дн назад", [Math.floor(sec / 86400)])
  const d = new Date(tsSeconds * 1000)
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}`
}

/** Русское множественное число: plural(5, ["аккаунт", "аккаунта", "аккаунтов"]). */
export function plural(n: number, forms: [string, string, string]): string {
  if (getLanguage() === "en") return t(Math.abs(n) === 1 ? forms[0] : forms[2])
  const abs = Math.abs(n) % 100
  const last = abs % 10
  if (abs > 10 && abs < 20) return t(forms[2])
  if (last > 1 && last < 5) return t(forms[1])
  if (last === 1) return t(forms[0])
  return t(forms[2])
}

/** Число и слово: count(5, ["пост", "поста", "постов"]) -> "5 постов". */
export function count(n: number, forms: [string, string, string]): string {
  return `${fmtInt(n)} ${plural(n, forms)}`
}

/** Первая буква заглавная, точка в конце — для текстов сервера в тостах. */
export function sentence(text: string): string {
  const t = text.trim()
  if (!t) return t
  const s = t.charAt(0).toUpperCase() + t.slice(1)
  return /[.!?…:]$/.test(s) ? s : `${s}.`
}
