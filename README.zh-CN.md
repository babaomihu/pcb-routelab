# PCB RouteLab

[English](README.md)

PCB RouteLab 是一个 **PCB 布线研究工具箱**，用于运行、观察和比较布线策略。它将已有的 DeepSeek Harness 布线研究整理成独立任务，方便使用者接入自己的板文件、固定计划或策略表达式。

支持：

- 在工程副本上执行原生布线，保持原工程和规则。
- 导出整板规划观察，执行网络顺序、层偏好和通道选择计划。
- 执行受限拥塞代价表达式，不执行任意模型代码。
- 可选接入 Harness，让模型调用诊断、布线、选择及提交工具。
- 输出候选板、增删铜线清单和 KiCad 原生验收报告。
- 前台或后台运行，查询状态、取消、重新验收后导出结果。

## 开始使用

实际验证环境为 **macOS arm64、KiCad 10.0.4、Python 3.13**。先安装 KiCad 和 Rust 工具链，再在本仓库执行：

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.lock.txt -r requirements.lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps .
.venv/bin/pcb-routelab build-engine --build-dir ../routelab-build
.venv/bin/pcb-routelab doctor
.venv/bin/pcb-routelab run --board examples/two-nets/two-nets.kicad_pcb --output ../routelab-example
.venv/bin/pcb-routelab export ../routelab-example --output ../routelab-export
```

使用自己的板时，替换 `--board`，配套 `.kicad_pro` 默认取同名文件，也可通过 `--project` 指定。所有输出目录必须是新目录。先保存 KiCad 中需要参与任务的修改；程序读取磁盘文件，不读取或覆盖编辑器的未保存内容。

## 如何看结果

- `success`：连接改善至全连接，并通过原规则验收。
- `safe_incomplete`：连接有改善且通过保护检查，但没有全部完成。
- `no_progress`：没有连接改善。
- `rejected`：候选不满足验收条件。
- `timeout` / `cancelled` / `error`：超时、取消或执行错误。

通过的候选位于任务目录 `review/`；`changes.json` 列出增删走线和过孔；完整原生检查在 `final-audit/`。`export` 会再次验收并导出到新目录，不自动采纳到原工程。

当前支持现代格式双层板、普通焊盘、直线铜段和通孔过孔；铺铜、铜弧、自定义焊盘、复杂自定义规则及不稳定对象身份等会被明确拒绝，不会静默删除或转换。原有违规可以保留并逐项报告，通过检查不表示可以直接投产。

详见：[安装](docs/INSTALL.md)、[操作](docs/USAGE.md)、[支持范围](docs/SUPPORT.md)、[离线验收](docs/VALIDATION.md)、[研究结果](docs/RESEARCH.md)、[故障处理](docs/TROUBLESHOOTING.md)。
