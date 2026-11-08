// Extracted JSX/classes from SettingsModal.tsx and ConfirmDialog.tsx at
// 6f8f44dadf77f7880f0db1eefb004fe0474b27d4. Copyright 2026 CookSleep, MIT.
// Only the application-specific data bindings are replaced with props.
import { useRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CloseIcon } from './components/icons'
import { useCloseOnEscape } from './hooks/useCloseOnEscape'
import { usePreventBackgroundScroll } from './hooks/usePreventBackgroundScroll'

export const SETTINGS_INPUT_CLASS = 'w-full rounded-xl border border-transparent bg-black/[0.04] px-3 py-2.5 text-sm text-gray-700 outline-none transition focus:border-blue-300 dark:bg-white/[0.06] dark:text-gray-200 dark:focus:border-blue-500/50'
export const SETTINGS_NAV_CLASS = 'whitespace-nowrap flex-shrink-0 flex items-center gap-2.5 px-3 py-2.5 text-sm rounded-xl transition-colors'
export const SETTINGS_NAV_ACTIVE_CLASS = 'bg-white dark:bg-white/[0.08] shadow-sm text-blue-600 dark:text-blue-400 font-medium'
export const SETTINGS_NAV_INACTIVE_CLASS = 'text-gray-600 dark:text-gray-400 hover:bg-gray-100/80 dark:hover:bg-white/[0.04]'
export const SETTINGS_NAV_CLASSES = {
  active: `${SETTINGS_NAV_CLASS} ${SETTINGS_NAV_ACTIVE_CLASS}`,
  inactive: `${SETTINGS_NAV_CLASS} ${SETTINGS_NAV_INACTIVE_CLASS}`,
}

const actionClasses = {
  primary: 'bg-blue-500 text-white hover:bg-blue-600',
  secondary: 'border border-transparent bg-black/[0.04] text-gray-600 hover:bg-black/[0.07] dark:bg-white/[0.06] dark:text-gray-400 dark:hover:bg-white/[0.1]',
  danger: 'bg-red-500 text-white hover:bg-red-600',
  ghost: 'rounded-full p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-white/[0.06] dark:hover:text-gray-200',
}
export const SETTINGS_BUTTON_CLASSES = Object.fromEntries(
  Object.entries(actionClasses).map(([name, classes]) => [name,
    `${name === 'ghost' ? '' : 'py-2 px-3 rounded-xl text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60'} ${classes}`,
  ]),
) as Record<keyof typeof actionClasses, string>

export function Button({ variant = 'secondary', className = '', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof actionClasses
}) {
  return <button type="button" {...props} className={`${SETTINGS_BUTTON_CLASSES[variant]} ${className}`}>{children}</button>
}

export function Switch({ checked, onChange, label, disabled = false }: {
  checked: boolean; onChange: (checked: boolean) => void; label: string; disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      disabled={disabled}
      className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${checked ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'} ${disabled ? 'cursor-not-allowed opacity-70' : ''}`}
      role="switch"
      aria-checked={checked}
      aria-label={label}
    >
      <span className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-[14px]' : 'translate-x-[2px]'}`} />
    </button>
  )
}

export function SettingsDrawer({ open, onClose, title, children }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  useCloseOnEscape(open, onClose)
  usePreventBackgroundScroll(open, panelRef)
  if (!open) return null
  return createPortal(
    <div data-no-drag-select className="fixed inset-0 z-[70] flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm animate-overlay-in" onClick={onClose} />
      <div ref={panelRef} className="relative z-10 w-full max-w-3xl rounded-3xl border border-white/50 bg-white/95 shadow-2xl ring-1 ring-black/5 animate-modal-in dark:border-white/[0.08] dark:bg-gray-900/95 dark:ring-white/10 flex h-[85vh] sm:h-[600px] flex-col overflow-hidden">
        <div className="flex items-center justify-between shrink-0 p-5 border-b border-gray-100 dark:border-white/[0.08]">
          <h3 className="text-lg font-bold text-gray-800 dark:text-gray-100 flex items-center gap-2">{title}</h3>
          <button onClick={onClose} className="rounded-full p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-white/[0.06] dark:hover:text-gray-200" aria-label="Close">
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>
        <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>, document.body,
  )
}
