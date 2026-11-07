import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Button, buttonVariants } from "./button"

describe("размеры кнопок на сенсорном экране", () => {
  it.each(["xs", "sm", "default"] as const)("%s — не меньше 40px", (size) => {
    expect(buttonVariants({ size })).toContain("pointer-coarse:h-10")
  })

  it.each(["icon-xs", "icon-sm", "icon"] as const)("%s — не меньше 40px", (size) => {
    expect(buttonVariants({ size })).toContain("pointer-coarse:size-10")
  })

  it("обычные размеры desktop остаются компактными", () => {
    expect(buttonVariants({ size: "xs" })).toContain("h-6")
    expect(buttonVariants({ size: "sm" })).toContain("h-7")
    expect(buttonVariants({ size: "icon-xs" })).toContain("size-6")
  })

  it("disabled остаётся недоступным для нажатия", () => {
    const html = renderToStaticMarkup(createElement(Button, { disabled: true }, "Удалить"))
    expect(html).toContain('disabled=""')
  })
})
