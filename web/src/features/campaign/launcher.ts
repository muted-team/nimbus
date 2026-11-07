import { useCallback } from "react"
import { create } from "zustand"
import { useLocation } from "wouter"

import { useAccounts } from "@/api/accounts"
import { isCampaignLive, startCampaign, stopCampaign, useCampaignStatus } from "@/api/campaign"
import { keys, queryClient } from "@/api/query-client"
import { sectionPath } from "@/app/sections"
import { confirm } from "@/components/confirm"
import { notify } from "@/lib/notify"

import { ensureFormValues, useFormStore } from "./form-store"
import { checkForm, firstErrorText, toStartBody, type FormValues } from "./form-model"
import { launchSummary } from "./launch-summary"
import { CONFIRM_LABEL, LAUNCH_LABEL, TOAST } from "./labels"
import { findShortage } from "./shortage"
import { fetchSlotFiles } from "./slot-files"

/* Запуск публикации — общий для экрана публикации и кнопок «Опубликовать» в
   аккаунтах: проверить сохранённую форму, спросить подтверждение, запустить.
   Кнопка в сводке публикации спрашивает без окна: сводка с теми же строками
   стоит рядом с ней, это и есть подтверждение. */

export interface LaunchOptions {
  /** false — без окна подтверждения (запуск из сводки) */
  confirm?: boolean
}

export interface CampaignLauncher {
  /** accounts — только эти аккаунты; без него — все. true — запущено */
  launch: (accounts?: string[], options?: LaunchOptions) => Promise<boolean>
  stop: () => Promise<void>
  /** идёт запрос запуска или остановки */
  busy: boolean
  /** публикация активна: идёт, останавливается или ждёт круг */
  live: boolean
}

/* Один замок на все кнопки запуска: состояние React обновляется позже клика,
   а проверка формы и окно подтверждения уже могут ждать ответа. */
const useLauncherState = create(() => ({ busy: false }))

export function useCampaignLauncher(): CampaignLauncher {
  const busy = useLauncherState((s) => s.busy)
  const [, navigate] = useLocation()
  const { data: st } = useCampaignStatus()
  const { data: accountsData } = useAccounts()
  const live = isCampaignLive(st)

  const launch = useCallback(
    async (accounts?: string[], { confirm: ask = true }: LaunchOptions = {}) => {
      if (useLauncherState.getState().busy) return false
      if (isCampaignLive(queryClient.getQueryData(keys.campaignStatus))) {
        notify.info(TOAST.running)
        return false
      }
      useLauncherState.setState({ busy: true })
      try {
        let values: FormValues
        try {
          values = await ensureFormValues()
        } catch (error) {
          notify.error(error, TOAST.notLoaded)
          return false
        }
        const { errors, parsed } = checkForm(values)
        if (!parsed) {
          useFormStore.setState({ showErrors: true, pendingFocus: true })
          notify.warn(firstErrorText(errors, values.media) ?? TOAST.notStarted)
          // Контент — в «Креативах», параметры — в «Публикации».
          navigate(sectionPath(errors.folders ? "media" : "camp"))
          return false
        }
        const total = accounts?.length ?? accountsData?.accounts.length
        // Форма могла прийти этим же кликом — числа нужны для её текущих папок.
        const slotInfo = await fetchSlotFiles(values)
        const short = findShortage(values, slotInfo, total)
        const { title, details } = launchSummary(values, parsed, { accounts, total }, short)
        const ok = !ask || (await confirm({
          title,
          description: accounts ? CONFIRM_LABEL.descSelected : CONFIRM_LABEL.descAll,
          details,
          confirmText: LAUNCH_LABEL.start,
          focus: "cancel",
        }))
        if (!ok) return false
        // Пока подтверждали, прогон мог запуститься в другом окне.
        if (isCampaignLive(queryClient.getQueryData(keys.campaignStatus))) {
          notify.info(TOAST.running)
          return false
        }
        await startCampaign(toStartBody(values, parsed, accounts))
        notify.ok(TOAST.started)
        return true
      } catch (error) {
        notify.error(error, TOAST.notStarted)
        return false
      } finally {
        useLauncherState.setState({ busy: false })
      }
    },
    [accountsData, navigate]
  )

  const stop = useCallback(async () => {
    if (useLauncherState.getState().busy) return
    useLauncherState.setState({ busy: true })
    try {
      await stopCampaign()
      notify.info(TOAST.stopping)
    } catch (error) {
      notify.error(error, TOAST.notStopped)
    } finally {
      useLauncherState.setState({ busy: false })
    }
  }, [])

  return { launch, stop, busy, live }
}
