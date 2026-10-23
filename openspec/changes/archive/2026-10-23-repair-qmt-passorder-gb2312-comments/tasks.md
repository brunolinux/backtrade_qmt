# Tasks

## 1. 修复注释与编码一致性

- [x] 1.1 更新脚本兼容性测试，使其检查 `gb2312` 编码声明、严格解码及字节往返；先运行该测试，确认现有声明使其失败。
- [x] 1.2 在 `qmt_passorder.py` 中重写四处乱码字段注释，修正 `_snapshot` 的持仓表述并声明 `gb2312`；验证文件严格按 GB2312 往返、可编译，且 QMT 定向测试通过。
- [x] 1.3 将 `qmt_passorder.md` 的编码说明改为 GB2312；搜索脚本、文档和兼容性测试，确认三者的编码描述一致。
- [x] 1.4 运行项目完整单元测试和 `openspec validate repair-qmt-passorder-gb2312-comments --strict`，确认交易行为未受影响且变更有效。
