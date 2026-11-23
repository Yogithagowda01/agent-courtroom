/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#1F2937',
        navy: '#1F2A44',
        muted: '#6B7280',
        line: '#D1D5DB',
        panel: '#F3F4F6',
        bar: '#E5E7EB',
        teal: { DEFAULT: '#0F766E', light: '#CCFBF1' },
        coral: { DEFAULT: '#C2410C', light: '#FFEDD5' },
        blue: { DEFAULT: '#1D4ED8', light: '#DBEAFE' },
        purple: { DEFAULT: '#6D28D9', light: '#EDE9FE' },
        gold: { DEFAULT: '#B45309', light: '#FEF3C7' },
      },
      fontFamily: {
        sans: ['"Helvetica Neue"', 'Helvetica', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
