# GitHub Issues to Hugo Publisher

将GitHub Issues自动转换为Hugo内容文件的GitHub Action解决方案，无需本地环境。

![示例](sample.jpg）

## 🚀 快速开始

### 1. 添加文件到您的Hugo仓库
将这两个文件复制到您的Hugo项目仓库中：
```
.github/workflows/issue_to_hugo_content.yml
.github/workflows/issue_to_hugo.py
```

### 2. 配置GitHub Secrets
在仓库设置中创建Personal Access Token：
1. 访问 `Settings > Secrets and variables > Actions`
2. 点击 `New repository secret`
3. 创建名为 `PAT_TOKEN` 的secret
4. 值：具有 `repo` 权限的GitHub Token

### 3. 创建内容目录
在Hugo仓库根目录创建空目录：
```bash
mkdir -p content/posts
git add content/posts
git commit -m "创建内容目录"
```

### 4. 使用Issues发布内容
1. 创建新Issue
2. 添加 **发布** 标签
3. 正文格式：
```markdown
![封面图描述](图片URL)

您的Markdown内容...

$标签1$ $标签2$
```

## ⚙️ 自定义配置（可选）

### 修改分类
编辑 `issue_to_hugo.py` 文件：
```python
# 支持的分类列表（第11行左右）
CATEGORY_MAP = ["生活", "技术", "学习", "思考", "项目"]
```

### 修改发布标签
```python
# 触发发布的标签（第13行左右）
PUBLISH_LABEL = "发布"  # 可改为 "publish" 等
```

### 修改输出目录
编辑 `issue_to_hugo_content.yml` 文件：
```yaml
# 所有content/posts替换为其他目录
path: "content/your-custom-folder"
```

## 🌟 功能特点

1. **自动转换** - 带"发布"标签的Issue自动生成Hugo内容
2. **图片处理** - 远程图片自动下载到本地
3. **标签系统** - 使用 `$标签$` 语法添加标签
4. **封面图支持** - 正文首张图片自动设为封面
5. **变更检测** - 仅当内容变化时才触发提交

## 💡 示例Issue格式

```markdown
![美丽的风景](https://example.com/sunset.jpg)

## 我的第一篇博客

这是一篇通过GitHub Issue发布的博客...

$旅行$ $摄影$ $2024$
```

## 🔧 工作流程说明

1. 创建带"发布"标签的Issue
2. GitHub Action自动触发
3. 转换脚本将Issue转为Hugo格式
4. 图片下载到内容目录
5. 自动提交到仓库
6. 触发Hugo构建（需您配置构建工作流）

## ⚠️ 注意事项

1. 确保您的Hugo站已配置构建工作流（可参考[Hugo官方部署指南](https://gohugo.io/hosting-and-deployment/hosting-on-github/)）
2. 使用 `$标签$` 语法时需放在**最后一行**
3. 封面图必须是正文第一张图片
4. 避免使用 `IssueBot` 作为用户名（工作流会跳过该用户）

## ❓ 常见问题

### Q: 如何触发手动转换？
在仓库Actions页面，选择 `Sync Issues to Hugo Content` 工作流，点击 `Run workflow`

### Q: 内容生成在哪里？
在 `content/posts/YYYYMMDD_问题号/index.md` 目录

### Q: 如何添加多个分类？
目前仅支持单个分类（取第一个匹配标签），多分类需修改脚本
```

## 文件路径说明

### 必需的文件结构

```markdown
your-hugo-repo/
├── .github/
│   └── workflows/
│       ├── issue_to_hugo_content.yml   # GitHub Action工作流
│       └── issue_to_hugo.py            # 转换脚本
├── content/
│   └── posts/                          # 生成的内容目录(需预先创建)
└── ...                                 # Hugo其他文件
```

### 关联Hugo构建（示例工作流）
在 `.github/workflows/hugo.yml` 添加：
```yaml
name: Hugo Build

on: 
  repository_dispatch:
    types: [hugo-build-trigger]
  push:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        
      - name: Setup Hugo
        uses: peaceiris/actions-hugo@v2
        with:
          hugo-version: 'latest'
          
      - name: Build
        run: hugo --minify
      
      - name: Deploy
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.PAT_TOKEN }}
          publish_dir: ./public
```

如有其他问题，可查看原文：[如何使用 GitHub Issue 发布 Hugo 博客](https://lawtee.com/article/publish-hugo-by-github-issue/)
