import { getLanguage } from "@/lib/i18n"
import { buildProxyLine, parseProxyLine } from "./proxy-line"

/* Прокси noshadow: страна, липкость IP и порт задаются не в панели провайдера,
   а суффиксами в ЛОГИНЕ, пароль при этом один (dev/NOSHADOW.md, проверено
   17.10.2026):

     ЛОГИН[-country-XX][-session-ID][-time-МИНУТЫ]:ПАРОЛЬ@proxy.noshadow.pro:ПОРТ

   - без -time IP меняется на каждом новом соединении (ротация);
   - -time-N держит один IP N минут; -session-ID без -time IP НЕ держит,
     зато делает строку отдельной — у пачки одинаковых строк сервер оставил
     бы одну;
   - http — порт 6969, socks5 — 9696, логин один на оба.

   Здесь — разбор и сборка такой строки. Строки человека модуль сам не меняет:
   генерация и правка идут только по его кнопке. */

export const NOSHADOW_HOST = "proxy.noshadow.pro"

export type Transport = "http" | "socks"

const PORT: Record<Transport, string> = { http: "6969", socks: "9696" }
const SCHEME: Record<Transport, string> = { http: "http", socks: "socks5" }

/** Сколько минут держать IP: потолок провайдера — 120. */
export const MAX_MINUTES = 120
export const DEFAULT_MINUTES = 15

/* Страны, в которых у noshadow есть выход: прогон всех 249 кодов ISO
   17.10.2026 (dev/_probe_noshadow_countries.py). На остальные прокси отвечает
   502/503 — выхода нет. */
export const NOSHADOW_COUNTRIES = [
  "AE", "AG", "AI", "AO", "AR", "AT", "AU", "AW", "BA", "BB", "BD", "BE", "BF", "BG", "BH",
  "BI", "BM", "BN", "BO", "BR", "BS", "BT", "BW", "BZ", "CA", "CD", "CG", "CI", "CL", "CM",
  "CO", "CR", "CV", "CW", "CY", "CZ", "DE", "DJ", "DK", "DO", "DZ", "EC", "EE", "EG", "ES",
  "ET", "FI", "FJ", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GH", "GM", "GN", "GP", "GQ",
  "GR", "GT", "GU", "GW", "GY", "HN", "HR", "HT", "ID", "IE", "IL", "IM", "IN", "IQ", "IS",
  "IT", "JE", "JM", "JO", "JP", "KE", "KH", "KN", "KR", "KW", "KY", "LA", "LB", "LC", "LI",
  "LK", "LR", "LS", "LT", "LU", "LV", "LY", "MA", "ME", "MG", "MK", "ML", "MM", "MN", "MO",
  "MQ", "MR", "MT", "MU", "MV", "MW", "MX", "MY", "NC", "NE", "NI", "NL", "NO", "NP", "NZ",
  "OM", "PA", "PE", "PH", "PK", "PL", "PR", "PS", "PT", "PY", "QA", "RE", "RO", "RS", "RW",
  "SA", "SB", "SC", "SD", "SE", "SG", "SI", "SK", "SL", "SN", "SO", "SR", "SS", "ST", "SV",
  "SX", "SZ", "TC", "TD", "TG", "TH", "TN", "TR", "TT", "TV", "TW", "TZ", "UA", "UG", "US",
  "UY", "VC", "VE", "VG", "VI", "VN", "WS", "YE", "YT", "ZA", "ZM", "ZW",
] as const

export interface Noshadow {
  /** логин аккаунта без суффиксов */
  base: string
  password: string
  /** код страны заглавными; пусто — суффикса нет, страну выбирает провайдер */
  country: string
  /** id липкой сессии; пусто — суффикса нет */
  session: string
  /** сколько минут держать IP; 0 — ротация на каждое соединение */
  minutes: number
  transport: Transport
  /** ссылка смены IP, если человек её приклеил к строке */
  rotateUrl: string
}

/* Суффиксы — в хвосте логина в любом порядке. Всё до первого из них — сам
   логин аккаунта. Хвост обязан разобраться целиком: незнакомый кусок значит
   чужой формат, и тогда строку не трогаем вовсе. */
const SUFFIX_START = /-(?:country|session|time)-/
const SUFFIX = /-(country|session|time)-([A-Za-z0-9]+)/g

/** Разобрать строку; null — это не noshadow или формат незнакомый. */
export function readNoshadow(line: string): Noshadow | null {
  const f = parseProxyLine(line)
  if (!f || f.host.toLowerCase() !== NOSHADOW_HOST || !f.login) return null
  const transport: Transport = f.scheme.startsWith("socks") ? "socks" : "http"
  const cut = f.login.search(SUFFIX_START)
  const base = cut < 0 ? f.login : f.login.slice(0, cut)
  const tail = cut < 0 ? "" : f.login.slice(cut)
  const out: Noshadow = { base, password: f.password, country: "", session: "", minutes: 0, transport, rotateUrl: f.rotateUrl }
  let used = 0
  for (const [whole, key, value] of tail.matchAll(SUFFIX)) {
    used += whole.length
    if (key === "country") out.country = value.toUpperCase()
    else if (key === "session") out.session = value
    else out.minutes = Number(value)
  }
  // минуты — только целое число: «-time-abc» дал бы NaN и прошёл бы проверку
  if (!base || used !== tail.length || !Number.isInteger(out.minutes) || out.minutes > MAX_MINUTES)
    return null
  return out
}

/** Собрать строку обратно — канонический вид, тот же, что хранит сервер. */
export function writeNoshadow(n: Noshadow): string {
  const login =
    n.base +
    (n.country ? `-country-${n.country}` : "") +
    (n.session ? `-session-${n.session}` : "") +
    (n.minutes > 0 ? `-time-${n.minutes}` : "")
  return buildProxyLine({
    scheme: SCHEME[n.transport],
    login,
    password: n.password,
    host: NOSHADOW_HOST,
    port: PORT[n.transport],
    rotateUrl: n.rotateUrl,
  })
}

/** Новый id липкой сессии: 8 случайных шестнадцатеричных знаков. */
export function newSession(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(4))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
}

/** Что поменять у строки; поле не задано — оставить как есть.
    minutes: 0 — ротация, N — один IP на N минут. */
export interface NoshadowPatch {
  country?: string
  minutes?: number
  transport?: Transport
  /** новая сессия — у липкой строки это новый IP */
  renew?: boolean
}

/** Применить правку. Липкому IP нужна сессия — строке без неё заводим новую;
    при переходе на ротацию сессию оставляем: без -time она IP не держит, а
    строка остаётся отдельной и не схлопнется с соседкой. Сам id не меняется
    никогда, кроме renew: тот же id — тот же IP, новый IP — только новый id. */
export function patchNoshadow(n: Noshadow, { renew, ...patch }: NoshadowPatch): Noshadow {
  const next = { ...n, ...patch }
  if (renew || (next.minutes > 0 && !next.session)) next.session = newSession()
  return next
}

export interface GenerateSpec {
  base: string
  password: string
  countries: string[]
  /** строк на каждую страну */
  perCountry: number
  /** 0 — ротация, N — один IP на N минут */
  minutes: number
  transport: Transport
}

/** Пачка строк: на каждую страну perCountry штук, у каждой своя сессия —
    разные строки, а при липком режиме ещё и разные IP. */
export function generateNoshadow(spec: GenerateSpec): string[] {
  return spec.countries.flatMap((country) =>
    Array.from({ length: spec.perCountry }, () =>
      writeNoshadow({
        base: spec.base,
        password: spec.password,
        country,
        session: newSession(),
        minutes: spec.minutes,
        transport: spec.transport,
        rotateUrl: "",
      })
    )
  )
}

/** Учётка из того, что вставил человек: целая строка noshadow или просто
    «логин:пароль» из карточки бота. Суффиксы в логине отбрасываются — их
    допишет генератор. null — ни то ни другое. */
export function readNoshadowAccount(text: string): { base: string; password: string } | null {
  const raw = text.trim()
  const n = readNoshadow(raw)
  if (n) return { base: n.base, password: n.password }
  // пароль без двоеточий: иначе «хост:порт:логин:пароль» сошёл бы за учётку
  const m = /^([^:\s@/]+):([^:\s]+)$/.exec(raw)
  if (!m) return null
  const cut = m[1].search(SUFFIX_START)
  return { base: cut < 0 ? m[1] : m[1].slice(0, cut), password: m[2] }
}

/** Учётки noshadow из списка: (логин, пароль) без повторов — из них генератор
    берёт аккаунт, не заставляя вставлять строку заново. */
export function noshadowAccounts(lines: string[]): { base: string; password: string }[] {
  const seen = new Map<string, { base: string; password: string }>()
  for (const line of lines) {
    const n = readNoshadow(line)
    if (n && !seen.has(n.base)) seen.set(n.base, { base: n.base, password: n.password })
  }
  return [...seen.values()]
}

const regionNames = new Map<string, Intl.DisplayNames | null>()

function namesForLanguage() {
  const language = getLanguage()
  if (regionNames.has(language)) return regionNames.get(language)
  try {
    const names = new Intl.DisplayNames([language], { type: "region" })
    regionNames.set(language, names)
    return names
  } catch {
    return null
  }
}

/** Название страны по-русски; нет в Intl — сам код. */
export function countryName(code: string): string {
  return namesForLanguage()?.of(code) ?? code
}
