import { useLanguage } from "@/lib/i18n"
import { HistoryIcon } from "lucide-react"

import { useChangelog } from "@/api/misc"
import type { Release } from "@/api/types"
import { QueryView, StateView } from "@/components/state-view"
import { StatusDot } from "@/components/status"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"

import { CHANGES_LABEL } from "./labels"

/* «Что нового» — история изменений окном из меню профиля. Это не рабочий
   раздел: заглядывают раз после обновления, и места в меню навсегда ему не
   нужно. Список прокручивается внутри окна, шапка с версией стоит. */

export function ChangesDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  useLanguage()
  const query = useChangelog()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[min(40rem,calc(100svh-4rem))] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="flex-row items-center gap-2 border-b py-3 pr-14 pl-4 pointer-coarse:min-h-14">
          <DialogTitle>{CHANGES_LABEL.title}</DialogTitle>
          {query.data?.version ? <Badge variant="secondary">v{query.data.version}</Badge> : null}
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <QueryView query={query}>
            {(log) =>
              log.releases.length ? (
                <div className="flex flex-col gap-6">
                  {log.releases.map((release) => (
                    <ReleaseBlock key={release.version} release={release} current={release.version === log.version} />
                  ))}
                </div>
              ) : (
                <StateView icon={HistoryIcon} title={CHANGES_LABEL.empty} />
              )
            }
          </QueryView>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ReleaseBlock({ release, current }: { release: Release; current: boolean }) {
  useLanguage()
  return (
    <section className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        v{release.version}
        {current ? <Badge variant="secondary">{CHANGES_LABEL.current}</Badge> : null}
        <span className="ml-auto text-xs font-normal text-muted-foreground tabular">{release.date}</span>
      </h3>
      <ul className="flex flex-col gap-2 select-text">
        {release.changes.length ? (
          release.changes.map((change, i) => (
            <li key={i} className="flex gap-3">
              <StatusDot tone="neutral" className="mt-2" />
              <span className="text-sm leading-relaxed">{change}</span>
            </li>
          ))
        ) : (
          <li className="text-sm text-muted-foreground">{CHANGES_LABEL.emptyRelease}</li>
        )}
      </ul>
    </section>
  )
}
