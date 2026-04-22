# 🎨 VerseMesh 诗意晶格

**AI审美参数编译器** - 将文字意境转化为可视化参数

## ✅ 项目状态

- 可运行的 Streamlit 应用（`app.py`）
- 支持智谱 GLM API 连接测试与审美参数编译
- 输出结构化 JSON + Midjourney 提示词

## ✨ 功能特色

- 🧠 **深度意境解析**：基于智谱GLM大模型理解诗歌、短句的审美层次
- 🎯 **参数化输出**：将感性审美转化为结构化视觉参数
- 🚀 **AI绘图集成**：自动生成Midjourney等工具的精准提示词
- 🎨 **交互式界面**：实时调节抽象程度、视觉张力等参数

## 🚀 快速开始

### 1) 创建并激活虚拟环境

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2) 安装依赖

```powershell
pip install -r requirements.txt
```

### 3) 配置环境变量

复制 `.env.example` 为 `.env`，并填写智谱（文本解析）与百炼（图像生成）API Key：

```env
ZHIPUAI_API_KEY=你的真实密钥
ZHIPUAI_MODEL_NAME=glm-4-plus
BAILIAN_API_KEY=你的百炼密钥
WAN_IMAGE_MODEL_NAME=wan2.7-image-pro
```

### 4) 启动应用

```powershell
streamlit run app.py
```

启动后在浏览器打开终端输出的本地地址（通常是 `http://localhost:8501`）。

## 🎮 使用方法

1. **输入文本**：在左侧输入框填入诗句或短句
2. **调节参数**：滑动调整抽象程度和视觉张力
3. **执行编译**：点击"执行编译"按钮开始分析
4. **查看结果**：
   - 核心主题和艺术家参考
   - 色彩面板参数
   - 情绪向量分析
   - 完整的JSON数据结构
   - 生成的Midjourney提示词

## 🔧 技术栈

- **后端框架**：Streamlit
- **AI模型**：智谱GLM（文本解析）+ 百炼Wan2.7-Image-Pro（图像生成）
- **数据处理**：JSON结构化输出
- **界面设计**：自定义CSS + Streamlit组件

## 🧩 项目结构

```text
VerseMesh_Project/
├─ app.py              # Streamlit 主程序
├─ requirements.txt    # Python 依赖
├─ .env.example        # 环境变量示例
└─ README.md
```

## ❗常见问题

### 依赖安装失败怎么办？

- 请优先使用 Python 3.10~3.12（兼容性更稳定）
- 先升级 pip：`python -m pip install --upgrade pip`
- 确保在项目虚拟环境中执行安装命令

### 提示“未找到 ZHIPUAI_API_KEY”

- 检查项目根目录下是否存在 `.env`
- 确认键名为 `ZHIPUAI_API_KEY` 且值非空
- 修改后重启 `streamlit run app.py`

### 提示“未配置 BAILIAN_API_KEY”

- 在项目根目录 `.env` 中添加 `BAILIAN_API_KEY=你的百炼API Key`
- 建议同时保留 `WAN_IMAGE_MODEL_NAME=wan2.7-image-pro`
- 修改后重启 `streamlit run app.py`

## 📄 许可证

MIT License