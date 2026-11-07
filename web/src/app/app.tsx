import { useLanguage } from "@/lib/i18n"
import { QueryClientProvider } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { Router, useLocation } from "wouter"
import { useHashLocation } from "wouter/use-hash-location"

import { onAuthRequired } from "@/api/client"
import { getAuth } from "@/api/misc"
import { queryClient } from "@/api/query-client"
import { useLiveStream } from "@/api/stream"
import { ConfirmHost } from "@/components/confirm"
import { ErrorBoundary } from "@/components/error-boundary"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useHotkey } from "@/hooks/use-hotkey"
import { useMediaQuery } from "@/hooks/use-media-query"

import { AppSidebar } from "./app-sidebar"
import { CommandPalette } from "./command-palette"
import { LoginScreen } from "./login-screen"
import { MobileNav } from "./mobile-nav"
import { useDocumentTitle } from "./nav-status"
import { usePrefs } from "./prefs"
import { AppRoutes } from "./routes"
import { SECTIONS } from "./sections"

type Gate = "checking" | "locked" | "open"

/* Сервер на замке спрашивает пароль. Проверяем до первой отрисовки, чтобы не
   мигать экраном с нулями; позже любой ответ 401 тоже поднимет экран входа. */
function useAuthGate(): Gate {
  const [gate, setGate] = useState<Gate>("checking")
  useEffect(() => {
    getAuth().then(
      (st) => setGate(st.required && !st.ok ? "locked" : "open"),
      () => setGate("open")
    )
    return onAuthRequired(() => setGate("locked"))
  }, [])
  return gate
}

function Shell() {
  useLanguage()
  const [location, navigate] = useLocation()
  const { sidebarOpen, setSidebarOpen, setLastPath } = usePrefs()
  // окно уже 1024 — меню свёрнуто до иконок, если его не раскрыли руками
  const wide = useMediaQuery("(min-width: 1024px)")
  const [narrowOpen, setNarrowOpen] = useState(false)

  useLiveStream(true)
  useDocumentTitle()

  useEffect(() => {
    setLastPath(location)
    window.scrollTo({ top: 0 })
  }, [location, setLastPath])

  // в полях ввода не ловим: Alt с цифрой на цифровой клавиатуре — это ещё и
  // ввод символа по коду, и раздел менялся бы прямо посреди набора текста.
  // Клавиши — у рабочих разделов по порядку меню; служебные (в меню
  // профиля) — без клавиши
  const working = SECTIONS.filter((s) => !s.secondary)
  useHotkey(
    working.map((_, i) => `Alt+${i + 1}`),
    (e) => {
      const n = Number(e.code.slice(-1))
      const target = working[n - 1]
      if (target) navigate(target.path)
    },
    { inInputs: false }
  )

  return (
    <SidebarProvider
      open={wide ? sidebarOpen : narrowOpen}
      onOpenChange={wide ? setSidebarOpen : setNarrowOpen}
      className="[--mobile-nav-h:3.5rem]"
    >
      {/* каждый кусок каркаса падает сам по себе: сбой в меню не гасит экран,
          сбой экрана — меню; экран оживает при переходе в другой раздел */}
      <ErrorBoundary fallback={null}>
        <AppSidebar />
      </ErrorBoundary>
      <SidebarInset className="min-w-0 pb-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom))] md:pb-0">
        <ErrorBoundary key={location}>
          <AppRoutes />
        </ErrorBoundary>
      </SidebarInset>
      <ErrorBoundary fallback={null}>
        <MobileNav />
        <CommandPalette />
      </ErrorBoundary>
    </SidebarProvider>
  )
}

export function App() {
  useLanguage()
  const gate = useAuthGate()
  const mobile = useMediaQuery("(max-width: 767px)")

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delay={400}>
        {gate === "open" ? (
          <Router hook={useHashLocation}>
            <Shell />
          </Router>
        ) : gate === "locked" ? (
          <LoginScreen />
        ) : null}
        <ConfirmHost />
        <Toaster
          position={mobile ? "top-center" : "bottom-right"}
          visibleToasts={mobile ? 2 : 4}
          offset={mobile ? { top: "calc(env(safe-area-inset-top) + 12px)" } : 16}
        />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
