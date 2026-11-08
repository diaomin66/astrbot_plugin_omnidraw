// Host adapter only. The upstream ConfirmDialog component remains unmodified.
import type { ReactNode } from 'react'
import { create } from 'zustand'

export interface ConfirmDialogState {
  title: string
  message: string
  content?: ReactNode
  checkbox?: { label: string; defaultChecked?: boolean; disabled?: boolean; tone?: 'primary' | 'danger' }
  confirmText?: string
  cancelText?: string
  showCancel?: boolean
  buttons?: Array<{ label: string; tone?: 'primary' | 'secondary' | 'danger' | 'warning'; action: (checked?: boolean) => void }>
  icon?: 'info' | 'copy'
  minConfirmDelayMs?: number
  messageAlign?: 'left' | 'center'
  tone?: 'danger' | 'warning'
  awaitAction?: boolean
  busyText?: string
  action?: (checked?: boolean) => void | boolean | Promise<void | boolean>
  cancelAction?: (checked?: boolean) => void
}

export const useStore = create<{
  confirmDialog: ConfirmDialogState | null
  setConfirmDialog: (dialog: ConfirmDialogState | null) => void
  toast: { message: string; type: 'success' | 'error' | 'info' } | null
  setToast: (toast: { message: string; type: 'success' | 'error' | 'info' } | null) => void
}>((set) => ({
  confirmDialog: null,
  setConfirmDialog: (confirmDialog) => set({ confirmDialog }),
  toast: null,
  setToast: (toast) => set({ toast }),
}))
