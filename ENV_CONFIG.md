# 环境变量配置说明

## 创建 .env 文件

在项目根目录创建 `.env` 文件，配置以下环境变量：

```env
# 阿里百炼 API 配置
OPENAI_API_KEY=your_qwen_api_key_here
OPENAI_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

## 配置说明

- **OPENAI_API_KEY**: 你的阿里百炼 API Key
- **OPENAI_API_BASE_URL**: API 基础 URL（如果使用阿里百炼，使用上述 URL）
  - 如果使用其他兼容 OpenAI API 的服务，修改此 URL 即可

## 获取 API Key

1. 访问 [阿里云百炼平台](https://dashscope.aliyuncs.com/)
2. 注册/登录账号
3. 创建 API Key
4. 将 API Key 填入 `.env` 文件

## 注意事项

- `.env` 文件已添加到 `.gitignore`，不会被提交到版本控制
- 确保不要将包含真实 API Key 的 `.env` 文件提交到代码仓库

