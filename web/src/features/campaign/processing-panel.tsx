import { t, useLanguage } from "@/lib/i18n"
import { saveUniq, useUniq } from "@/api/misc"
import { UNIQ_KEYS } from "@/api/types"
import { Panel } from "@/components/panel"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { UNIQ_TITLE } from "@/features/uniq/labels"
import { notify } from "@/lib/notify"

import { useFormStore } from "./form-store"
import { FORM_LABEL, PROCESSING_LABEL } from "./labels"


/* Шаг «Обработка»: уникализация креативов перед постом. Здесь — включить и
   видеть, сколько параметров в деле; сами вилки и превью — во вкладке
   «Уникализация» в «Креативах». Видео уходит как
   есть — об этом строка вместо тумблера. */

export function ProcessingPanel() {
  useLanguage()
  const uniq = useUniq()
  const media = useFormStore((s) => s.values?.media)
  const on = !!uniq.data?.enabled
  const active = uniq.data ? UNIQ_KEYS.filter((k) => uniq.data[k].enabled).length : 0

  const toggle = (enabled: boolean) => {
    saveUniq({ enabled }).catch((error) => notify.error(error, PROCESSING_LABEL.notSaved))
  }

  return (
    <Panel title={FORM_LABEL.processing}>
      {media === "video" ? (
        <p className="text-sm text-muted-foreground">{PROCESSING_LABEL.video}</p>
      ) : (
        <div className="flex items-center gap-2">
          <Switch id="camp-uniq" checked={on} disabled={!uniq.data} onCheckedChange={toggle} />
          <Label htmlFor="camp-uniq">{t(UNIQ_TITLE)}</Label>
          {on ? (
            <span className="text-sm text-muted-foreground tabular">{PROCESSING_LABEL.active(active, UNIQ_KEYS.length)}</span>
          ) : null}
        </div>
      )}
    </Panel>
  )
}
