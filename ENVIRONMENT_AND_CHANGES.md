# 环境配置与代码修改说明

本文档详细说明 ChatBI 项目的环境配置方法和代码修改内容。

## 目录

- [环境配置](#环境配置)
- [代码修改内容](#代码修改内容)
- [常见问题](#常见问题)

---

## 环境配置

### 1. Python 环境

#### 使用 Conda（推荐）

```bash
# 激活 nlp 环境
conda activate nlp

# 如果环境不存在，创建新环境
conda env create -n nlp -f environment.yml
conda activate nlp
```

#### 使用其他方式

```bash
# 使用 pip
pip install -r requirements.txt

# 或使用 uv
uv sync
```

### 2. 环境变量配置

#### 方式一：系统环境变量（推荐）

在系统环境变量中设置：

```bash
# macOS/Linux (添加到 ~/.zshrc 或 ~/.bashrc)
export OPENAI_API_KEY="your_qwen_api_key_here"
export OPENAI_API_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"

# 使配置生效
source ~/.zshrc  # 或 source ~/.bashrc
```

#### 方式二：.env 文件

在项目根目录创建 `.env` 文件：

```env
# 阿里百炼 API 配置
OPENAI_API_KEY=your_qwen_api_key_here
OPENAI_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

**注意**：代码已优化，优先使用系统环境变量，如果系统环境变量已设置，`.env` 文件不会覆盖它。

### 3. 获取 API Key

1. 访问 [阿里云百炼平台](https://dashscope.aliyuncs.com/)
2. 注册/登录账号
3. 创建 API Key
4. 将 API Key 配置到环境变量或 `.env` 文件

### 4. 向量数据库初始化

```bash
# 进入 tools 目录
cd tools

# 生成向量数据库（需要激活 conda 环境）
conda run -n nlp python ingest_chromadb.py
```

这会读取 `docs/` 目录下的所有 `.md` 文件，生成 embedding 并存储到项目根目录的 `chroma_langchain_db/`。

### 5. 示例数据库生成（可选）

```bash
cd tools
conda run -n nlp python generate_sqlite_data.py
```

---

## 代码修改内容

### 1. 环境变量读取优化 (`agent.py`)

#### 修改前
- 在模块加载时读取环境变量，可能导致无法读取到最新值
- `load_dotenv()` 可能覆盖系统环境变量

#### 修改后
- 使用 `load_dotenv(override=False)` 确保系统环境变量优先
- 将环境变量读取改为动态函数，在运行时获取最新值
- 添加了 `get_env_var()` 辅助函数统一管理环境变量读取
- 将 `model_configurations` 改为函数 `get_model_configurations()`，确保每次调用时读取最新环境变量

**关键代码**：
```python
# 加载 .env 文件，但不覆盖已存在的系统环境变量
load_dotenv(override=False)

def get_env_var(var_name: str, default: Optional[str] = None) -> Optional[str]:
    """从系统环境变量或 .env 文件获取环境变量，优先使用系统环境变量"""
    value = os.getenv(var_name, default)
    return value

def get_model_configurations():
    """动态获取模型配置，确保每次调用时都读取最新的环境变量"""
    api_key = get_env_var("OPENAI_API_KEY")
    base_url = get_env_var("OPENAI_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    # ...
```

### 2. 向量数据库路径统一修复

#### 问题描述
- `ingest_chromadb.py` 写入到项目根目录的 `chroma_langchain_db`
- `tools_rag.py` 从 `tools/chroma_langchain_db` 读取
- 路径不一致导致向量数据库更新无效

#### 修复方案

**文件：`tools/tools_rag.py`**

修改前：
```python
current_file_dir = os.path.dirname(os.path.abspath(__file__))
CHROMADB_PATH = os.path.join(current_file_dir, "chroma_langchain_db")
```

修改后：
```python
current_file_dir = os.path.dirname(os.path.abspath(__file__))
# 统一使用项目根目录的向量数据库路径
upper_dir = os.path.dirname(current_file_dir)  # 项目根目录
CHROMADB_PATH = os.path.join(upper_dir, "chroma_langchain_db")
```

**文件：`tools/ingest_chromadb.py`**

修改前：
```python
persist_directory="../chroma_langchain_db"  # 相对路径
```

修改后：
```python
# 使用绝对路径，统一使用项目根目录的向量数据库
chromadb_path = os.path.join(upper_dir, "chroma_langchain_db")
persist_directory=chromadb_path
```

**结果**：两个文件现在都使用项目根目录的 `chroma_langchain_db/`，确保写入和读取路径一致。

### 3. Deprecation Warning 修复

**文件：`tools/tools_rag.py`**

修改前：
```python
from langchain.vectorstores import Chroma  # 已弃用
```

修改后：
```python
from langchain_community.vectorstores import Chroma  # 使用新导入
```

### 4. 错误处理改进

**文件：`agent.py`**

在 `create_agent()` 函数中添加了更详细的错误信息：

```python
if not config.api_key:
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        raise ValueError(f"API key for model '{model_name}' is empty. Please check your environment variable OPENAI_API_KEY.")
    else:
        raise ValueError(
            f"API key for model '{model_name}' is not set. "
            f"Please set the OPENAI_API_KEY environment variable. "
            f"You can set it in your system environment or create a .env file in the project root."
        )
```

### 5. 新增文档

为了增强 RAG 功能，新增了两个文档：

1. **`docs/query_examples.md`**
   - 包含常见查询场景和 SQL 示例
   - 数据可视化建议
   - 常见问题解答

2. **`docs/database_overview.md`**
   - 数据库结构概览
   - 表关系说明
   - 常用查询模式

---

## 常见问题

### Q1: 环境变量设置了但代码读取不到？

**A**: 确保：
1. 系统环境变量已正确设置（使用 `echo $OPENAI_API_KEY` 验证）
2. 如果使用 `.env` 文件，确保文件在项目根目录
3. 重启应用/终端使环境变量生效
4. 代码已优化为优先读取系统环境变量

### Q2: 向量数据库更新后没有生效？

**A**: 检查：
1. 确保 `ingest_chromadb.py` 和 `tools_rag.py` 使用相同的路径（都是项目根目录的 `chroma_langchain_db/`）
2. 重新运行 `python ingest_chromadb.py` 更新数据库
3. 重启应用使更改生效

### Q3: 如何验证环境变量是否正确配置？

**A**: 运行以下命令：

```bash
# 检查系统环境变量
echo $OPENAI_API_KEY
echo $OPENAI_API_BASE_URL

# 或在 Python 中检查
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(override=False); print('API Key:', 'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET')"
```

### Q4: 向量数据库路径在哪里？

**A**: 
- 项目根目录：`/Users/mhhh/ChatBI/chroma_langchain_db/`
- 这是统一使用的路径，所有相关代码都已更新为使用此路径

### Q5: 如何更新向量数据库？

**A**: 

```bash
# 1. 确保在正确的环境
conda activate nlp

# 2. 进入 tools 目录
cd tools

# 3. 运行更新脚本
conda run -n nlp python ingest_chromadb.py
```

---

## 修改文件清单

1. **agent.py**
   - 优化环境变量读取机制
   - 添加动态配置函数
   - 改进错误提示

2. **tools/tools_rag.py**
   - 修复向量数据库路径
   - 修复 deprecation warning
   - 统一使用项目根目录路径

3. **tools/ingest_chromadb.py**
   - 使用绝对路径替代相对路径
   - 统一使用项目根目录路径

4. **docs/query_examples.md** (新增)
   - 查询示例和常见问题

5. **docs/database_overview.md** (新增)
   - 数据库概览文档

---

## 验证步骤

完成配置后，按以下步骤验证：

1. **验证环境变量**：
   ```bash
   python3 -c "import os; from dotenv import load_dotenv; load_dotenv(override=False); print('OPENAI_API_KEY:', 'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET')"
   ```

2. **验证向量数据库**：
   ```bash
   python3 -c "import chromadb; client = chromadb.PersistentClient(path='chroma_langchain_db'); collection = client.get_collection('example_collection'); print(f'文档数量: {collection.count()}')"
   ```

3. **启动应用**：
   ```bash
   streamlit run main.py
   ```

4. **测试查询**：
   - "查询所有产品类别"
   - "如何查询最近一个月的订单？"
   - "数据库中有哪些表？"

---

## 更新日期

最后更新：2024-11-09

---

## 相关文档

- [ENV_CONFIG.md](ENV_CONFIG.md) - 环境变量配置详细说明
- [CONDA_SETUP.md](CONDA_SETUP.md) - Conda 环境配置指南
- [README.md](README.md) - 项目总体说明

