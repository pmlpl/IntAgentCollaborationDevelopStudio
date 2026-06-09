# Python Async

异步 IO 与数据库最佳实践。

## 核心原则
1. 禁止在 async 路由/协程中调用同步阻塞 IO（如 `requests.get()`、`time.sleep()`）
2. 数据库操作用 `await session.execute(select(...))` 而非同步方式
3. 并发请求用 `asyncio.gather()` 或 `asyncio.TaskGroup`（Python 3.11+）

## 数据库
- SQLAlchemy 2.0+ 用 `select()` 风格，弃用 `Query()` 风格
- 连接池：asyncpg 用 `asyncpg.create_pool()`，或通过 SQLAlchemy `create_async_engine`
- 事务用 `async with session.begin():` 确保自动提交/回滚

## 常见模式
```python
# 正确：异步数据库查询
async def get_user(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

# 错误：同步阻塞在 async 上下文中
def get_user_sync(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()
```

## 测试
- 用 `pytest-asyncio` + `pytest.mark.asyncio`
- 数据库 fixture 用 `async_session` + 事务回滚
