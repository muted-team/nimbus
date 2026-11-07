import { useLanguage } from "@/lib/i18n"
import { useEffect } from "react"
import { SquareIcon } from "lucide-react"

import { useCampaignForm, useCampaignStatus } from "@/api/campaign"
import { sectionTitle } from "@/app/sections"
import { confirmDestructive } from "@/components/confirm"
import { Hint } from "@/components/hint"
import { Page, PageBody, PageHeader } from "@/components/page"
import { Panel } from "@/components/panel"
import { ErrorView, LoadingRows } from "@/components/state-view"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { useHotkey } from "@/hooks/use-hotkey"

import { CampaignProgress } from "./campaign-progress"

import { checkForm } from "./form-model"
import { hydrateForm, useFormAutosave, useFormStore } from "./form-store"
import { CONFIRM_LABEL, FIELD_ORDER, FORM_LABEL, LAUNCH_LABEL, SUMMARY_LABEL } from "./labels"
import { LaunchPanel } from "./launch-panel"
import { useCampaignLauncher } from "./launcher"
import { ParamsPanel } from "./params-panel"


/* Публикация: параметры и запуск. Контент и обработка — в «Креативах».
   Показываем только активный прогон, без отчётов прошлых запусков.
   Ctrl+Enter запускает, а во время публикации останавливает. */

export default function CampaignPage() {
  useLanguage()
  const form = useCampaignForm()
  const { data: st } = useCampaignStatus()
  const values = useFormStore((s) => s.values)
  const pendingFocus = useFormStore((s) => s.pendingFocus)
  const { launch, stop, busy, live } = useCampaignLauncher()

  useEffect(() => {
    if (form.data) hydrateForm(form.data)
  }, [form.data])

  useFormAutosave()

  useEffect(() => {
    if (!pendingFocus || !values) return
    const { errors } = checkForm(values)
    const field = FIELD_ORDER.find((f) => errors[f])
    if (field) document.querySelector<HTMLElement>(`[data-field="${field}"]`)?.focus()
    useFormStore.setState({ pendingFocus: false })
  }, [pendingFocus, values])

  /* Ctrl+Enter запускает (с окном подтверждения: сочетание легко нажать
     вслепую в поле описания), а идущую публикацию останавливает тоже только
     с подтверждением: остановка посреди круга дороже лишнего вопроса. */
  const hotkeyLaunch = async () => {
    if (!live) {
      await launch()
      return
    }
    const ok = await confirmDestructive({
      title: CONFIRM_LABEL.stop,
      description: CONFIRM_LABEL.stopDesc,
      confirmText: LAUNCH_LABEL.stop,
    })
    if (ok) await stop()
  }
  useHotkey("Mod+Enter", () => void hotkeyLaunch())

  const hasRun = live && !st?.restored

  return (
    <Page>
      <PageHeader
        title={sectionTitle("camp")}
        actions={
          live ? (
            <Hint label={LAUNCH_LABEL.stop} hotkey="Mod+Enter">
              <Button variant="destructive" onClick={() => void stop()} disabled={busy}>
                {busy ? <Spinner /> : <SquareIcon />}
                {busy ? LAUNCH_LABEL.stopping : LAUNCH_LABEL.stop}
              </Button>
            </Hint>
          ) : null
        }
      />
      <PageBody width="full" className="max-w-[1440px]">

        {hasRun ? (
          <Panel title={LAUNCH_LABEL.progress}>
            <CampaignProgress />
          </Panel>
        ) : null}


        {live ? <p className="pt-2 text-sm text-muted-foreground">{SUMMARY_LABEL.nextRun}</p> : null}
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="flex min-w-0 flex-col gap-4">
            {values ? (
              <>
                <ParamsPanel />
              </>
            ) : (
              <Panel title={FORM_LABEL.params}>
                {form.isError ? <ErrorView error={form.error} onRetry={() => void form.refetch()} /> : <LoadingRows />}
              </Panel>
            )}
          </div>
          <div className="lg:sticky lg:top-20">
            <LaunchPanel />
          </div>
        </div>
      </PageBody>
    </Page>
  )
}
