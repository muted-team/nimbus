import { execFile } from "node:child_process"
import { existsSync } from "node:fs"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"
import { promisify } from "node:util"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import react from "@vitejs/plugin-react"
import { createServer } from "vite"
import { expect, it } from "vitest"
import { ClientUpdates } from "./client-updates"

function browserCandidates(platform: string, env: NodeJS.ProcessEnv) {
  if (env.CHROME_BIN) return [env.CHROME_BIN]
  const windows = platform === "win32"
  const join = windows ? path.win32.join : path.posix.join
  const names = windows
    ? ["chrome.exe", "msedge.exe", "chromium.exe"]
    : [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
      ]
  const candidates = (env.PATH || env.Path || "")
    .split(windows ? ";" : ":")
    .filter(Boolean)
    .flatMap((directory) => names.map((name) => join(directory, name)))
  if (windows) {
    return [
      ...candidates,
      ...[env.ProgramFiles, env["ProgramFiles(x86)"], env.LOCALAPPDATA]
        .filter((directory): directory is string => Boolean(directory))
        .flatMap((directory) => [
          join(directory, "Google/Chrome/Application/chrome.exe"),
          join(directory, "Microsoft/Edge/Application/msedge.exe"),
        ]),
    ]
  }
  if (platform === "darwin") {
    return [
      ...candidates,
      ...["/Applications", join(env.HOME || "/", "Applications")].flatMap(
        (directory) => [
          join(directory, "Google Chrome.app/Contents/MacOS/Google Chrome"),
          join(directory, "Chromium.app/Contents/MacOS/Chromium"),
          join(directory, "Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]
      ),
    ]
  }
  return [...candidates, ...names.map((name) => join("/usr/bin", name))]
}

const chromium = browserCandidates(process.platform, process.env).find(
  existsSync
)
const noBrowser =
  "No installed Chromium/Chrome/Edge found on " +
  process.platform +
  "; set CHROME_BIN to an existing engine. Nothing is downloaded."

it("discovers installed Chromium-family browsers across OS layouts without downloading", () => {
  expect(browserCandidates("linux", { PATH: "/fixture/bin" })).toContain(
    "/fixture/bin/chromium"
  )
  expect(browserCandidates("darwin", {})).toContain(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  )
  expect(
    browserCandidates("win32", { ProgramFiles: "C:\\Program Files" })
  ).toContain("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe")
  expect(
    browserCandidates("win32", {
      "ProgramFiles(x86)": "C:\\Program Files (x86)",
    })
  ).toContain(
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
  )
  expect(
    browserCandidates("darwin", { CHROME_BIN: "/fixture/Chromium" })
  ).toEqual(["/fixture/Chromium"])
})

async function renderClicks(script: string) {
  const root = path.resolve(import.meta.dirname, "../..")
  const temporary = await mkdtemp(
    path.join(
      existsSync("/tmp/opencode") ? "/tmp/opencode" : tmpdir(),
      "nimbus-updater-browser-"
    )
  )
  const server = await createServer({
    configFile: false,
    appType: "custom",
    root,
    cacheDir: path.join(temporary, "vite"),
    plugins: [react()],
    resolve: { alias: { "@": path.join(root, "src") } },
    server: { host: "127.0.0.1", port: 0 },
    optimizeDeps: {
      include: ["react", "react-dom/client", "@tanstack/react-query"],
    },
  })
  server.middlewares.use(async (request, response, next) => {
    if (request.url !== "/__updates.html") return next()
    response.setHeader("Content-Type", "text/html")
    response.setHeader(
      "Content-Security-Policy",
      "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'"
    )
    response.end(
      await server.transformIndexHtml(
        request.url,
        `
      <html><body><div id="root"></div><script>
        window.addEventListener("error", event => document.body.dataset.testResult = btoa(JSON.stringify({ fixtureError: event.message })));
      </script><script type="module">
        import { createElement } from "react";
        import { createRoot } from "react-dom/client";
        import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
        import { ClientUpdates } from "/src/components/client-updates.tsx";
        const pending = {};
        const calls = { check: 0, prepare: 0, restart: 0 };
        window.pywebview = { api: {
          check_client_update: () => new Promise(resolve => { calls.check++; pending.check = resolve; }),
          prepare_client_update: () => new Promise(resolve => { calls.prepare++; pending.prepare = resolve; }),
          restart_client_update: () => new Promise(resolve => { calls.restart++; pending.restart = resolve; }),
        } };
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        client.setQueryData(["changelog"], { version: "1.0.4" });
        createRoot(document.getElementById("root")).render(
          createElement(QueryClientProvider, { client }, createElement(ClientUpdates))
        );
        const wait = async predicate => {
          for (let tries = 0; tries < 300; tries++) {
            if (predicate()) return;
            await new Promise(resolve => setTimeout(resolve, 10));
          }
          throw new Error("Synthetic updater DOM did not reach the expected state");
        };
        // App-owned action attributes survive translation and distinguish the three updater controls.
        const button = action => {
          const matches = document.querySelectorAll('#root button[data-action="' + action + '"]');
          if (matches.length !== 1) {
            const candidates = Array.from(document.querySelectorAll('#root button')).map(item => ({
              slot: item.dataset.slot, action: item.dataset.action ?? null, type: item.type,
              visible: item.getClientRects().length > 0, disabled: item.disabled,
            }));
            throw new Error('Expected one updater ' + action + ' control; matches=' + matches.length + '; candidates=' + JSON.stringify(candidates));
          }
          const control = matches[0];
          if (!control.getClientRects().length) throw new Error('Updater ' + action + ' control is not visible');
          return control;
        };
        const snapshot = () => ({
          alerts: Array.from(document.querySelectorAll('[role="alert"]')).map(item => item.textContent),
          statuses: Array.from(document.querySelectorAll('[role="status"]')).map(item => item.textContent),
          destructive: document.querySelector('[role="alert"]')?.classList.contains("text-destructive") ?? false,
          body: document.getElementById("root").textContent,
          calls: { ...calls },
        });
        try {
          await wait(() => document.querySelector('#root button'));
          ${script}
          document.body.dataset.testResult = btoa(unescape(encodeURIComponent(JSON.stringify(result))));
        } catch (error) {
          document.body.dataset.testResult = btoa(JSON.stringify({ fixtureError: error.message }));
        }
      </script></body></html>
    `
      )
    )
  })
  try {
    await server.listen()
    const url = server.resolvedUrls!.local[0] + "__updates.html"
    const { stdout, stderr } = await promisify(execFile)(
      chromium!,
      [
        "--headless",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--no-proxy-server",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--user-data-dir=" + path.join(temporary, "profile"),
        "--dump-dom",
        "--virtual-time-budget=10000",
        url,
      ],
      { timeout: 30000, maxBuffer: 2 * 1024 * 1024 }
    )
    const encoded = stdout.match(/data-test-result="([^"]+)"/)?.[1]
    expect(
      encoded,
      "Headless browser did not finish the synthetic updater clicks: " +
        stdout
          .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "")
          .slice(0, 1000) +
        stderr.slice(-500)
    ).toBeDefined()
    const result = JSON.parse(Buffer.from(encoded!, "base64").toString("utf8"))
    expect(result.fixtureError).toBeUndefined()
    return result
  } finally {
    await server.close()
    await rm(temporary, { recursive: true, force: true })
  }
}

it("browser mode points only at public client Releases without promising installation", () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const html = renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement(ClientUpdates))
  )
  expect(html).toContain("Обновления Nimbus")
  expect(html).toContain("GitHub Releases")
  expect(html).toContain("настольном приложении")
  expect(html).not.toContain("Перезапустить и обновить")
  expect(html).not.toContain("Скачать обновление")
  expect(html).not.toContain("Проверить обновления")
  client.clear()
})

it("headless browser blocks non-fixture hostnames", async ({ skip }) => {
  if (!chromium) skip(noBrowser)
  const result = await renderClicks(`
    const result = { blocked: false };
    try { await fetch(location.href.replace("127.0.0.1", "localhost"), { mode: "no-cors" }); }
    catch { result.blocked = true; }
  `)
  expect(result.blocked).toBe(true)
}, 45000)

it("fixture only permits same-origin browser requests", async ({ skip }) => {
  if (!chromium) skip(noBrowser)
  const result = await renderClicks(`
    const result = { blocked: false };
    try { await fetch("data:,synthetic-outside-fixture"); }
    catch { result.blocked = true; }
  `)
  expect(result.blocked).toBe(true)
}, 45000)

it("native check presents one accessible error through retry recovery", async ({
  skip,
}) => {
  if (!chromium) skip(noBrowser)
  const result = await renderClicks(`
    button("check").click();
    await wait(() => pending.check);
    const checking = snapshot();
    pending.check({ error: "Не удалось проверить обновления. Ошибка проверки сертификата TLS GitHub." });
    await wait(() => document.querySelector('[role="alert"]'));
    const failed = snapshot();
    const canRetry = !button("check").disabled;
    delete pending.check;
    button("check").click();
    await wait(() => pending.check);
    const retrying = snapshot();
    pending.check({ current_version: "1.0.4", latest_version: "1.0.4", available: false,
      supported: true, state: "idle", release_url: "https://github.com/muted-team/nimbus/releases" });
    await wait(() => !button("check").disabled);
    const result = { checking, failed, canRetry, retrying, recovered: snapshot() };
  `)
  expect(result.checking.statuses).toContain("Проверяем GitHub…")
  expect(result.failed.alerts).toEqual([
    "Не удалось проверить обновления. Ошибка проверки сертификата TLS GitHub.",
  ])
  expect(result.failed.destructive).toBe(true)
  expect(result.failed.statuses).toEqual([])
  expect(result.failed.body).not.toContain(
    "Не удалось выполнить обновление. Попробуйте позже."
  )
  expect(result.canRetry).toBe(true)
  expect(result.retrying.alerts).toEqual([])
  expect(result.retrying.statuses).toContain("Проверяем GitHub…")
  expect(result.recovered.alerts).toEqual([])
  expect(result.recovered.statuses).toEqual(["Установлена последняя версия"])
  expect(result.recovered.calls.check).toBe(2)
}, 45000)

it("download failure keeps retry usable and recovers to a verified ready status", async ({
  skip,
}) => {
  if (!chromium) skip(noBrowser)
  const result = await renderClicks(`
    const available = { current_version: "1.0.4", latest_version: "1.0.5", available: true,
      supported: true, state: "idle", release_url: "https://github.com/muted-team/nimbus/releases" };
    button("check").click();
    await wait(() => pending.check);
    pending.check(available);
    await wait(() => document.querySelector('#root button[data-action="prepare"]'));
    const release = snapshot();
    button("prepare").click();
    await wait(() => pending.prepare);
    const downloading = snapshot();
    pending.prepare({ error: "Не удалось подготовить обновление. Превышен лимит запросов GitHub (HTTP 403)." });
    await wait(() => document.querySelector('[role="alert"]'));
    const failed = snapshot();
    const canRetry = !button("prepare").disabled;
    delete pending.prepare;
    button("prepare").click();
    await wait(() => pending.prepare);
    const retrying = snapshot();
    pending.prepare({ ...available, state: "ready", can_restart: true });
    await wait(() => document.querySelector('#root button[data-action="restart"]'));
    const restart = button("restart");
    const result = { release, downloading, failed, canRetry, retrying, ready: snapshot(),
      checkDisabled: button("check").disabled, restartEnabled: !restart.disabled };
  `)
  expect(result.release.statuses).toEqual(["Доступна версия 1.0.5"])
  expect(result.downloading.statuses).toContain("Загружаем и проверяем…")
  expect(result.failed.alerts).toEqual([
    "Не удалось подготовить обновление. Превышен лимит запросов GitHub (HTTP 403).",
  ])
  expect(result.failed.statuses).toEqual([])
  expect(result.canRetry).toBe(true)
  expect(result.retrying.alerts).toEqual([])
  expect(result.ready.alerts).toEqual([])
  expect(result.ready.statuses).toEqual([
    "Обновление проверено и готово. Сохраните правки перед перезапуском; ваши данные останутся на месте.",
  ])
  expect(result.checkDisabled).toBe(true)
  expect(result.restartEnabled).toBe(true)
  expect(result.ready.calls.prepare).toBe(2)
}, 45000)
