export function generatePassword(minLength: number): string {
  const alphabet =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
  return Array.from(
    crypto.getRandomValues(new Uint8Array(Math.max(16, minLength))),
    (byte) => alphabet[byte & 63]
  ).join("")
}
