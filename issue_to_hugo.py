import os
import argparse
import re
import requests
import json
import logging
from urllib.parse import unquote
from datetime import datetime
from github import Github, Auth
from bs4 import BeautifulSoup

# ======================
# 用户可配置区域（修改这些常量以适应您的需求）
# ======================

# 支持的分类列表（请根据实际需求修改）
CATEGORY_MAP = ["生活", "技术", "学习", "思考", "项目"]

# 触发发布的标签（可替换为其他标签名）
PUBLISH_LABEL = "发布"

# ======================
# 核心功能函数
# ======================

def setup_logger(debug=False):
    """配置日志记录器"""
    logger = logging.getLogger('issue-to-hugo')
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)
    
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger

def is_within_code_block(text, position):
    """
    检查指定位置是否在代码块内
    支持多行代码块（```）和内联代码（`）
    """
    lines = text.split('\n')
    in_code_block = False
    in_inline_code = False
    char_count = 0
    
    for line in lines:
        line_start = char_count
        line_end = char_count + len(line) + 1
        
        # 检查当前位置是否在当前行
        if position >= line_start and position <= line_end:
            if in_inline_code or in_code_block:
                return True
        
        # 检测多行代码块
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
        
        # 检测内联代码
        inline_code_matches = list(re.finditer(r'`[^`]+`', line))
        for match in inline_code_matches:
            start, end = match.span()
            if position >= line_start + start and position <= line_start + end:
                return True
        
        char_count += len(line) + 1
    
    return in_code_block

def extract_cover_image(body):
    """从正文提取首张非代码块图片作为封面图"""
    img_pattern = r"!\[([^\]]*?)\]\((https?:\/\/[^\)]+)\)"
    matches = list(re.finditer(img_pattern, body))
    
    for match in matches:
        img_url = match.group(2)
        start_pos = match.start()
        if not is_within_code_block(body, start_pos):
            # 移除封面图标记
            body = body[:match.start()] + body[match.end():]
            return img_url, body
    return None, body

def safe_filename(filename):
    """生成安全的文件名（保留合法字符和扩展名）"""
    clean_url = re.sub(r"\?.*$", "", filename)  # 移除URL参数
    basename = os.path.basename(clean_url)
    decoded_name = unquote(basename)  # URL解码
    
    name, ext = os.path.splitext(decoded_name)
    safe_name = re.sub(r"[^a-zA-Z0-9\-_]", "_", name)  # 替换非法字符
    
    # 验证图片扩展名
    valid_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
    if not ext.lower() in valid_extensions:
        ext = ""
    
    # 限制文件名长度
    if len(safe_name) > 100 - len(ext):
        safe_name = safe_name[:100 - len(ext)]
    
    return safe_name + ext

def download_image(url, output_path, token=None):
    """
    下载图片到本地
    基于内容类型自动确定文件扩展名
    """
    try:
        headers = {}
        if token:
            headers['Authorization'] = f'token {token}'
        
        response = requests.get(url, stream=True, headers=headers)
        if response.status_code == 200:
            # 根据Content-Type确定文件类型
            content_type = response.headers.get("content-type", "").lower()
            ext = ".jpg"  # 默认扩展名
            if "image/png" in content_type:
                ext = ".png"
            elif "image/jpeg" in content_type:
                ext = ".jpg"
            elif "image/gif" in content_type:
                ext = ".gif"
            elif "image/webp" in content_type:
                ext = ".webp"
            
            # 处理输出路径
            base, current_ext = os.path.splitext(output_path)
            if current_ext.lower() not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                output_path = base + ext
            
            # 保存图片
            with open(output_path, 'wb') as f:
                f.write(response.content)
            logging.info(f"下载成功: {url} -> {output_path}")
            return output_path
        else:
            logging.error(f"下载失败，状态码: {response.status_code}, URL: {url}")
    except Exception as e:
        logging.error(f"下载图片失败: {url} - {e}")
    return None

def replace_image_urls(body, issue_number, output_dir, token=None):
    """
    替换正文中的图片URL为本地路径
    跳过代码块内的图片
    """
    # Markdown图片语法
    md_img_pattern = r"!\[([^\]]*?)\]\((https?:\/\/[^\)]+)\)"
    # HTML图片标签
    html_img_pattern = r'<img[^>]+src=["\']?(https?:\/\/[^"\'>]+)["\']?'
    
    def md_replacer(match):
        """Markdown图片替换处理函数"""
        if is_within_code_block(body, match.start()):
            return match.group(0)  # 跳过代码块内的图片
        alt_text = match.group(1)
        img_url = match.group(2)
        filename = f"{issue_number}_{safe_filename(img_url)}"
        output_path = os.path.join(output_dir, filename)
        final_path = download_image(img_url, output_path, token)
        if final_path:
            final_filename = os.path.basename(final_path)
            return f"![{alt_text}]({final_filename})"
        return match.group(0)
    
    def html_replacer(match):
        """HTML图片替换处理函数"""
        if is_within_code_block(body, match.start()):
            return match.group(0)
        img_url = match.group(1)
        alt_match = re.search(r'alt=["\']?([^"\'>]+)["\']?', match.group(0))
        alt_text = alt_match.group(1) if alt_match else 'Image'
        filename = f"{issue_number}_{safe_filename(img_url)}"
        output_path = os.path.join(output_dir, filename)
        final_path = download_image(img_url, output_path, token)
        if final_path:
            final_filename = os.path.basename(final_path)
            return f"![{alt_text}]({final_filename})"
        return match.group(0)
    
    # 执行替换
    body = re.sub(md_img_pattern, md_replacer, body, flags=re.IGNORECASE)
    body = re.sub(html_img_pattern, html_replacer, body, flags=re.IGNORECASE)
    return body

def sanitize_markdown(content):
    """清理Markdown中不安全的HTML标签"""
    if not content:
        return ""
    
    # 仅允许安全的HTML标签
    soup = BeautifulSoup(content, "html.parser")
    allowed_tags = [
        "p", "a", "code", "pre", "blockquote", 
        "ul", "ol", "li", "strong", "em", 
        "img", "h1", "h2", "h3", "h4", "h5", "h6"
    ]
    
    for tag in soup.find_all(True):
        if tag.name not in allowed_tags:
            tag.unwrap()  # 移除非允许标签但保留内容
    
    return str(soup)

def extract_tags_from_body(body, logger):
    """从正文最后一行提取标签（跳过代码块）"""
    if not body:
        return [], body
    
    body = body.replace('\r\n', '\n').rstrip()
    lines = body.split('\n')
    if not lines:
        return [], body
    
    last_line = lines[-1].strip()
    char_position = len(body) - len(last_line)
    
    # 检查是否在代码块中
    if is_within_code_block(body, char_position):
        logger.debug("最后一行在代码块内，跳过标签提取")
        return [], body
    
    # 使用 $tag$ 格式提取标签
    tags = re.findall(r'\$(.+?)\$', last_line, re.UNICODE)
    tags = [tag.strip() for tag in tags if tag.strip()]
    
    if tags:
        # 移除标签行
        body = '\n'.join(lines[:-1]).rstrip()
        logger.debug(f"提取到标签: {tags}")
    
    return tags, body

def convert_issue(issue, output_dir, token, logger):
    """转换单个issue为Hugo内容"""
    try:
        labels = [label.name for label in issue.labels]
        
        # 检查是否带发布标签
        if PUBLISH_LABEL not in labels or issue.state != "open":
            logger.debug(f"跳过 issue #{issue.number} - 未标记为发布")
            return False
        
        # 创建内容目录
        pub_date = issue.created_at.strftime("%Y%m%d")
        slug = f"{pub_date}_{issue.number}"  # 唯一标识符
        post_dir = os.path.join(output_dir, slug)
        
        if os.path.exists(post_dir):
            logger.info(f"跳过 issue #{issue.number} - 内容已存在")
            return False
        
        os.makedirs(post_dir, exist_ok=True)
        
        # 处理正文内容
        body = issue.body or ""
        cover_url, body = extract_cover_image(body)  # 提取封面图
        tags, body = extract_tags_from_body(body, logger)  # 提取标签
        body = sanitize_markdown(body)  # 清理HTML
        body = replace_image_urls(body, issue.number, post_dir, token)  # 处理图片
        
        # 确定分类（取第一个匹配的标签）
        categories = [tag for tag in labels if tag in CATEGORY_MAP]
        category = categories[0] if categories else "未分类"
        
        # 下载封面图
        cover_name = None
        if cover_url:
            try:
                cover_filename = f"cover_{safe_filename(cover_url)}"
                cover_path = os.path.join(post_dir, cover_filename)
                final_cover_path = download_image(cover_url, cover_path, token)
                if final_cover_path:
                    cover_name = os.path.basename(final_cover_path)
                    logger.info(f"封面图已下载: {cover_url}")
            except Exception as e:
                logger.error(f"封面图下载失败: {cover_url} - {e}")
        
        # 生成Front Matter
        frontmatter_lines = [
            "---",
            f'title: "{issue.title.replace(\'"\', \'\\\\"\')}"',  # 转义双引号
            f'date: "{issue.created_at.strftime("%Y-%m-%d")}"',
            f'slug: "{slug}"',
            f'categories: ["{category.replace(\'"\', \'\\\\"\')}"]',
            f'tags: {json.dumps(tags, ensure_ascii=False)}'
        ]
        
        if cover_name:
            frontmatter_lines.append(f'image: "{cover_name}"')
        
        frontmatter_lines.append("---\n")
        frontmatter = "\n".join(frontmatter_lines)
        
        # 写入Markdown文件
        md_file = os.path.join(post_dir, "index.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)
        
        logger.info(f"转换完成: issue #{issue.number} -> {md_file}")
        return True
    except Exception as e:
        logger.exception(f"转换失败 issue #{issue.number}")
        error_file = os.path.join(output_dir, f"ERROR_{issue.number}.tmp")
        with open(error_file, "w") as f:
            f.write(f"转换错误: {str(e)}")
        return False

def main():
    """主程序入口"""
    args = parse_arguments()
    logger = setup_logger(args.debug)
    
    # 获取GitHub Token
    token = args.token or os.getenv("GITHUB_TOKEN")
    if not token:
        logger.error("缺少GitHub Token")
        return
    
    try:
        # 连接GitHub API
        auth = Auth.Token(token)
        g = Github(auth=auth)
        repo = g.get_repo(args.repo)
        logger.info(f"已连接仓库: {args.repo}")
    except Exception as e:
        logger.error(f"连接GitHub失败: {str(e)}")
        return
    
    # 准备输出目录
    os.makedirs(args.output, exist_ok=True)
    logger.info(f"输出目录: {os.path.abspath(args.output)}")
    
    processed_count = 0
    error_count = 0
    
    try:
        # 处理所有打开的Issues
        issues = repo.get_issues(state="open")
        total_issues = issues.totalCount
        logger.info(f"开始处理 {total_issues} 个 Issues")
        
        for issue in issues:
            if issue.pull_request:  # 跳过PR
                continue
            try:
                if convert_issue(issue, args.output, token, logger):
                    processed_count += 1
            except Exception as e:
                error_count += 1
                logger.error(f"处理失败 issue #{issue.number}: {str(e)}")
                try:
                    # 在Issue中添加错误信息
                    error_comment = f"⚠️ 转换失败，请检查格式:\n\n```\n{str(e)}\n```"
                    if len(error_comment) > 65536:
                        error_comment = error_comment[:65000] + "\n```\n...(内容过长)"
                    
                    issue.create_comment(error_comment)
                    
                    # 添加错误标签
                    try:
                        error_label = repo.get_label("conversion-error")
                    except:
                        error_label = repo.create_label("conversion-error", "ff0000")
                    issue.add_to_labels(error_label)
                except Exception as inner_e:
                    logger.error(f"添加评论失败: {inner_e}")
    except Exception as e:
        logger.exception(f"获取Issues失败: {e}")
        
    # 输出统计信息
    summary = f"处理完成! 成功: {processed_count}, 失败: {error_count}"
    logger.info(summary)
        
    if args.debug:
        logger.debug("目录内容:")
        logger.debug(os.listdir(args.output))

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='将GitHub Issues转换为Hugo内容')
    parser.add_argument('--token', help='GitHub访问令牌')
    parser.add_argument('--repo', required=True, help='GitHub仓库 (owner/repo)')
    parser.add_argument('--output', default='content/posts', help='输出目录')
    parser.add_argument('--debug', action='store_true', help='启用调试日志')
    return parser.parse_args()

if __name__ == "__main__":
    main()
