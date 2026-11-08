import colors from 'tailwindcss/colors'

// Original GPT Image Playground theme; only the local content glob differs.
export default {
  darkMode: 'class',
  content: ['./index.html', './app.js', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        background: 'hsl(var(--background) / <alpha-value>)',
        border: 'hsl(var(--border) / <alpha-value>)',
        gray: colors.zinc,
        foreground: 'hsl(var(--foreground) / <alpha-value>)',
        input: 'hsl(var(--input) / <alpha-value>)',
        muted: { DEFAULT: 'hsl(var(--muted) / <alpha-value>)', foreground: 'hsl(var(--muted-foreground) / <alpha-value>)' },
        primary: { DEFAULT: 'hsl(var(--primary) / <alpha-value>)', foreground: 'hsl(var(--primary-foreground) / <alpha-value>)' },
        sidebar: { DEFAULT: 'hsl(var(--sidebar) / <alpha-value>)', foreground: 'hsl(var(--sidebar-foreground) / <alpha-value>)' },
      },
      fontFamily: { sans: ['var(--font-ui-sans)'], mono: ['var(--font-mono)'] },
    },
  },
  plugins: [],
}
