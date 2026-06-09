# FastAPI 专家技能包

用于后端 REST API 开发：路由设计、Pydantic 校验、OpenAPI 文档。

## 规范要点

1. 路由使用名词复数，动词用 HTTP 方法表达
2. 响应体统一 `{ "data": ..., "error": null }` 包装
3. 数据库访问优先 async session
