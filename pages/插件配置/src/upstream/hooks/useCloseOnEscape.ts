import { useEffect, useRef } from 'react'

/**
 * 全局 ESC 栈：每个模态注册时入栈，只有栈顶的 handler 会被调用。
 * 这样保证 ESC 一次只关闭最顶层的一个弹窗。
 */
const escStack: Array<{ id: number; handler: () => void }> = []
let nextId = 0

function globalKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (escStack.length === 0) return
  e.preventDefault()
  // 调用栈顶（最后注册的）handler
  escStack[escStack.length - 1].handler()
}

// 只注册一次全局监听
let listenerAttached = false
function ensureListener() {
  if (listenerAttached) return
  listenerAttached = true
  window.addEventListener('keydown', globalKeyDown)
}

export function useCloseOnEscape(enabled: boolean, onClose: () => void) {
  const idRef = useRef<number | null>(null)
  const handlerRef = useRef(onClose)
  handlerRef.current = onClose

  useEffect(() => {
    if (!enabled) {
      // 清理
      if (idRef.current !== null) {
        const idx = escStack.findIndex((e) => e.id === idRef.current)
        if (idx !== -1) escStack.splice(idx, 1)
        idRef.current = null
      }
      return
    }

    ensureListener()
    const id = nextId++
    idRef.current = id
    escStack.push({ id, handler: () => handlerRef.current() })

    return () => {
      const idx = escStack.findIndex((e) => e.id === id)
      if (idx !== -1) escStack.splice(idx, 1)
      idRef.current = null
    }
  }, [enabled])
}
