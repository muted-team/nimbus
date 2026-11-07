import { useLanguage } from "@/lib/i18n"
import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from "react"
import { Redirect, Route, Switch } from "wouter"

import { LoadingRows } from "@/components/state-view"

import { MOVED, SECTIONS, type SectionId } from "./sections"

/* Экраны грузятся по требованию: окно открывается быстрее, а тяжёлые экраны
   (уникализатор, аккаунты) не тормозят первый. */
const PAGES: Record<SectionId, LazyExoticComponent<ComponentType>> = {
  camp: lazy(() => import("@/features/campaign/campaign-page")),
  accounts: lazy(() => import("@/features/accounts/accounts-page")),
  proxies: lazy(() => import("@/features/proxies/proxies-page")),
  media: lazy(() => import("@/features/media/media-page")),
  logs: lazy(() => import("@/features/logs/logs-page")),
  settings: lazy(() => import("@/features/settings/settings-page")),
  profile: lazy(() => import("@/features/profile/profile-page")),
}

/* У креативов адрес вложенный: открытая папка и вкладка уникализации живут в
   адресе (/media/f/<папка>, /media/uniq), чтобы «Назад» и Esc вели обратно. */
const NESTED: Partial<Record<SectionId, true>> = { media: true }

export function AppRoutes() {
  useLanguage()
  return (
    <Suspense fallback={<LoadingRows className="px-6 py-6" />}>
      <Switch>
        {Object.entries(MOVED).map(([from, to]) => (
          <Route key={from} path={from}>
            <Redirect to={to} replace />
          </Route>
        ))}
        {SECTIONS.map((s) => {
          const Page = PAGES[s.id]
          return (
            <Route key={s.id} path={NESTED[s.id] ? `${s.path}/*?` : s.path}>
              <Page />
            </Route>
          )
        })}
        <Route>
          <Redirect to="/" replace />
        </Route>
      </Switch>
    </Suspense>
  )
}
