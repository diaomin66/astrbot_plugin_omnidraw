import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import Select, { type SelectOption } from './upstream/components/Select'
import { Checkbox } from './upstream/components/Checkbox'
import ConfirmDialog from './upstream/components/ConfirmDialog'
import Toast from './upstream/components/Toast'
import { CollectionManageIcon, CodeIcon, HistoryIcon, LinkIcon, SettingsIcon, SketchIcon, SparklesIcon } from './upstream/components/icons'
import { Button, Switch, SettingsDrawer, SETTINGS_INPUT_CLASS, SETTINGS_BUTTON_CLASSES, SETTINGS_NAV_CLASSES } from './upstream/SettingsPrimitives'
import { useStore } from './upstream/store'
import './upstream/index.css'
import './integration.css'

// React owns only these islands. The original form controls remain the source
// of truth for the plugin's existing configuration bridge and event handlers.
type Island = { host: HTMLElement; root: Root; fingerprint: string }
const islands = new Map<HTMLElement, Island>()
const styledTokens = new WeakMap<HTMLElement, { classes: string; tokens: string[] }>()
const confirmedActions = new WeakSet<HTMLElement>()
const nativeButtonSelector = 'button:not([data-playground-native])'
let scheduled = false
const pendingScopes = new Set<HTMLElement>()

// Keyboard binding is host integration, not a restyled replacement for Select.
function PlaygroundSelect({ label, value, options, onChange, disabled = false }: {
  label: string; value: string | number; options: SelectOption[];
  onChange: (value: string | number) => void; disabled?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null)
  const activeIndex = useRef(-1)
  const [open, setOpen] = useState(false)
  const onOpenChange = useCallback((next: boolean) => {
    activeIndex.current = -1
    setOpen(next)
  }, [])
  const trigger = () => host.current?.querySelector<HTMLElement>(':scope > div > div')?.click()
  return <div ref={host} className="w-full" data-upstream-control="select" role="combobox" aria-label={label} aria-expanded={open} aria-haspopup="listbox" tabIndex={disabled ? -1 : 0} onKeyDown={(event) => {
    if (disabled || (event.target as HTMLElement).closest('button')) return
    const items = Array.from(host.current?.querySelectorAll<HTMLElement>('[data-option-value]') || [])
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      if (!open) { activeIndex.current = -1; trigger(); return }
      if (!items.length) return
      activeIndex.current = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
        : activeIndex.current < 0 ? (event.key === 'ArrowUp' ? items.length - 1 : 0)
          : (activeIndex.current + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length
      const option = items[activeIndex.current]
      option.tabIndex = -1
      option.focus()
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (open && activeIndex.current >= 0) items[activeIndex.current]?.click()
      else trigger()
    } else if (event.key === 'Escape' && open) {
      event.preventDefault()
      event.stopPropagation()
      trigger()
      host.current?.focus()
    } else if (event.key === 'Tab' && open) {
      trigger()
    }
  }}>
    <Select value={value} options={options} onChange={(next) => { onChange(next); host.current?.focus() }} disabled={disabled} onOpenChange={onOpenChange} className={SETTINGS_INPUT_CLASS} />
  </div>
}

function tokens(element: HTMLElement, classes: string) {
  const previous = styledTokens.get(element)
  if (previous?.classes === classes) return
  const next = classes.split(/\s+/).filter(Boolean)
  if (previous) element.classList.remove(...previous.tokens)
  element.classList.add(...next)
  styledTokens.set(element, { classes, tokens: next })
}

function mount(owner: HTMLElement, fingerprint: string, content: ReactNode) {
  let island = islands.get(owner)
  if (island && !island.host.isConnected) {
    island.root.unmount()
    islands.delete(owner)
    island = undefined
  }
  if (!island) {
    const host = document.createElement('span')
    host.dataset.playgroundIsland = 'true'
    host.className = 'playground-island'
    owner.append(host)
    island = { host, root: createRoot(host), fingerprint: '' }
    islands.set(owner, island)
  }
  if (island.fingerprint === fingerprint) return
  island.fingerprint = fingerprint
  island.root.render(content)
}

function nativeChange(control: HTMLInputElement | HTMLSelectElement) {
  control.dispatchEvent(new Event('input', { bubbles: true }))
  control.dispatchEvent(new Event('change', { bubbles: true }))
  schedule(control.parentElement!)
}

function choose(buttons: HTMLButtonElement[], value: string | number) {
  buttons.find((button) => (button.dataset.val ?? button.dataset.id) === String(value))?.click()
}

function nativeButtons(owner: HTMLElement, selector: string) {
  return Array.from(owner.querySelectorAll<HTMLButtonElement>(selector)).filter((button) => !button.closest('[data-playground-island]'))
}

function mountButtonSelect(owner: HTMLElement, buttons: HTMLButtonElement[], label: string) {
  if (!buttons.length) return
  const active = buttons.find((button) => button.classList.contains('active'))
  const value = active?.dataset.val ?? active?.dataset.id ?? ''
  const options: SelectOption[] = buttons.map((button) => {
    const remove = button.parentElement?.classList.contains('model-chip')
      ? button.parentElement.querySelector<HTMLButtonElement>('.chip-del')
      : null
    return {
      value: button.dataset.val ?? button.dataset.id ?? '',
      label: button.textContent?.trim() || '',
      ...(remove ? { actions: [{ label: '删除', variant: 'danger' as const, onClick: () => remove.click() }] } : {}),
    }
  })
  Array.from(owner.children).forEach((child) => {
    if (child instanceof HTMLElement && !child.dataset.playgroundIsland) child.hidden = true
  })
  const fingerprint = JSON.stringify([value, options.map((option) => [option.value, option.label, Boolean(option.actions)])])
  mount(owner, fingerprint,
    <PlaygroundSelect label={label} value={value} options={options} onChange={(next) => choose(buttons, next)} />,
  )
}

function mountBackups(owner: HTMLElement) {
  const buttons = nativeButtons(owner, 'button.selector-chip')
  if (!buttons.length) return
  buttons.forEach((button) => { button.hidden = true })
  const values = buttons.map((button) => [button.dataset.id, button.classList.contains('active'), button.querySelector('.selector-chip-order')?.textContent])
  mount(owner, JSON.stringify(values),
    <div className="flex flex-wrap items-center gap-3" data-upstream-control="checkboxes">
      {buttons.map((button) => {
        const order = button.querySelector('.selector-chip-order')?.textContent
        return <Checkbox key={button.dataset.id} label={`${button.dataset.id}${order ? ` · ${order}` : ''}`} checked={button.classList.contains('active')} onChange={() => button.click()} />
      })}
    </div>,
  )
}

function mountSwitch(input: HTMLInputElement) {
  const owner = input.parentElement!
  input.hidden = true
  const label = input.getAttribute('aria-label') || input.id
  mount(owner, JSON.stringify([input.checked, input.disabled, label]),
    <Switch checked={input.checked} disabled={input.disabled} label={label} onChange={(checked) => {
      input.checked = checked
      nativeChange(input)
    }} />,
  )
}

function mountNativeSelect(select: HTMLSelectElement) {
  const owner = select.parentElement!
  select.hidden = true
  const options = Array.from(select.options).map((option) => ({ value: option.value, label: option.label }))
  mount(owner, JSON.stringify([select.value, options]),
    <PlaygroundSelect label={select.labels?.[0]?.textContent?.trim() || select.id} value={select.value} options={options} disabled={select.disabled} onChange={(value) => {
        select.value = String(value)
        nativeChange(select)
    }} />,
  )
}

function within<T extends HTMLElement>(scope: HTMLElement, selector: string): T[] {
  return [...(scope.matches(selector) ? [scope as T] : []), ...scope.querySelectorAll<T>(selector)]
}

function decorate(scope: HTMLElement) {
  within(scope, '.input-modern, .input-glass').forEach((element) => tokens(element, SETTINGS_INPUT_CLASS))
  within(scope, nativeButtonSelector).forEach((button) => {
    if (button.closest('[data-playground-island], #playground-overlay-root')) return
    if (button.matches('.nav-item, .persona-profile-chip')) {
      tokens(button, SETTINGS_NAV_CLASSES[button.classList.contains('active') ? 'active' : 'inactive'])
    } else if (button.classList.contains('btn-danger')) {
      tokens(button, SETTINGS_BUTTON_CLASSES.danger)
    } else if (button.classList.contains('btn-primary')) {
      tokens(button, SETTINGS_BUTTON_CLASSES.primary)
    } else if (button.matches('.chip-del, .persona-profile-delete, .btn-del-img')) {
      tokens(button, SETTINGS_BUTTON_CLASSES.ghost)
    } else {
      tokens(button, SETTINGS_BUTTON_CLASSES.secondary)
    }
  })
  const styles: Record<string, string> = {
    '.sidebar': 'bg-gray-50/50 border-gray-100',
    '.save-panel': 'bg-white border-gray-100',
    '.brand-block h1': 'text-base font-bold text-gray-800',
    '.brand-block p, .eyebrow, .nav-label, .sidebar-metrics small': 'text-xs text-gray-400',
    '.brand-mark': 'text-blue-500',
    '.topbar h2': 'text-lg font-bold text-gray-800',
    '.topbar-caption, .card p, .field-hint, .save-state': 'text-sm text-gray-500',
    '.card h3, .form-group > label': 'text-sm font-medium text-gray-700',
    '.card, .node-card, .route-row': 'rounded-2xl border border-gray-200 bg-white p-4',
    '.status-pill': 'rounded-xl bg-black/[0.04] text-xs text-gray-500',
    '.section-note, .cache-setting-row': 'rounded-xl border border-gray-100 bg-white text-sm text-gray-600',
    '.empty-state': 'rounded-xl border border-dashed border-gray-200 text-sm text-gray-400',
    '.empty-hint': 'text-xs text-gray-400',
    '.usage-summary > div, .cache-summary > div': 'rounded-2xl border border-gray-100 bg-white p-4',
    '.usage-summary span, .cache-summary span': 'text-lg font-medium text-gray-700',
    '.usage-summary small, .cache-summary small, .usage-user-main small': 'text-xs text-gray-500',
    '.cache-breakdown > div, .usage-user-row': 'rounded-2xl border border-gray-100 bg-white p-4 text-sm text-gray-600',
    '.usage-user-row > span': 'text-blue-500',
    '.upload-trigger': SETTINGS_BUTTON_CLASSES.secondary,
  }
  Object.entries(styles).forEach(([selector, classes]) => {
    within(scope, selector).forEach((element) => tokens(element, classes))
  })
}

function dispose(scope: HTMLElement) {
  for (const [owner, island] of islands) {
    if (scope.contains(owner)) {
      island.root.unmount()
      islands.delete(owner)
    }
  }
}

function hydrate(scope: HTMLElement) {
  decorate(scope)
  within<HTMLInputElement>(scope, 'input.ios-switch').forEach(mountSwitch)
  within<HTMLSelectElement>(scope, 'select.input-modern').forEach(mountNativeSelect)
  within(scope, '.node-selector, .node-selector-video').forEach((owner) => {
    mountButtonSelect(owner, nativeButtons(owner, 'button.selector-chip'), owner.id)
  })
  within(scope, '.route-backup-selector').forEach(mountBackups)
  within(scope, '.chip-group').forEach((owner) => {
    mountButtonSelect(owner, nativeButtons(owner, 'button.api-chip'), owner.parentElement?.querySelector('label')?.textContent || '选择')
  })
  document.documentElement.dataset.playgroundReady = 'true'
}

function schedule(scope: HTMLElement) {
  if (!scope?.isConnected) return
  const pane = scope.closest('.tab-pane')
  if (pane && !pane.classList.contains('active')) return
  for (const pending of pendingScopes) {
    if (pending.contains(scope)) return
    if (scope.contains(pending)) pendingScopes.delete(pending)
  }
  pendingScopes.add(scope)
  if (scheduled) return
  scheduled = true
  requestAnimationFrame(() => {
    scheduled = false
    const scopes = [...pendingScopes]
    pendingScopes.clear()
    for (const target of scopes) if (target.isConnected) hydrate(target)
  })
}

function OverlayApp() {
  const [drawer, setDrawer] = useState<'navigation' | 'gif' | null>(null)
  useEffect(() => {
    const open = (event: Event) => setDrawer((event as CustomEvent).detail)
    window.addEventListener('omnidraw:drawer', open)
    return () => window.removeEventListener('omnidraw:drawer', open)
  }, [])
  const nav = Array.from(document.querySelectorAll<HTMLButtonElement>('.nav-item'))
  return <>
    <ConfirmDialog />
    <div role="status" aria-live="polite"><Toast /></div>
    <SettingsDrawer open={drawer !== null} onClose={() => setDrawer(null)} title={drawer === 'navigation' ? '插件配置' : 'GPT Image 2.6 · GIF'}>
      {drawer === 'navigation'
        ? <nav className="flex flex-col gap-1">{nav.map((item) => <button key={item.dataset.target} type="button" className={SETTINGS_NAV_CLASSES[item.classList.contains('active') ? 'active' : 'inactive']} onClick={() => { item.click(); setDrawer(null) }}>{item.textContent?.trim()}</button>)}</nav>
        : <div className="space-y-4 text-sm text-gray-600 leading-relaxed">
          <p>使用标准生图接口，模型设为 <code>gpt-image-2.6-sunburst</code> 或 <code>gpt-image-2.6-flare</code>，并确认账号或服务商已开放 GIF preview 权限。</p>
          <p className="rounded-xl bg-black/[0.04] p-3 font-mono text-xs break-words">/gif 小猫挥手 --frame_count 9 --frame_duration_ms 200 --size auto</p>
          <p>请求使用 <code>output_format=gif</code>。帧数 2 至 16，每帧 20 至 2000 毫秒，默认 9 帧、200 毫秒。尺寸建议使用 <code>auto</code>。</p>
          <p>GIF 不支持流式输出、局部图像、蒙版或自定义输出压缩。普通绘图仍使用原有静态图片流程，已有配置与模型不变。</p>
          <p>LLM 可根据用户意图显式选择 GIF。实际生成能力与 preview 权限以服务商为准。</p>
          <Button variant="primary" onClick={() => setDrawer(null)}>知道了</Button>
        </div>}
    </SettingsDrawer>
  </>
}

let toastTimer: ReturnType<typeof window.setTimeout> | undefined
window.addEventListener('omnidraw:toast', (event) => {
  const detail = (event as CustomEvent).detail
  const type = detail?.type === 'error' ? 'error' : detail?.type === 'info' ? 'info' : 'success'
  window.clearTimeout(toastTimer)
  useStore.getState().setToast({ message: String(detail?.message ?? ''), type })
  toastTimer = window.setTimeout(() => useStore.getState().setToast(null), 3200)
})

const root = document.createElement('div')
root.id = 'playground-overlay-root'
document.body.append(root)
createRoot(root).render(<OverlayApp />)

const navIcons = [SettingsIcon, HistoryIcon, CollectionManageIcon, LinkIcon, SparklesIcon, CodeIcon, SettingsIcon]
document.querySelectorAll<HTMLElement>('.nav-icon').forEach((element, index) => {
  const Icon = navIcons[index] || SettingsIcon
  element.replaceChildren()
  mount(element, 'icon', <Icon className="w-4 h-4" />)
})
const brand = document.querySelector<HTMLElement>('.brand-mark')
if (brand) { brand.replaceChildren(); mount(brand, 'brand', <SketchIcon className="w-6 h-6" />) }

document.addEventListener('click', (event) => {
  const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-action]') : null
  if (!target) return
  const action = target.dataset.action || ''
  if (action === 'show-gif-help' || action === 'open-navigation') {
    event.preventDefault()
    event.stopImmediatePropagation()
    window.dispatchEvent(new CustomEvent('omnidraw:drawer', { detail: action === 'show-gif-help' ? 'gif' : 'navigation' }))
    return
  }
  if (!action.startsWith('del-') && action !== 'clear-cache') return
  if (confirmedActions.has(target)) { confirmedActions.delete(target); return }
  event.preventDefault()
  event.stopImmediatePropagation()
  const cache = action === 'clear-cache'
  useStore.getState().setConfirmDialog({
    title: cache ? '清理图片缓存' : '确认移除',
    message: cache ? '仅清理 temp_images 与 user_refs 中的缓存，人设参考图不受影响。' : '移除当前项目后，点击保存更改才会写入配置。',
    confirmText: cache ? '清理缓存' : '确认移除',
    cancelText: '取消',
    tone: 'danger',
    action: () => {
      if (!target.isConnected) return
      confirmedActions.add(target)
      target.click()
    },
  })
}, true)

// Only the host's explicit DOM commits hydrate islands; React's own mutations
// and ordinary keystrokes must never trigger another document-wide scan.
window.addEventListener('omnidraw:render', (event) => schedule((event as CustomEvent).detail.root))
window.addEventListener('omnidraw:dispose', (event) => dispose((event as CustomEvent).detail.root))
for (const selector of ['.sidebar', '.topbar', '.tab-pane.active']) {
  const scope = document.querySelector<HTMLElement>(selector)
  if (scope) schedule(scope)
}
