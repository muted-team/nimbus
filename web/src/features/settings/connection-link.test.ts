import { describe, expect, it } from "vitest"

import { externalConnection } from "./connection-link"

describe("manual external connection address", () => {
  it("copies a validated address and a link using the currently bound port", () => {
    expect(externalConnection(" 203.0.113.10 ", 8740)).toEqual({ address: "203.0.113.10", link: "http://203.0.113.10:8740" })
    expect(externalConnection("Nimbus.Example.com", 9999)).toEqual({ address: "nimbus.example.com", link: "http://nimbus.example.com:9999" })
  })

  it.each(["", "0.0.0.0", "0", "0x0", "0.0", "999.1.1.1", "a b.example", "example.com/path", "example.com?key=secret", "user:password@example.com", "https://example.com", "example.com:443"])(
    "rejects non-address or wildcard input %s",
    (value) => expect(externalConnection(value, 8740)).toBeNull()
  )

  it.each(["203.0.113.010", "203.0.113.001", "0300.168.1.5", "127.1", "2130706433", "0x7f000001"])(
    "never silently rewrites noncanonical IPv4 %s to another address",
    (value) => expect(externalConnection(value, 8740)).toBeNull()
  )
})
