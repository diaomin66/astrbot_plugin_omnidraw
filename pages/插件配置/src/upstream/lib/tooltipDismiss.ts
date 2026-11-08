/**
 * Global tooltip dismiss bus.
 *
 * Any code that opens a modal / overlay should call `dismissAllTooltips()`.
 * ViewportTooltip and useTooltip subscribe to this event and auto-hide.
 *
 * Implementation: a simple EventTarget singleton — zero dependencies,
 * no React context required, works across the entire component tree.
 */

const bus = new EventTarget()
const EVENT_NAME = 'dismiss-tooltips'

/** Call this before opening any modal / dialog to hide every tooltip. */
export function dismissAllTooltips() {
  bus.dispatchEvent(new Event(EVENT_NAME))
}

/** Subscribe to the dismiss signal. Returns an unsubscribe function. */
export function onDismissTooltips(callback: () => void): () => void {
  bus.addEventListener(EVENT_NAME, callback)
  return () => bus.removeEventListener(EVENT_NAME, callback)
}
