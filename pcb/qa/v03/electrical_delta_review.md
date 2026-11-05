# PCB V0.3 相对 V0.2 独立电气与机械差异复核

复核日期：2026-11-05。结果：**PASS**，共 17 项比较。只读取发布文件；未调用 EDA、未修改工程。

| 比较对象 | 结果 |
|---|---|
| source_copies_v03 | PASS |
| component_reference_set | PASS |
| component_position_rotation_layer | PASS |
| global_physical_pad_geometry_and_nets | PASS |
| native_holes | PASS |
| pcb_pad_net_primitives | PASS |
| schematic_pin_networks | PASS |
| pcb_pin_networks | PASS |
| gerber_top_copper | PASS |
| gerber_bottom_copper | PASS |
| gerber_outline | PASS |
| gerber_drill_positions_diameters_plating | PASS |
| gerber_parser_supported | PASS |
| C1_procurement_update_without_electrical_geometry_change | PASS |
| C4_procurement_update_without_electrical_geometry_change | PASS |
| native_copper_outline_drill_stack_records | PASS |
| physical_part_identity_and_model_transforms | PASS |

## 结论

V0.3 顶、底层 Gerber 铜图形与 V0.2 的对称差面积均为 0 mm²；板框、42 个独立钻孔的中心/直径/镀铜属性一致。23 个器件的位置、角度、面别及63个物理焊盘的几何和网络一致。两份网表的所有引脚网络不变。

C1/C4 保持 CL21A106KAYNNNE 与原0805封装，供应商编号改为 C15850。逐一比较实际PAD定义、实例放置和引脚网络均一致；这次采购元数据更新没有改变焊盘或电路连接。

在上述几何比较通过的范围内，PCB V0.3 与已建立的 V0.2 外壳安装柱、接口位置和内部器件空间保持兼容。本结论不将数字模型尺寸相同扩展为实物插拔、材料公差、线束或散热验证。

结构兼容性以铜/孔、器件位置、封装实际焊盘、板框、层叠记录、真实采购料号以及模型名称/放置变换的相等为依据；外壳模型没有在本子任务中改动。丝印变化由制造复核单独检查。

补充发现：D1 与 J1/J3/J4/JP1/JP2/JP3 的 EDA 3D Model 资源 UUID 有变化，但相应的采购料号、3D Model Title 和 3D Model Transform 不变。完整工程包未嵌入这些远程3D模型实体，因而本复核不声称其远程模型二进制完全相同；这不改变上述实际PCB铜/孔与装配坐标比较。资源变更清单保留于JSON。

详细比较值、所有器件属性差异及此次输入 SHA-256 见 [electrical_delta_review.json](electrical_delta_review.json)。
