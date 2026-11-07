import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"

import { Slider } from "./slider"

it("имя одиночного ползунка относится к фокусируемому input, а не только к обёртке", () => {
  const html = renderToStaticMarkup(createElement(Slider, { value: [80], "aria-label": "Сжатие, %" }))
  const input = html.match(/<input\b[^>]*type="range"[^>]*>/)?.[0]
  expect(input).toContain('aria-label="Сжатие, %"')
})

it("границы диапазона имеют разные имена и русские подписи вместо start/end range", () => {
  const html = renderToStaticMarkup(createElement(Slider, { value: [-10, 10], min: -360, max: 360, "aria-label": "Поворот, °" }))
  const inputs = html.match(/<input\b[^>]*type="range"[^>]*>/g) ?? []
  expect(inputs).toHaveLength(2)
  expect(inputs[0]).toContain('aria-label="Поворот, °, от"')
  expect(inputs[1]).toContain('aria-label="Поворот, °, до"')
  expect(inputs[0]).toContain('value="-10"')
  expect(inputs[1]).toContain('value="10"')
  expect(html).not.toContain("start range")
  expect(html).not.toContain("end range")
  expect(inputs[0]).toContain('aria-valuetext="−10"')
  expect(inputs[1]).toContain('aria-valuetext="10"')
})

it("фокус скрытого range показывает кольцо на видимом бегунке", () => {
  const html = renderToStaticMarkup(createElement(Slider, { value: [80], "aria-label": "Сжатие, %" }))
  const thumb = html.match(/<div\b[^>]*data-slot="slider-thumb"[^>]*>/)?.[0]
  expect(thumb).toContain("has-[:focus-visible]:ring-3")
  expect(thumb).toContain("has-[:focus-visible]:outline-hidden")
})
