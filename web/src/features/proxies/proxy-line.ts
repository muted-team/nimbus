/* Разбор и сборка одной строки прокси в каноническом виде — том самом, в
   котором её хранит сервер после разбора при добавлении (modules/proxies.py):

     схема://[логин:пароль@]хост:порт[ ссылка_смены_IP]

   Другие форматы («host:port:user:pass» и подобные) сюда попасть не могут —
   их разбор нужен только один раз, при добавлении, и он остаётся на сервере.
   Здесь — разбор ровно этого единственного вида, для формы правки по полям. */

/* Учётка в каноническом адресе лежит ЗАКОДИРОВАННОЙ процентами: сервер
   пропускает её через quote, потому что дальше эта строка уходит в curl как
   URL. Для показа её надо раскодировать обратно — иначе в поле правки вместо
   пароля `gjfnix054$` видно `gjfnix054%24`, а поле заведено ровно затем, чтобы
   сверить пароль посимвольно. При сборке кодируем обратно: иначе @, / и #
   меняют разбор URL; сервер бережёт уже закодированную строку от повторного
   кодирования (modules/proxies._quote_cred). */
function decodeCred(value: string): string {
  try {
    return decodeURIComponent(value.replace(/%(?![0-9a-f]{2})/gi, "%25"))
  } catch {
    // Invalid UTF-8 escapes are left as entered rather than crashing the editor.
    return value
  }
}

export interface ProxyLineFields {
  scheme: string
  /** логин как его ввёл человек: раскодированный, без процентов */
  login: string
  /** пароль как его ввёл человек: раскодированный, без процентов */
  password: string
  /** хост как есть; у IPv6 — вместе с квадратными скобками */
  host: string
  port: string
  /** ссылка смены IP; пустая строка — её нет */
  rotateUrl: string
}

const LINE_RE =
  /^([a-zA-Z][a-zA-Z0-9]*):\/\/(?:([^:@\s]*):([^@\s]*)@)?(\[[^\]\s]+\]|[^:@\s]+):(\d+)(?:\s+(\S+))?$/

/** Разобрать строку по каноническому виду; null — строка на него не похожа
    (мусор, старый формат, ручная опечатка) — такую показываем как есть, а не
    теряем молча. */
export function parseProxyLine(line: string): ProxyLineFields | null {
  const m = LINE_RE.exec(line.trim())
  if (!m) return null
  const [, scheme, login, password, host, port, rotateUrl] = m
  return {
    scheme,
    login: decodeCred(login ?? ""),
    password: decodeCred(password ?? ""),
    host,
    port,
    rotateUrl: rotateUrl ?? "",
  }
}

/** Собрать строку обратно — тот же канонический вид, что читает
    `parseProxyLine`. Сервер её всё равно перепроверит своим разбором. */
export function buildProxyLine(f: ProxyLineFields): string {
  // The server's paste parser splits raw apostrophes even inside a URL.
  const encode = (value: string) => encodeURIComponent(value).replace(/'/g, "%27")
  const auth = f.login || f.password ? `${encode(f.login)}:${encode(f.password)}@` : ""
  const base = `${f.scheme}://${auth}${f.host}:${f.port}`
  const rotate = f.rotateUrl.trim()
  return rotate ? `${base} ${rotate}` : base
}
