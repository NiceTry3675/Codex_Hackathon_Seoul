/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#18221d",
        moss: {
          50: "#f3f7f2",
          100: "#e4eee3",
          500: "#4d735a",
          600: "#3b5e48",
          700: "#2f4b3a",
        },
        sand: "#f4efe6",
        coral: "#d5674c",
      },
      boxShadow: {
        card: "0 18px 50px -30px rgba(24, 34, 29, 0.28)",
      },
      fontFamily: {
        sans: [
          "Pretendard Variable",
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
