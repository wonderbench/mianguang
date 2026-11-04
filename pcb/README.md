# PCB设计 · V0.2

载板为66 × 56 mm双面PCB，使用C1001雷达外接接口和XIAO ESP32C3插座。V0.2已统一F1选料、保留XIAO的14个通孔、增加JP2/JP3串口断开跳线与C4/C5去耦，并完成重新布线和检查。

| 目录或文件 | 用途 |
|---|---|
| [release_v02/](release_v02/) | 已冻结工程、原理图/PCB源、BOM、Gerber、坐标、预览、装配说明及manifest |
| [releases/](releases/) | 完整交付ZIP及SHA-256 |
| [release_v02_acceptance.json](release_v02_acceptance.json) | 44/44通过的独立验收报告，绑定发布manifest |
| [qa/](qa/) | 网表、铜连接、钻孔、锡膏和哈希检查程序 |
| [scripts/](scripts/) | 本版导出过程脚本及适用范围 |
| [LATEST.json](LATEST.json) | 最新版本与归档位置 |

在嘉立创EDA专业版导入[Mianguang_V0.2.epro2](release_v02/Mianguang_V0.2.epro2)。后续修改先另存新版本，再统一更新工程、BOM、Gerber和检查清单。原始`release_v02/`与ZIP保持字节不变，不在冻结目录中直接修订说明或覆盖文件。

[原理图预览](release_v02/Schematic_V0.2.png) · [PCB四页查看文件](release_v02/PCB_Review_V0.2.pdf) · [装配和上电步骤](release_v02/README_交付与装配.md)

PCB DRC为0错误。原理图无致命/电气错误，保留一组涉及8个排针的采购属性警告，因此原理图检查布尔值仍为false。独立校验覆盖实际铜连通、42个独立钻孔、29个SMT锡膏开窗、14个XIAO通孔及同版文件一致性；不代替实物验证。

冻结说明中的`hardware/`、历史脚本及旧版路径来自原工作区：本仓库分类后对应`pcb/`，历史V0.1工程和中间补丁未作为当前制造文件上传。PCB与固件版本分别为V0.2和V0.2.0。
