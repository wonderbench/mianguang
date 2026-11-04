# EDA导出脚本

以`../release_v02/Mianguang_V0.2.epro2`为工程入口。这里记录已复核工程的导出流程，不从零建图或重新布线。

- `eda_release_bridge.py`发现本机EDA窗口并核对项目UUID、项目名与文档UUID，拒绝写入其他工程。
- `export_release_v02.py`导出源、网表、BOM、坐标、Gerber、完整工程、图纸及原生检查记录；CSV转换为UTF-8标准逗号格式，PDF使用`pypdf`提取装配和图层页。

依赖嘉立创EDA专业版、EasyEDA API Gateway、本机桥接服务与Python的`pypdf`。UUID针对原始V0.2工作工程；新电脑导入后应核对真实UUID并在副本中配置，不应直接修改保护条件以跳过检查。

执行会覆盖`release_v02/`导出，令现有manifest失效；只应在新版本副本中使用。修改后需保存并重新打开，尤其不能只凭原理图文字API返回成功判定已持久化。统一导出后执行`../qa/`检查并生成新的校验清单。

旧版建图、重排、布局及一次性修补脚本依赖当时实例ID和中间数据，未作为本仓库可复现入口提供。
