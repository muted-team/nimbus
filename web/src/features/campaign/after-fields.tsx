import { NumberInput, RangeInput } from "@/components/number-input"
import { SimpleSelect } from "@/components/simple-select"
import { Field, FieldContent, FieldError, FieldGroup, FieldLabel as Label } from "@/components/ui/field"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useLanguage } from "@/lib/i18n"

import { checkForm } from "./form-model"
import { updateForm, useFormStore } from "./form-store"
import { CLEANUP_MODE_LABEL, FORM_LABEL, KEEP_LABEL, REPEAT_UNIT_ITEMS, type CleanupMode } from "./labels"

const rowLayout = "min-w-0 @md/field-group:grid @md/field-group:grid-cols-[12rem_minmax(0,1fr)] @md/field-group:gap-x-4"

export function AfterFields() {
  useLanguage()
  const values = useFormStore((s) => s.values)!
  const showErrors = useFormStore((s) => s.showErrors)
  const { errors } = checkForm(values)

  return (
    <>
      <Field orientation="responsive" className={rowLayout}>
        <Label>{FORM_LABEL.keep[values.media]}</Label>
        <FieldContent className="min-w-0">
          <ToggleGroup
            value={[values.keep ? "keep" : "delete"]}
            onValueChange={(group) => {
              const next = group[0]
              if (next) updateForm({ keep: next === "keep" })
            }}
            aria-label={FORM_LABEL.keep[values.media]}
          >
            <ToggleGroupItem value="delete">{KEEP_LABEL.delete}</ToggleGroupItem>
            <ToggleGroupItem value="keep">{KEEP_LABEL.keep}</ToggleGroupItem>
          </ToggleGroup>
        </FieldContent>
      </Field>

      <Field orientation="responsive" className={rowLayout} data-invalid={showErrors && !!errors.cleanupCount}>
        <Label htmlFor="camp-cleanup">{FORM_LABEL.cleanup}</Label>
        <FieldContent className="min-w-0 gap-3">
          <div className="flex min-h-8 items-center pointer-coarse:min-h-10">
            <Switch id="camp-cleanup" checked={values.cleanup} onCheckedChange={(cleanup) => updateForm({ cleanup })} className="pointer-coarse:after:-inset-y-3" />
          </div>
          {values.cleanup ? (
            <FieldGroup className="gap-3">
              <ToggleGroup
                value={[values.cleanupMode]}
                onValueChange={(group) => {
                  const next = group[0]
                  if (next) updateForm({ cleanupMode: next as CleanupMode })
                }}
                aria-label={FORM_LABEL.cleanup}
              >
                {(["same", "all", "count"] as CleanupMode[]).map((mode) => (
                  <ToggleGroupItem key={mode} value={mode}>{CLEANUP_MODE_LABEL[mode]}</ToggleGroupItem>
                ))}
              </ToggleGroup>
              {values.cleanupMode === "count" ? (
                <Field className="min-w-0 max-w-32">
                  <Label htmlFor="camp-cleanup-count">{FORM_LABEL.cleanupCount}</Label>
                  <NumberInput
                    id="camp-cleanup-count"
                    value={values.cleanupCount}
                    onValueChange={(cleanupCount) => updateForm({ cleanupCount })}
                    data-field="cleanupCount"
                    aria-invalid={showErrors && errors.cleanupCount ? true : undefined}
                    aria-describedby={showErrors && errors.cleanupCount ? "camp-cleanup-error" : undefined}
                  />
                </Field>
              ) : null}
            </FieldGroup>
          ) : null}
          {showErrors && errors.cleanupCount ? <FieldError id="camp-cleanup-error" className="text-xs">{errors.cleanupCount}</FieldError> : null}
        </FieldContent>
      </Field>

      <Field orientation="responsive" className={rowLayout} data-invalid={showErrors && !!errors.repeat}>
        <Label htmlFor="camp-repeat">{FORM_LABEL.repeat}</Label>
        <FieldContent className="min-w-0 gap-3">
          <div className="flex min-h-8 items-center pointer-coarse:min-h-10">
            <Switch id="camp-repeat" checked={values.repeat} onCheckedChange={(repeat) => updateForm({ repeat })} className="pointer-coarse:after:-inset-y-3" />
          </div>
          {values.repeat ? (
            <FieldGroup className="min-w-0 gap-3 @md/field-group:flex-row @md/field-group:items-end">
              <Field className="min-w-0 max-w-64">
                <Label>{FORM_LABEL.repeatEvery}</Label>
                <RangeInput
                  label={FORM_LABEL.repeatEvery}
                  min={values.repeatMin}
                  max={values.repeatMax}
                  onMinChange={(repeatMin) => updateForm({ repeatMin })}
                  onMaxChange={(repeatMax) => updateForm({ repeatMax })}
                  field="repeat"
                  invalid={showErrors && !!errors.repeat}
                  aria-describedby={showErrors && errors.repeat ? "camp-repeat-error" : undefined}
                />
              </Field>
              <Field className="min-w-0 max-w-32">
                <Label>{FORM_LABEL.repeatUnit}</Label>
                <SimpleSelect
                  aria-label={FORM_LABEL.repeatUnit}
                  value={values.repeatUnit}
                  items={REPEAT_UNIT_ITEMS}
                  onValueChange={(repeatUnit) => updateForm({ repeatUnit })}
                  className="w-full"
                />
              </Field>
            </FieldGroup>
          ) : null}
          {showErrors && errors.repeat ? <FieldError id="camp-repeat-error" className="text-xs">{errors.repeat}</FieldError> : null}
        </FieldContent>
      </Field>
    </>
  )
}
