# Vue3 Debug & Standards

Vue3 + Pinia + Tailwind CSS 前端开发规范。

## 组件规范
1. 使用 `<script setup lang="ts">` 语法（优先 TypeScript）
2. 组件文件名 PascalCase（如 `SearchBar.vue`）
3. Props 用 `defineProps<{...}>()` 类型注解
4. Emits 用 `defineEmits<{...}>()` 类型注解
5. 组件内保持单一职责，超过 300 行拆分子组件

## 状态管理（Pinia）
1. 全局状态放 Pinia store，不在组件间 prop drilling
2. Store 命名：`use[Feature]Store`（如 `useAuthStore`）
3. Store 内区分 state / getters / actions
4. 异步数据用 actions + async/await，loading/error 状态放在 store 中

## 样式（Tailwind CSS）
1. 优先使用 Tailwind 原子类，不写自定义 CSS 除非必要
2. 类名组织顺序：布局（flex/grid/position）→ 间距（p/m/gap）→ 尺寸（w/h）→ 颜色（bg/text/border）→ 其他
3. 响应式：移动端优先 `md:` `lg:` 断点
4. 暗色模式用 `dark:` 前缀

## 调试技巧
1. Vue DevTools 查看组件树、Pinia state、事件
2. `console.log` 仅用于开发调试，提交前删除
3. 错误边界用 `onErrorCaptured` 捕获子组件异常
