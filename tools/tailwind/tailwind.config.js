/** Tailwind build config for the static frontend (run `npm run build` in this folder). */
module.exports = {
  // Paths are relative to this folder. app.js is included because it renders
  // result cards with Tailwind classes at runtime.
  content: ['../../frontend/index.html', '../../frontend/app.js'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Space Grotesk', 'system-ui', 'sans-serif'],
        display: ['Orbitron', 'Space Grotesk', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
};
