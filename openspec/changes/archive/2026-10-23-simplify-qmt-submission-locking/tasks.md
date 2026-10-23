# Tasks

## 1. 核对状态同步边界

- [x] 1.1 核对 `_submit` 仍仅由 `refresh` 调用，且 `refresh` 保留 `state.running` 与两个阶段标志的加锁转换；通过搜索调用点和检查函数代码确认。
- [x] 1.2 核对 `_submit` 在 `passorder` 前直接登记 `attempts`、`_callback_order` 直接查询登记记录，且两处不再获取 `state.lock`；运行 QMT 定向测试，确认定时器重入、同步回调和单笔失败后继续的场景通过。
- [x] 1.3 运行项目完整单元测试，确认全部通过，且没有为内部锁的具体写法增加仅镜像实现的测试。
