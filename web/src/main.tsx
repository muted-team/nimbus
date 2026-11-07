import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { App } from "@/app/app"
import { usePrefs } from "@/app/prefs"
import { SECTIONS } from "@/app/sections"

import "./index.css"

// окно программы открывается на корне — возвращаем последний открытый раздел
const { lastPath } = usePrefs.getState()
if (!location.hash && lastPath !== "/" && SECTIONS.some((s) => s.path === lastPath)) {
  history.replaceState(null, "", `#${lastPath}`)
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
