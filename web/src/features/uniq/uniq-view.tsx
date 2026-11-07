import { t, useLanguage } from "@/lib/i18n"
import { useEffect, useMemo, useState } from "react"

import { useCampaignForm } from "@/api/campaign"
import { saveUniq, useUniq } from "@/api/misc"
import { UNIQ_KEYS, type MediaKind, type UniqKey, type UniqParam, type UniqSettings } from "@/api/types"
import { ErrorView, LoadingRows } from "@/components/state-view"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useAutosave } from "@/hooks/use-autosave"
import { notify } from "@/lib/notify"

import { TOAST, UNIQ_TITLE } from "./labels"
import { applyPatch, pickParams, type ParamPatch } from "./param-model"
import { ParamsPanel } from "./params-panel"
import { PreviewPanel } from "./preview-panel"

/* Уникализация — вкладка «Креативов»: обработка — свойство креативов, а не
   отдельный раздел. Слева параметры с вилками и замками, справа превью
   обработанного фото из папок публикации. Настройки автосохраняются.
   В режиме видео превью нет — ролик уходит в TikTok как есть, — но сами
   параметры остаются: они общие и понадобятся, когда вернётся фото. */

export function UniqView() {
  const uniq = useUniq()
  const form = useCampaignForm()

  if (uniq.data === undefined) {
    return uniq.isError ? <ErrorView error={uniq.error} onRetry={() => void uniq.refetch()} /> : <LoadingRows rows={8} />
  }

  return (
    <UniqScreen
      settings={uniq.data}
      media={form.data?.media === "video" ? "video" : "photo"}
      folders={form.data?.slots ?? []}
      foldersReady={form.data !== undefined || form.isError}
    />
  )
}

function UniqScreen({
  settings,
  media,
  folders,
  foldersReady,
}: {
  settings: UniqSettings
  media: MediaKind
  folders: string[]
  foldersReady: boolean
}) {
  useLanguage()
  const [master, setMaster] = useState(settings.enabled)
  const [params, setParams] = useState<Record<UniqKey, UniqParam>>(() => pickParams(settings))

  const patchParam = (key: UniqKey, patch: ParamPatch) => {
    setParams((prev) => ({ ...prev, [key]: applyPatch(prev[key], patch) }))
  }

  // правки параметров уходят сами; мастер — сразу, отдельным запросом
  const { markSaved } = useAutosave(params, saveUniq, {
    delay: 600,
    onError: (error) => notify.error(error, TOAST.notSaved),
  })
  const [fromServer] = useState(params)
  useEffect(() => {
    markSaved(fromServer)
  }, [markSaved, fromServer])

  const toggleMaster = (enabled: boolean) => {
    setMaster(enabled)
    saveUniq({ enabled }).catch((error) => {
      notify.error(error, TOAST.notSaved)
      // не записалось — возвращаем тумблер, если пользователь не трогал его снова
      setMaster((cur) => (cur === enabled ? !enabled : cur))
    })
  }

  const fullSettings = useMemo<UniqSettings>(
    () => ({ enabled: master, limits: settings.limits, ...params }),
    [master, settings.limits, params],
  )

  const enabledCount = UNIQ_KEYS.filter((k) => params[k].enabled).length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Switch id="uniq-master" checked={master} onCheckedChange={toggleMaster} />
        <Label htmlFor="uniq-master">{t(UNIQ_TITLE)}</Label>
        {master ? (
          <span className="text-sm text-muted-foreground tabular">
            {enabledCount}{t("из")}{UNIQ_KEYS.length}
          </span>
        ) : null}
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        <ParamsPanel master={master} params={params} limits={settings.limits} onPatch={patchParam} />
        <PreviewPanel settings={fullSettings} media={media} folders={folders} foldersReady={foldersReady} />
      </div>
    </div>
  )
}
