import { spawnSync } from "node:child_process"
import { createElement, Fragment, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, expect, it, vi } from "vitest"

import { api } from "@/api/client"
import { keys, queryClient } from "@/api/query-client"
import type { ProxiesResponse } from "@/api/types"

vi.mock("@/components/ui/sheet", () => ({
  Sheet: ({ children }: PropsWithChildren) => createElement(Fragment, null, children),
  SheetContent: ({ children }: PropsWithChildren) => createElement("section", null, children),
  SheetHeader: ({ children }: PropsWithChildren) => createElement("header", null, children),
  SheetTitle: ({ children }: PropsWithChildren) => createElement("h2", null, children),
  SheetFooter: ({ children }: PropsWithChildren) => createElement("footer", null, children),
}))

import { NoshadowPanel } from "./noshadow-panel"
import { saveProxiesLines } from "./proxies-store"
import { patchNoshadow, readNoshadow, writeNoshadow } from "./noshadow"

const server = String.raw`
import json, os, socket, subprocess, tempfile, sys
from pathlib import Path
from unittest.mock import patch
import main
from modules import config, paths, proxy_pool

body = json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix="noshadow-api-", dir="web/src/features/proxies") as directory:
    with paths.use_root(Path(directory).resolve()), patch.object(proxy_pool, "snapshot", return_value=[]), patch.object(proxy_pool, "prune"), patch.object(socket.socket, "connect", side_effect=AssertionError("external requests forbidden")):
        config.save({"proxies": [], "proxy_enabled": True})
        handler = main.Handler.__new__(main.Handler)
        handler._read_json = lambda: (body, None)
        handler._campaign_running = lambda: False
        replies = []
        handler._json = lambda payload, *args: replies.append(payload)
        handler._api_proxies_put()
        config._drop_cache()
        restarted = subprocess.run([sys.executable, "-c", "import json; from modules import config; print(json.dumps(config.load()))"],
            env={**os.environ, "NIMBUS_DATA_ROOT": str(Path(directory).resolve())}, text=True, capture_output=True, check=True)
        print(json.dumps({"response": replies[0], "reopened": handler._proxies_payload(), "config": json.loads(restarted.stdout)}))
`

afterEach(() => {
  vi.unstubAllGlobals()
  queryClient.clear()
})

it("persists a NoShadow edit through the real API/config round-trip and reopened panel", async () => {
  const original = "http://fixture-country-US-session-ab12-time-15:synthetic%40%3A%2F%23%2540%27quote@proxy.noshadow.pro:6969"
  const edited = patchNoshadow(readNoshadow(original)!, { country: "GB", minutes: 45, transport: "socks" })
  const lines = [writeNoshadow(edited), "http://other.invalid:8080"]
  const marks = { login: [0], publish: [1], registration: [0], off: [1] }
  let persisted: { response: ProxiesResponse; reopened: ProxiesResponse; config: Record<string, unknown> }
  const fetch = vi.fn(async (path: string, init: RequestInit) => {
    expect(path).toBe("api/proxies")
    if (init.method === "GET") return new Response(JSON.stringify(persisted.reopened))
    expect(init.method).toBe("PUT")
    const process = spawnSync(globalThis.process.env.PYTHON || (globalThis.process.platform === "win32" ? "python" : "python3"), ["-c", server], {
      cwd: new URL("../../../../", import.meta.url),
      env: { ...globalThis.process.env, PYTHONDONTWRITEBYTECODE: "1", NIMBUS_DATA_ROOT: "" },
      input: String(init.body), encoding: "utf8",
    })
    expect(process.status, process.stderr).toBe(0)
    persisted = JSON.parse(process.stdout)
    return new Response(JSON.stringify(persisted.response))
  })
  vi.stubGlobal("fetch", fetch)

  const result = await saveProxiesLines(lines, marks)
  expect(result?.errors).toEqual([])
  expect(readNoshadow(result!.proxies[0])).toEqual(edited)
  expect(queryClient.getQueryData(keys.proxies)).toEqual(result)
  queryClient.clear()
  const reopened = await api.get<ProxiesResponse>("api/proxies")
  expect(reopened.proxies).toEqual(result!.proxies)
  for (const [field, indexes] of Object.entries(marks)) {
    expect(persisted!.config[`proxies_${field}`]).toEqual(indexes.map((index) => reopened.proxies[index]))
  }
  const html = renderToStaticMarkup(createElement(NoshadowPanel, {
    proxies: reopened.proxies, marks, editing: [0], onClose: vi.fn(),
  }))
  expect(html).toMatch(/id="ns-minutes"[^>]*value="45"/)
  expect(readNoshadow(reopened.proxies[0])?.session).toBe("ab12")
  expect(fetch).toHaveBeenCalledTimes(2)
})
