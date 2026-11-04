# 项目辅助脚本

`build_design_document.py`生成2026-10-28方案书的历史版本，使用`python-docx`、`models/renders/`效果图与`docs/source/delivery_status_2026-10-28.json`。在独立Python环境安装`python-docx`后，从仓库根目录运行：

```sh
python3 tools/build_design_document.py
```

输出在`docs/generated/`，不覆盖已交付PDF/DOCX。字体为`docs/fonts/`中的Noto Sans CJK SC；转PDF环境需能读取该字体。脚本保留原方案内容，不会自动同步PCB新版本状态。

固件构建与日志工具在`firmware/`，PCB校验与导出工具在`pcb/`，模型脚本在`models/scripts/`。
