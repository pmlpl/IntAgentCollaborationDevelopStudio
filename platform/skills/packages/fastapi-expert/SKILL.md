# FastAPI Expert

FastAPI 后端开发最佳实践规范。

## 项目结构
- `app/` — 应用入口与配置
- `app/api/` — 路由与端点定义（按资源分文件）
- `app/models/` — SQLAlchemy 数据模型
- `app/services/` — 业务逻辑层
- `app/schemas/` — Pydantic 请求/响应序列化
- `app/dependencies.py` — 可复用 Depends 依赖
- `tests/` — 按模块组织的测试

## 代码规范
1. 路由函数返回 Pydantic 模型，不要返回原生 dict
2. 数据库操作优先使用 async session（`AsyncSession`）
3. 异常使用 `HTTPException` 并附带明确状态码和 detail
4. 使用 lifespan context manager 管理启动/关闭资源
5. 复杂查询封装为 service 函数，路由只做参数提取和响应

## API 设计
- RESTful 命名：GET /items、POST /items、GET /items/{id}、PUT /items/{id}、DELETE /items/{id}
- 分页参数统一：`skip: int = Query(0)`, `limit: int = Query(100)`
- 返回格式统一定义在 `app/schemas/common.py`
- 输入验证用 Pydantic v2 model_validator

## 测试
- 使用 `TestClient` + `pytest-asyncio`
- 每个端点至少覆盖：200 成功、404 找不到、422 参数错误
- 数据库测试用内存 SQLite 或测试 fixture 覆盖真实 DB
