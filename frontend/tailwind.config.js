/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        disaster: {
          p1: "#ef4444",
          p2: "#f97316",
          p3: "#eab308",
          p4: "#6b7280",
        },
      },
    },
  },
  plugins: [],
};
