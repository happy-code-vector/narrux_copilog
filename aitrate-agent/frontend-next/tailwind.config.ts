import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          primary: '#ffffff',
          secondary: '#f4f3f0',
          tertiary: '#ebeae5',
          info: '#e6f1fb',
          danger: '#fceaea',
          success: '#e1f5ee',
          warning: '#faeeda',
        },
        text: {
          primary: '#1a1a18',
          secondary: '#5f5e5a',
          tertiary: '#888780',
          info: '#0c447c',
          danger: '#791f1f',
          success: '#04342c',
          warning: '#633806',
        },
        accent: '#185FA5',
        nav: '#1a1a18',
      },
      borderRadius: {
        md: '8px',
        lg: '12px',
      },
    },
  },
  plugins: [],
};

export default config;
