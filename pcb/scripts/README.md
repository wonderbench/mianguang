# EDA导出脚本

当前工程入口为`../release_v03_precheck03/Mianguang_V0.3.epro2`。这里记录已复核工程的导出流程，不从零建图或重新布线。以下V0.2脚本为历史流程，不能用来覆盖已冻结目录。

- `eda_release_bridge.py`发现本机EDA窗口并核对项目UUID、项目名与文档UUID，拒绝写入其他工程。
- `export_release_v02.py`导出源、网表、BOM、坐标、Gerber、完整工程、图纸及原生检查记录；CSV转换为UTF-8标准逗号格式，PDF使用`pypdf`提取装配和图层页。

依赖嘉立创EDA专业版、EasyEDA API Gateway、本机桥接服务与Python的`pypdf`。UUID针对原始V0.2工作工程；新电脑导入后应核对真实UUID并在副本中配置，不应直接修改保护条件以跳过检查。

执行会覆盖`release_v02/`导出，令现有manifest失效；只应在新版本副本中使用。修改后需保存并重新打开，尤其不能只凭原理图文字API返回成功判定已持久化。统一导出后执行`../qa/`检查并生成新的校验清单。

旧版建图、重排、布局及一次性修补脚本依赖当时实例ID和中间数据，未作为本仓库可复现入口提供。

## V0.3 修订导出

`eda_bridge_v03.py` 仅连接 UUID 与名称都匹配的独立 V0.3 工程；提供 `run(code, tag, document=None)` 和 `open_document(uuid)`（别名 `open_doc`）。诊断记录写入忽略目录 `verification/local/pcb_v03_work/`。该模块导入时不连接 EDA。

完成保存、重开和修改持久性复核后运行`export_release_v03.py`。它要求原理图与PCB严格检查都返回`passed=true`且详细列表为空；默认目录`release_v03/`已经冻结，会拒绝覆盖。后续候选可导入模块并显式设置`OUT`为新的绝对路径，再调用`main()`；03本轮使用`release_v03_precheck03/`，现也已冻结。

中间文件及完整原生PDF保留在本地诊断目录，四页查看PDF单独导出。原生检查记录绑定最终`.esch` / `.epcb` / `.epro2`的SHA-256，并核对实际23个元件和所用封装在检查、导出前后及完整工程包内一致。比较忽略编辑器重建的记录序号、DOCHEAD时间/客户端字段；包内封装比较另忽略结构已验证的`ELE_PLACEHOLDER`分配计数，实际PAD/POLY/ATTR仍须完整一致，删除或恢复图形的差异会失败。6项回归覆盖该边界。该工具不生成发布清单，也不代替独立Gerber、采购、装配及保存重开检查。PDF依赖固定在本目录`requirements.txt`。

## Gerber与SMT派生文件

`prepare_gerber_upload.py`在冻结前处理原生Gerber。必须先保存原始ZIP；脚本证明Via分类钻孔完全包含在主PTH后，仅去掉该冗余附表，检查全部保留成员字节、42个独立孔及孔属性不变。它拒绝覆盖已冻结目录，不能当作通用删孔工具。03原始包与证据见`../qa/v03/precheck03/`。

`prepare_smt_preflight_v03.py`在源目录冻结后生成SMT子集和哈希记录，不改工程。默认对应02；03须明确指定：

```sh
python3 pcb/scripts/prepare_smt_preflight_v03.py --release pcb/release_v03_precheck03 --output pcb/preflight_v03/smt_precheck03
```

输出9组14件SMT BOM、14位号CPL及9件手工项。来源manifest、位号、数量、焊盘类别和坐标均核对；已存在目录不能混入另一来源。输出仍须交由用户手动上传平台进行SMT匹配及方向确认。
