import QRCode from "qrcode"

export function createPhoneQr(link: string): Promise<string> {
  const url = new URL(link)
  const parts = url.hostname.split(".").map(Number)
  const privateAddress =
    parts.length === 4 &&
    parts.every((part) => Number.isInteger(part) && part >= 0 && part <= 255) &&
    (parts[0] === 10 ||
      (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
      (parts[0] === 192 && parts[1] === 168))
  if (
    url.protocol !== "http:" ||
    !privateAddress ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/"
  ) {
    return Promise.reject(new Error("Неверный адрес интерфейса для телефона"))
  }
  return QRCode.toDataURL(link, {
    width: 224,
    margin: 4,
    errorCorrectionLevel: "M",
  })
}
