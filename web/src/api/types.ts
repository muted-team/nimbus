/* Ответы API программы (main.py). Поля — ровно как отдаёт сервер. */

export interface ProfilePosts {
  count?: number | null
  views?: number | null
  /** постов в тени; null — ещё не проверяли */
  shadow?: number | null
}

export interface Profile {
  /** имя профиля, если оно отличается от логина */
  nickname?: string | null
  verified?: boolean | null
  private_account?: boolean | null
  followers?: number | null
  likes?: number | null
  posts?: ProfilePosts
  /** unix-время последнего обновления профиля, секунды */
  fetched_at?: number | null
}

/** Числа аккаунта из центра автора: их отдаёт сам аккаунт по своим кукам —
    без подписи, без анонимного сбора профиля и без прокси на него
    (modules/studio.py:counters). Поля сгруппированы как в ответе. */
export interface StudioCounters {
  /** настоящие посты: сорвавшиеся публикации сюда не входят */
  posts?: number | null
  photo_posts?: number | null
  /** непубличные посты */
  private_posts?: number | null
  followers?: number | null
  following?: number | null
  /** посетители профиля, которых ещё не смотрели */
  unread_visitors?: number | null
}

/** Числа студии по аккаунтам. Аккаунта в наборе нет — числа собрать не
    вышло (нет сохранённого входа или сессия не ответила). */
export type StudioCountersMap = Record<string, StudioCounters>

export interface Account {
  username: string
  has_session: boolean
  has_totp: boolean
  has_email: boolean
  /** unix-время сохранения аватарки или null */
  avatar: number | null
  profile: Profile | null
  /** Страна аккаунта по данным самого TikTok (кука store-country-code
      сохранённой сессии, например "US"). Не из строки, которой аккаунт
      добавляли: там продавец пишет что угодно. Нет сессии — null. */
  region: string | null
  /** Язык аккаунта оттуда же. Сейчас TikTok его в сессию не кладёт, поэтому
      у всех null — столбца в таблице нет, поле оставлено на будущее. */
  lang: string | null
}

/** Правка одного аккаунта — только изменённые поля (POST /api/accounts/update).
    Непустая строка — новое значение, пустая — снять поле (кроме username/
    password, их снять нельзя), поле отсутствует в объекте — не трогаем. */
export interface AccountPatch {
  username?: string
  password?: string
  totp_secret?: string
  email?: string
  email_password?: string
}

/** Секреты одного аккаунта открытым текстом (GET /api/accounts/secrets) —
    только для формы ручной правки: владелец сверяет, не опечатался ли.
    Ключа нет, если поля не было сохранено. */
export interface AccountSecrets {
  password?: string
  totp_secret?: string
  email?: string
  email_password?: string
}

export interface BannedAccount {
  username: string
  /** unix-время отключения, секунды */
  banned_at?: number | null
  ban_reason?: string | null
}

export interface AccountsResponse {
  accounts: Account[]
  banned: BannedAccount[]
}

export interface AvatarsResponse {
  avatars: Record<string, string>
}

/** Аккаунт, строка которого перезаписала уже существующего (повторное
    добавление — не дубль, modules/accounts.py:add_accounts_bulk). */
export interface UpdatedAccount {
  username: string
  /** поля, значение которых строка заменила: password, totp_secret, email,
      email_password. Поля, которых в строке нет, у аккаунта сохраняются */
  replaced: string[]
}

export interface BulkAddResponse {
  added: string[]
  /** перезаписанные аккаунты; ключа нет, когда перезаписей не было, — тогда
      добавились только новые. Маршрут /api/accounts/bulk отдаёт его не сразу:
      `updated` считает modules/accounts.py, а до морды он доезжает с T-150 */
  updated?: UpdatedAccount[]
  errors: { line: number; reason: string }[]
}

export interface LoginResponse {
  ok: boolean
  username: string
  reason?: string
  banned?: boolean
}

export interface ProfilesStatus {
  running: boolean
  total: number
  done: number
  ok: number
  current?: string[]
  /** ещё не готовые: в работе и в очереди */
  pending?: string[]
  failed: { username: string; reason: string }[]
  error?: string | null
  /** номер изменения: снимок с меньшим устарел */
  seq: number
}

/** Итог чистки одного аккаунта: сколько снесли или почему не вышло. */
export interface PurgeResult {
  deleted?: number
  total?: number
  error?: string
}

export interface PurgeStatus {
  current: string[]
  /** итоги последних чисток по аккаунтам */
  results?: Record<string, PurgeResult>
}

export type ProxyState = "unknown" | "checking" | "ok" | "dead"

export interface ProxyHealth {
  proxy: string
  state: ProxyState
  /** определённый тип прокси: http, socks5, socks4…; null — ещё не выяснили */
  scheme?: string | null
  /** мс до самого прокси */
  ping?: number | null
  /** мс ответа TikTok через прокси */
  ms?: number | null
  error?: string | null
  /** сколько дел сейчас идёт через прокси */
  busy?: number
  /** unix-время последней проверки, секунды; null — ещё не проверялся */
  checked_at?: number | null
  /** unix-время, когда пул проверит строку сам, секунды; null — не запланировано */
  next_check_at?: number | null
  /** есть ли у строки ссылка смены IP */
  rotating?: boolean
  /** секунд до следующей смены IP; 0 — можно сейчас */
  rotate_in?: number
  /** Страна прокси двумя буквами («US») по вердикту самого TikTok: страницу
      /signup он отдаёт с регионом, определённым по нашему IP. Не geo-сервис.
      null — ещё не спрашивали. Переспрашивается при смене IP и раз в сутки:
      у ротационных прокси IP меняется, а с ним и страна. */
  country?: string | null
  /** оператор выхода при последней удачной проверке («Comcast Cable…»);
      null — ещё не узнавали */
  org?: string | null
  /** отмечена ли строка как годная для ВХОДА в аккаунт */
  login?: boolean
  /** отмечена ли строка как годная для ПУБЛИКАЦИИ */
  publish?: boolean
  /** включена ли строка; выключенная остаётся в списке, но в работу не идёт */
  enabled?: boolean
}

export interface ProxiesResponse {
  proxies: string[]
  enabled: boolean
  /** сколько строк со ссылкой смены IP */
  rotating: number
  health: ProxyHealth[]
  /** строки, которые разобрать не удалось (только в ответе PUT) */
  errors?: { line: number; error: string }[]
}

/** Ответ смены IP у одной строки: итог плюс свежие отметки (как GET /api/proxies). */
export interface ProxyRotateResponse extends ProxiesResponse {
  ok: boolean
  /** ссылку смены IP не дёргали: у строки её нет; считает modules/proxies.py,
      в ответе появится с T-150 */
  skipped?: boolean
  /** адрес действительно сменился (сверка «до» и «после»); считает
      modules/proxies.py, в ответе появится с T-150 */
  changed?: boolean
  ip_before?: string | null
  ip_after?: string | null
  reason?: string | null
}

export type CampaignState = "idle" | "running" | "stopping" | "waiting" | "stopped" | "error"

export type CampaignStep =
  | "rotate"
  | "cleanup"
  | "login"
  | "wait_proxy"
  | "notices"
  | "publishing"

export interface CampaignWorker {
  account: string
  step: CampaignStep | string
  posts_done: number
}

export interface CampaignResult {
  account: string
  ok: boolean
  posts_done: number
  posts_lost?: number
  reason?: string | null
  banned?: boolean
  /** сколько постов аккаунта TikTok снял за нарушение правил (по уведомлениям);
      у стенда и текущего сервера поле есть всегда, у старого сервера может не
      быть */
  removed?: number
}

export interface CampaignReport {
  published: string[]
  failed: string[]
  banned: string[]
  /** аккаунты, с которых TikTok снял посты за нарушение правил; у стенда и
      текущего сервера поле есть всегда, у старого сервера может не быть —
      поэтому оно необязательное, а места чтения подстраховываются `?? []` */
  removed?: string[]
  posts: number
  /** сколько постов снято за нарушение правил, по всем аккаунтам отчёта */
  posts_removed?: number
}

export type MediaKind = "photo" | "video"

export interface CampaignStatus {
  status: CampaignState
  /** true — отчёт поднят с диска после перезапуска, а не свежий проход;
      сервер кладёт поле и в дефолт, и при подъёме, поэтому оно обязательное */
  restored: boolean
  accounts_total: number
  accounts_done: number
  queued: string[]
  posts_per_account: number
  threads: number
  workers: CampaignWorker[]
  results: CampaignResult[]
  stop_reason: string | null
  started_at: string | null
  finished_at: string | null
  repeat: boolean
  media: MediaKind
  round: number
  rounds_done: number
  next_run_at: string | null
  posts_total: number
  posts_done: number
  posts_failed: number
  report: CampaignReport
}

export type Creatives = "unique" | "copies" | "single"
export type RepeatUnit = "min" | "hour"

/** Форма публикации, как её хранит сервер (config.campaign_form). */
export interface CampaignForm {
  posts_per_account?: number
  /** 0 — не сносить, -1 — всё, -2 — сколько зальём, N */
  delete_before?: number
  creatives?: Creatives
  keep_photos?: boolean
  media?: MediaKind
  slots?: string[]
  video_slots?: string[]
  caption?: string
  title?: string
  min_delay_ms?: number
  max_delay_ms?: number
  repeat?: boolean
  repeat_unit?: RepeatUnit
  repeat_min?: number
  repeat_max?: number
}

export interface CampaignStartBody extends CampaignForm {
  accounts?: string[]
}

export type ProxyOnDeath = "swap" | "stop"
export type BrowserProfile = "chrome152" | "firefox155"

export interface Settings {
  browser_profile: BrowserProfile
  browser_profile_active: BrowserProfile
  browser_profiles: BrowserProfile[]
  /** наш сервер: адрес, по которому ходим сейчас, встроенный и задан ли свой */
  server: { url: string; default: string; custom: boolean }
  threads: number
  threads_max: number
  /** прокси умер посреди публикации: пересесть на другой живой или остановить поток */
  proxy_on_death: ProxyOnDeath
  /** сколько минут ждать перегруженный сервер, прежде чем сдаться */
  server_wait_min: number
  server_wait_max: number
  port: number
  host: string
  bound: { host: string; port: number }
  /** отдельный вход из локальной сети; включается без перезапуска окна */
  phone: { on: boolean; active: boolean; supported?: boolean; connected?: boolean; links: string[] }
  password: { available: boolean; set: boolean; min_len: number; required?: boolean }
}

/** GET /api/server/check: доступен — задержка, нет — причина для человека */
export type ServerCheck = { ok: true; ms: number } | { ok: false; error: string }

export type SettingsPatch = Partial<
  Pick<Settings, "threads" | "proxy_on_death" | "server_wait_min" | "port" | "host" | "browser_profile">
> & {
  phone_access?: boolean
  password?: string
  /** свой адрес нашего сервера; пусто — встроенный */
  server?: string
}

export const UNIQ_KEYS = [
  "rotate",
  "scale",
  "compress",
  "brightness",
  "contrast",
  "saturation",
  "gamma",
  "hue",
] as const
export type UniqKey = (typeof UNIQ_KEYS)[number]

export interface UniqParam {
  enabled: boolean
  locked: boolean
  min: number
  max: number
}

export type UniqSettings = {
  enabled: boolean
  limits: Record<UniqKey, [number, number]>
} & Record<UniqKey, UniqParam>

export interface UniqPreviewItem {
  image?: string
  name?: string
  applied?: Partial<Record<UniqKey, number>>
  bytes?: number
  meta?: Record<string, string>
  error?: string
}

export interface UniqPreviewResponse {
  items: UniqPreviewItem[]
}

export type LogLevel = "" | "ok" | "warn" | "err"

export interface LogItem {
  /** номер записи сервера; 0 — запись самого интерфейса */
  seq: number
  /** unix-время, секунды */
  ts: number
  level: LogLevel
  account?: string
  text: string
  debug?: boolean
  /** источник подробности: login, publish, anon… */
  source?: string
  /** true — запись поднята из файла событий прошлого запуска (modules/eventlog.py);
      у свежих записей поля нет */
  past?: boolean
}

export interface Release {
  version: string
  date: string
  changes: string[]
}

export interface Changelog {
  version: string | null
  releases: Release[]
}

export interface SlotInfo {
  path: string
  exists: boolean
  photos: number
  videos: number
}

/** Папка программы — media/<имя> рядом с ней (modules/photo_source.library) */
export interface MediaFolder {
  name: string
  /** абсолютный путь — им папка и стоит в форме публикации */
  path: string
  photos: number
  videos: number
  /** unix-время последней правки */
  mtime: number
  /** свежие фото — обложка карточки в «Креативах» */
  preview: Pick<MediaFile, "file" | "mtime">[]
}

export interface MediaFile {
  file: string
  kind: MediaKind
  size: number
  mtime: number
}

export interface MediaLibrary {
  /** где лежат папки программы; путь внутри — папка программы */
  root: string
  /** свежие сверху */
  folders: MediaFolder[]
}

export interface AuthState {
  required: boolean
  ok: boolean
}

/* ── ключ к нашему серверу (modules/remote.py, GET/PUT /api/license) ──── */

/** none — ключа нет; error — сервер не ответил или отказал (текст в error) */
export type LicenseStatus = "active" | "disabled" | "none" | "error" | string

export interface LicenseInfo {
  /** последние 4 знака ключа, «…ab12»; пусто — ключа нет */
  key: string
  status: LicenseStatus
  balance?: number | null
  currency?: string
  name?: string
  avatar_url?: string | null
  /** unix-время окончания, секунды; null — бессрочно */
  expires_at?: number | null
  error?: string
}

export interface LicenseCharge {
  /** unix-время списания, секунды */
  at: number
  action: string
  /** действие по-человечески: «Пост с фото», «Вход» */
  title: string
  /** аккаунт или пачка: «alice» / «u1, u2, u3 +2»; пусто у движений баланса */
  account: string
  /** пояснение движения баланса (пополнение, покупка в другом сервисе) */
  note: string
  /** credit — начисление, debit — списание */
  kind: "credit" | "debit"
  /** сумма без знака, ₽; 0 — бесплатно */
  amount: number | null
  ok: boolean
  /** почему не удалось; пусто у удачного */
  error: string
}

export interface LicenseHistory {
  items: LicenseCharge[]
  /** курсор следующей страницы; null — дальше нет */
  next: string | null
}
