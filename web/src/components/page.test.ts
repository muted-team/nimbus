import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Page } from "./page"

describe("page scroll ownership", () => {
  it("keeps long forms in a viewport scroll container instead of the WebKit document", () => {
    const html = renderToStaticMarkup(createElement(Page, null, "Settings"))
    expect(html).toContain("overflow-y-auto")
    expect(html).toContain("md:h-svh")
    expect(html).not.toContain("min-h-full")
  })

  it("leaves fill pages scrolling inside their existing lists", () => {
    const html = renderToStaticMarkup(createElement(Page, { fill: true }, "Accounts"))
    expect(html).toContain("md:h-svh")
    expect(html).not.toContain("overflow-y-auto")
  })
})
