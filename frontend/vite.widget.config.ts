import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * チャットウィジェット単体ビルド用Vite設定
 * 使い方: vite build --config vite.widget.config.ts
 * 出力: dist-widget/widget.js
 */
export default defineConfig({
    plugins: [react()],
    build: {
        outDir: 'dist-widget',
        lib: {
            entry: 'src/chatbot/widget-entry.tsx',
            name: 'ClinicChatWidget',
            fileName: () => 'widget.js',
            formats: ['iife'],
        },
        rollupOptions: {
            // React/ReactDomもバンドルに含める（外部サイトに依存しない）
        },
    },
    define: {
        'process.env.NODE_ENV': '"production"',
    },
})
