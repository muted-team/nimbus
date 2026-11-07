import { describe, expect, it } from "vitest"
import { createPhoneQr } from "./phone-qr"

describe("QR для телефона", () => {
  it("создаёт локальное изображение только из адреса интерфейса", async () => {
    const qr = await createPhoneQr("http://192.168.1.5:8740")
    expect(qr).toMatch(/^data:image\/png;base64,/)
  })

  it("не кодирует пароль или адрес чужого сервиса", async () => {
    for (const link of [
      "http://user:password@192.168.1.5:8740",
      "https://example.com",
      "http://0.0.0.0:8740",
      "http://127.0.0.1:8740",
    ]) {
      await expect(createPhoneQr(link)).rejects.toThrow()
    }
  })
})
