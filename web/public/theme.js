/* Runs before the stylesheet so the first frame uses the chosen appearance. */
;(() => {
  const media = window.matchMedia("(prefers-color-scheme: dark)")
  const root = document.documentElement
  const listeners = new Set()
  const valid = (value) => ["system", "light", "dark"].includes(value)
  let mode = "system"
  try {
    const saved = window.localStorage.getItem("ttwa.theme")
    if (valid(saved)) mode = saved
  } catch {
    /* Private browsers may block storage; the current choice still works. */
  }
  let snapshot
  const apply = () => {
    const resolved =
      mode === "system" ? (media.matches ? "dark" : "light") : mode
    if (snapshot?.mode === mode && snapshot.resolved === resolved) return
    snapshot = { mode, resolved }
    root.classList.toggle("dark", resolved === "dark")
    root.style.colorScheme = resolved
    document
      .querySelector('meta[name="color-scheme"]')
      ?.setAttribute("content", resolved)
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", resolved === "dark" ? "#0a0a0a" : "#fafafa")
    listeners.forEach((listener) => listener())
  }
  apply()
  media.addEventListener("change", apply)
  window.addEventListener("storage", (event) => {
    if (event.key !== "ttwa.theme" && event.key !== null) return
    mode = valid(event.newValue) ? event.newValue : "system"
    apply()
  })
  window.__ttwaTheme = {
    getSnapshot: () => snapshot,
    setMode: (next) => {
      if (!valid(next)) return
      mode = next
      try {
        window.localStorage.setItem("ttwa.theme", mode)
      } catch {
        /* Keep the in-memory choice. */
      }
      apply()
    },
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
})()
