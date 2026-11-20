import type { ReactNode } from 'react'
import { PageTitle } from '../components/States'
import { Shell } from '../components/Shell'
import {
  TEXT_SCALES,
  resetSettings,
  updateSettings,
  useSettings,
  type Settings as SettingsShape,
} from '../lib/settings'

function Choice<T extends string | number | boolean>({
  name,
  legend,
  hint,
  value,
  options,
  onChange,
}: {
  name: string
  legend: string
  hint?: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <fieldset className="panel m-0 mt-4 min-w-0">
      <legend className="px-1 text-lg font-bold">{legend}</legend>
      {hint && <p className="m-0 mb-3 max-w-[62ch] text-sm text-muted">{hint}</p>}
      <div className="flex flex-wrap gap-3">
        {options.map((o) => (
          <label
            key={String(o.value)}
            className={`flex min-h-11 cursor-pointer items-center gap-2.5 rounded-xl border-2 px-4 py-2 font-semibold ${
              o.value === value ? 'border-accent bg-surface2' : 'border-line-strong'
            }`}
          >
            <input
              type="radio"
              name={name}
              checked={o.value === value}
              onChange={() => onChange(o.value)}
              className="size-5 accent-[var(--accent)]"
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function Preview(): ReactNode {
  return (
    <section className="panel mt-4" aria-labelledby="preview">
      <h2 id="preview" className="m-0 mb-2 text-lg font-bold">
        Preview
      </h2>
      <p className="m-0 max-w-[62ch]">
        This is how text looks with your choices. Films you have not seen are ranked by how close
        they sit to the ones you rated highly, and the reasons are listed beside each pick.
      </p>
      <p className="m-0 mt-2 text-sm text-muted">
        Smaller, quieter text such as match percentages and release years looks like this.
      </p>
    </section>
  )
}

/** `/settings` : display and reading preferences, kept in this browser only. */
export function Settings() {
  const s = useSettings()
  const set = <K extends keyof SettingsShape>(key: K) => (v: SettingsShape[K]) =>
    updateSettings({ [key]: v } as Partial<SettingsShape>)

  return (
    <Shell title="Display settings" ads={false}>
      <PageTitle title="Display settings">
        Changes apply straight away and stay on this device. Nothing here is sent anywhere.
      </PageTitle>

      <Choice
        name="theme"
        legend="Colour theme"
        hint="System follows your device's light or dark setting."
        value={s.theme}
        options={[
          { value: 'system', label: 'System' },
          { value: 'light', label: 'Light' },
          { value: 'dark', label: 'Dark' },
        ]}
        onChange={set('theme')}
      />
      <Choice
        name="contrast"
        legend="Contrast"
        hint="High contrast uses plain black and white, stronger borders, no background texture and a heavier focus outline."
        value={s.contrast}
        options={[
          { value: 'system', label: 'System' },
          { value: 'standard', label: 'Standard' },
          { value: 'high', label: 'High' },
        ]}
        onChange={set('contrast')}
      />
      <Choice
        name="text-size"
        legend="Text size"
        hint="Scales everything on the site together."
        value={s.textScale}
        options={TEXT_SCALES.map((n) => ({ value: n, label: `${n}%` }))}
        onChange={set('textScale')}
      />
      <Choice
        name="reading"
        legend="Dyslexia-friendly reading"
        hint="Switches to Atkinson Hyperlegible, a typeface designed for legibility, with extra spacing between letters, words and lines, and no all-capital labels."
        value={s.dyslexia}
        options={[
          { value: false, label: 'Off' },
          { value: true, label: 'On' },
        ]}
        onChange={set('dyslexia')}
      />
      <Choice
        name="motion"
        legend="Motion"
        hint="Reduce stops transitions and animation. System follows your device setting."
        value={s.motion}
        options={[
          { value: 'system', label: 'System' },
          { value: 'reduce', label: 'Reduce' },
        ]}
        onChange={set('motion')}
      />

      <Preview />

      <div className="mt-6">
        <button type="button" className="btn secondary" onClick={resetSettings}>
          Reset to defaults
        </button>
      </div>
    </Shell>
  )
}
