import { NumberInput, RangeInput } from "@/components/number-input"
import { Panel } from "@/components/panel"
import { Field, FieldContent, FieldError, FieldGroup, FieldLabel as Label } from "@/components/ui/field"
import { t, useLanguage } from "@/lib/i18n"

import { AfterFields } from "./after-fields"
import { checkForm } from "./form-model"
import { updateForm, useFormStore } from "./form-store"
import { FORM_LABEL } from "./labels"

export function ParamsPanel() {
  useLanguage()
  const values = useFormStore((s) => s.values)!
  const showErrors = useFormStore((s) => s.showErrors)
  const { errors } = checkForm(values)

  return (
    <Panel title={FORM_LABEL.params}>
      <FieldGroup className="gap-4">
        <Field orientation="responsive" className="min-w-0 @md/field-group:grid @md/field-group:grid-cols-[12rem_minmax(0,1fr)] @md/field-group:gap-x-4" data-invalid={showErrors && !!errors.posts}>
          <Label htmlFor="camp-posts">{FORM_LABEL.posts}</Label>
          <FieldContent className="min-w-0 gap-2">
            <NumberInput
              id="camp-posts"
              value={values.posts}
              onValueChange={(posts) => updateForm({ posts })}
              className="@md/field-group:max-w-24"
              data-field="posts"
              aria-invalid={showErrors && errors.posts ? true : undefined}
              aria-describedby={showErrors && errors.posts ? "camp-posts-error" : undefined}
            />
            {showErrors && errors.posts ? <FieldError id="camp-posts-error" className="text-xs">{errors.posts}</FieldError> : null}
          </FieldContent>
        </Field>
        <Field orientation="responsive" className="min-w-0 @md/field-group:grid @md/field-group:grid-cols-[12rem_minmax(0,1fr)] @md/field-group:gap-x-4" data-invalid={showErrors && !!errors.delay}>
          <Label>{FORM_LABEL.delay}</Label>
          <FieldContent className="min-w-0 gap-2">
            <RangeInput
              label={t("Пауза")}
              min={values.delayMin}
              max={values.delayMax}
              onMinChange={(delayMin) => updateForm({ delayMin })}
              onMaxChange={(delayMax) => updateForm({ delayMax })}
              className="@md/field-group:max-w-64"
              decimal
              field="delay"
              invalid={showErrors && !!errors.delay}
              aria-describedby={showErrors && errors.delay ? "camp-delay-error" : undefined}
            />
            {showErrors && errors.delay ? <FieldError id="camp-delay-error" className="text-xs">{errors.delay}</FieldError> : null}
          </FieldContent>
        </Field>
        <AfterFields />
      </FieldGroup>
    </Panel>
  )
}
