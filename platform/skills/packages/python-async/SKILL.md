# Python 异步技能包

异步 IO、asyncpg、SQLAlchemy async session 模式。

## 规范要点

1. 禁止在 async 路由中调用阻塞 IO
2. 数据库操作用 `await session.execute(...)`
