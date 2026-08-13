import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        content: resolve(__dirname, 'src/content.jsx'),
        background: resolve(__dirname, 'src/background.js'),
      },
      output: {
        entryFileNames: (chunkInfo) => {
          if (chunkInfo.name === 'content' || chunkInfo.name === 'background') {
            return '[name].js';
          }
          return 'assets/[name].js';
        },
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            return 'panel.css';
          }
          return 'assets/[name].[ext]';
        },
        manualChunks: undefined,
      },
    },
  },
});
