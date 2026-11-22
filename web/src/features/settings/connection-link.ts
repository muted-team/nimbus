/** Manual address only; it is not a probe of inbound access or IP stability. */
export function externalConnection(
  raw: string,
  port: number
): { address: string; link: string } | null {
  const host = raw.trim()
  if (!host || !/^[a-z\d]+(?:[.-][a-z\d]+)*$/i.test(host)) return null
  try {
    const url = new URL(`http://${host}:${port}`)
    if (url.hostname === "0.0.0.0" || url.hostname !== host.toLowerCase()) return null
    return { address: url.hostname, link: url.origin }
  } catch {
    return null
  }
}
