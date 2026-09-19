import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/** 这个文件跑在 node 里，但仓库没有装 @types/node，只声明这里用到的那一点 */
declare const process: { env: Record<string, string | undefined> }

/**
 * 手机访问这台机器上的前端：dev server 必须绑 0.0.0.0（绑 127.0.0.1 时只有本机连得上），
 * 而且**不能**把接口地址写死成 127.0.0.1 —— 在手机上那指的是手机自己。
 * 所以这里再挂两条代理：/api 与 /artifacts 转给本机后端 8000。
 * 前端发现「当前页面不是本机」时会自动改用同源相对地址（见 src/api/index.ts），
 * 于是同一个界面既能本机直连 8000，也能被手机/局域网访问（走这里的代理，且不受 CORS 限制）。
 */
const BACKEND = process.env.PAPERCAST_BACKEND || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5178,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND },
      '/artifacts': { target: BACKEND },
    },
  },
  preview: { host: '0.0.0.0', port: 4178, strictPort: true },
})
