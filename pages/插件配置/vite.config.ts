import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: 'assets',
    emptyOutDir: false,
    lib: { entry: 'src/main.tsx', formats: ['iife'], name: 'OmniDrawUI', fileName: () => 'ui.js', cssFileName: 'ui' },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
})
