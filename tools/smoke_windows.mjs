/** Check the packaged Windows application in a temporary, account-free copy. */
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { once } from "node:events"
import { cp, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises"
import net from "node:net"
import path from "node:path"
import os from "node:os"

assert.equal(process.platform, "win32", "Run this check on Windows")
const source = path.resolve(process.argv[2])
const output = path.resolve(process.argv[3] || "smoke-results")
const temporary = await mkdtemp(path.join(os.tmpdir(), "nimbus-package-check-"))
const application = path.join(temporary, "Nimbus v1.0.0")
await cp(source, application, { recursive: true })
const { mkdir } = await import("node:fs/promises")
await mkdir(output, { recursive: true })

async function freePort() {
  const server = net.createServer()
  server.listen(0, "127.0.0.1")
  await once(server, "listening")
  const port = server.address().port
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  return port
}

const apiPort = await freePort()
const debugPort = await freePort()
await writeFile(path.join(application, "config.json"), JSON.stringify({
  license_key: "", browser_profile: "chrome152", proxy_enabled: false,
  phone_access: false, port: apiPort,
}))
const environment = { ...process.env,
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${debugPort}`,
  WEBVIEW2_USER_DATA_FOLDER: path.join(temporary, "webview-profile"),
}
delete environment.NIMBUS_SERVER
const child = spawn(path.join(application, "Nimbus.exe"), [String(apiPort)], {
  cwd: application, env: environment, stdio: "ignore",
})
let socket
const results = []
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
async function waitFor(fn, seconds = 90) {
  const end = Date.now() + seconds * 1000
  while (Date.now() < end) {
    assert.equal(child.exitCode, null, "Packaged application exited")
    try { const value = await fn(); if (value) return value } catch {}
    await pause(250)
  }
  throw new Error("Packaged application did not become ready")
}

try {
  const base = `http://127.0.0.1:${apiPort}`
  const release = await waitFor(async () => {
    const response = await fetch(base + "/api/changelog")
    return response.ok ? response.json() : null
  })
  assert.equal(release.version, "1.0.0")
  const page = await (await fetch(base)).text()
  for (const match of page.matchAll(/(?:src|href)="(?:\.\/)?([^"?#]+\.(?:js|css))"/g)) {
    assert.equal((await fetch(base + "/" + match[1].replace(/^\//, ""))).status, 200)
  }
  const targets = await waitFor(async () => {
    const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`)
    const targets = await response.json()
    return targets.find((target) => target.type === "page" && target.url.startsWith(base))
  })
  socket = new WebSocket(targets.webSocketDebuggerUrl)
  await once(socket, "open")
  let sequence = 0
  const pending = new Map()
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data)
    const promise = pending.get(message.id)
    if (!promise) return
    clearTimeout(promise.timer)
    pending.delete(message.id)
    message.error ? promise.reject(new Error(message.error.message)) : promise.resolve(message.result)
  })
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)) }, 10000)
    pending.set(id, { resolve, reject, timer })
    socket.send(JSON.stringify({ id, method, params }))
  })
  const evaluate = async (expression) => {
    const response = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })
    if (response.exceptionDetails) throw new Error("WebView evaluation failed")
    return response.result.value
  }
  await call("Page.enable")
  await evaluate("window.__packageErrors=[]; addEventListener('error',e=>__packageErrors.push(e.message)); true")
  for (const [route, title] of [["/", "Публикация"], ["/accounts", "Аккаунты"],
    ["/proxies", "Прокси"], ["/media", "Креативы"], ["/logs", "Логи"],
    ["/settings", "Настройки"], ["/profile", "Профиль"]]) {
    await evaluate(`location.hash=${JSON.stringify(route)}; true`)
    await waitFor(() => evaluate(`[...document.querySelectorAll('h1')].some(e=>e.textContent.trim()===${JSON.stringify(title)} && e.getBoundingClientRect().width>0)`), 20)
    const state = await evaluate("({width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth+1,errors:window.__packageErrors})")
    assert.equal(state.overflow, false, `Horizontal overflow: ${route}`)
    assert.deepEqual(state.errors, [], `WebView errors: ${route}`)
    const screenshot = await call("Page.captureScreenshot", { format: "png", captureBeyondViewport: false })
    await writeFile(path.join(output, (route.slice(1) || "publication") + ".png"), Buffer.from(screenshot.data, "base64"))
    results.push({ route, rendered: true, ...state })
  }
  const title = await new Promise((resolve, reject) => {
    const processCheck = spawn("powershell.exe", ["-NoProfile", "-Command", `(Get-Process -Id ${child.pid}).MainWindowTitle`])
    let text = ""
    processCheck.stdout.on("data", (chunk) => text += chunk)
    processCheck.on("error", reject)
    processCheck.on("close", (code) => code === 0 ? resolve(text.trim()) : reject(new Error("Native window check failed")))
  })
  assert.equal(title, "Nimbus", "Native window was not opened")
  await writeFile(path.join(output, "results.json"), JSON.stringify({ nativeWindow: true, release: release.version, routes: results }, null, 2))
  console.log("Windows package: native window and seven rendered routes passed")
} finally {
  socket?.close()
  const stop = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" })
  await once(stop, "exit").catch(() => {})
  await pause(500)
  await rm(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 250 })
}
